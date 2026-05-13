import threading
import queue
import csv
import time
from datetime import datetime
import pymap3d as pm
import os

# ── Optional serial import ────────────────────────────────────────────────────
try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# ── Arduino serial config ─────────────────────────────────────────────────────
ARDUINO_PORT     = '/dev/ttyUSB0' #update according to which USB port the Arduino is on. 
ARDUINO_BAUDRATE = 115200

# ── Shared queue ──────────────────────────────────────────────────────────────
data_q = queue.Queue()

# ── Ground station position ───────────────────────────────────────────────────
gs_lat = 8.5000
gs_lon = 76.9000
gs_alt = 0

# ── Filters ───────────────────────────────────────────────────────────────────
MAX_ALT_FT        = 50000
MAX_ALT_CHANGE_FT = 2000
MIN_LAT = -90;  MAX_LAT = 90
MIN_LON = -180; MAX_LON = 180

last_alt_ft = {}
running     = False
thread_ref  = None
ser_global  = None   # module-level serial handle — shared between worker and stop function for homing command

# Priority option:
TRACKING_MODE = "closest"   # or "highest_el", "first_detected", "lowest_alt"
current_target = None   # ICAO of aircraft being tracked

# ── Validation ────────────────────────────────────────────────────────────────
def valid_row(icao, lat, lon, alt_ft):
    if lat == 0 or lon == 0:
        return False
    if not (MIN_LAT <= lat <= MAX_LAT):
        return False
    if not (MIN_LON <= lon <= MAX_LON):
        return False
    if alt_ft <= 0 or alt_ft > MAX_ALT_FT:
        return False
    if icao in last_alt_ft:
        if abs(alt_ft - last_alt_ft[icao]) > MAX_ALT_CHANGE_FT:
            return False
    last_alt_ft[icao] = alt_ft # last altitude per ICAO for jump filtering
    return True

# ── Called by decoder ─────────────────────────────────────────────────────────
def submit_decoded_position(icao, lat, lon, alt_ft):
    """Called by the ADS-B decoder immediately after CPR decode."""
    data_q.put((icao, lat, lon, alt_ft))

# ── Arduino serial helpers ────────────────────────────────────────────────────
def try_open_serial():
    """
    Attempts to open the Arduino serial port.
    Returns a serial.Serial object if successful, or None if:
      - pyserial is not installed
      - Arduino is not connected
      - Port is wrong or busy
    In all failure cases, pipeline continues in CSV-only mode.
    """
    if not SERIAL_AVAILABLE:
        print("[AzEl] pyserial not installed — Arduino output disabled.")
        return None
    try:
        ser = serial.Serial(ARDUINO_PORT, ARDUINO_BAUDRATE, timeout=1)
        time.sleep(2)   # wait for Arduino reset
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        # Read startup message if present
        if ser.in_waiting > 0:
            ready = ser.readline().decode().strip()
            print(f"[AzEl] Arduino says: {ready}")
        else:
            print("[AzEl] Arduino connected (no startup message — already running)")
        print(f"[AzEl] Arduino connected on {ARDUINO_PORT} at {ARDUINO_BAUDRATE} baud.")
        return ser
    except serial.SerialException as e:
        print(f"[AzEl] Arduino not available ({e}) — CSV-only mode.")
        return None

def send_to_arduino(ser, az, el):
    """
    Sends az/el to Arduino as a comma-separated string: 'az,el\n'
    e.g. '123.45,12.34\n'
    If the write fails (Arduino disconnected mid-run), logs and disables serial.
    Returns the ser object if still valid, or None if it failed.
    """
    try:
        msg = f"{az:.2f},{el:.2f}\n"
        ser.write(msg.encode('utf-8'))
        return ser
    except (serial.SerialException, OSError) as e:
        print(f"[AzEl] Serial write failed ({e}) — disabling Arduino output.")
        try:
            ser.close()
        except Exception:
            pass
        return None

def select_target(icao, az, el, slant):
    global current_target
    if current_target is None:
        current_target = icao   # lock onto first aircraft seen
    if icao == current_target:
        return True   # this is the target, track it
    return False      # ignore other aircraft

# ── Az/El worker thread ───────────────────────────────────────────────────────
def azel_worker(ser):
    """
    ser is passed in from start_azel_thread — already opened before
    any positions arrive so no serial commands get dropped.
    """
    global ser_global
    print("[AzEl] Worker started")

    # ── CSV setup ─────────────────────────────────────────────────────────────
    now        = datetime.now()
    module_dir = os.path.dirname(__file__)
    output_dir = os.path.join(module_dir, "..", "azel_output")
    os.makedirs(output_dir, exist_ok=True)
    filename   = os.path.join(output_dir, f"azel_{now.strftime('%m%d_%H%M')}.csv")
    out        = open(filename, "w", newline="")
    writer     = csv.writer(out)
    writer.writerow(["time", "icao", "lat", "lon", "alt_ft",
                     "az_deg", "el_deg", "range_m"])
    print(f"[AzEl] Writing to: {filename}")
    

    try:
        while running or not data_q.empty():
            try:
                icao, lat, lon, alt_ft = data_q.get(timeout=0.5)
            except queue.Empty:
                continue

            if not valid_row(icao, lat, lon, alt_ft):
                continue

            alt_m         = alt_ft * 0.3048
            az, el, slant = pm.geodetic2aer(lat, lon, alt_m,
                                            gs_lat, gs_lon, gs_alt)
            t = datetime.now().strftime("%H:%M:%S")

            writer.writerow([t, icao, lat, lon, alt_ft, az, el, slant])
            out.flush()
            print(f"{t} {icao} AZ={az:.1f}° EL={el:.1f}° Range={slant/1000:.1f} km")

            if ser is not None and select_target(icao, az, el, slant):
                ser = send_to_arduino(ser, az, el)
                ser_global = ser   # keep module-level ref in sync

    finally:
        out.close()
        print("[AzEl] Worker stopped")
        # if ser is not None:          # removed the ser.close() block from here as stop_azel_thread handles it
        #     try:
        #         ser.close()
        #         print("[AzEl] Serial port closed.")
        #     except Exception:
        #         pass
        #ser_global = None

# ── Thread control ────────────────────────────────────────────────────────────
def start_azel_thread():
    global running, last_alt_ft, thread_ref, ser_global

    running = True
    last_alt_ft.clear()
    with data_q.mutex:
        data_q.queue.clear()

    # Open serial BEFORE starting thread 
    # ready when first position arrives
    ser_global = try_open_serial()  #try_open_serial() returns None silently if Arduino is not connected.

    thread_ref = threading.Thread(target=azel_worker,
                                  args=(ser_global,), daemon=True)
    thread_ref.start()
    print("[AzEl] Thread running")

def stop_azel_thread():
    global running, thread_ref, ser_global
    running = False
    if thread_ref is not None:
        thread_ref.join(timeout=2)
        print("[AzEl] Thread joined")

    # Use existing serial connection for HOMING (avoids Arduino reset)
    if ser_global is not None:
        try:
            ser_global.reset_input_buffer()
            ser_global.write(b"HOME\n")
            print("[AzEl] Waiting for motors to return home...")
            deadline = time.time() + 30
            while time.time() < deadline:
                response = ser_global.readline().decode().strip()
                if "Homed" in response:
                    print("[AzEl] Motors at home position.")
                    break
                elif response:
                    print(f"[AzEl] Arduino: {response}")
            else:
                print("[AzEl] WARNING: Homing timeout.")
            ser_global.close()
            print("[AzEl] Serial port closed.")
        except Exception as e:
            print(f"[AzEl] Could not home Arduino: {e}")
    else:
        print("[AzEl] Arduino not connected — skipping home.")

# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    # TEMPORARY MOTOR TEST — only runs when azel_pipeline.py run standalone
    # run with: python3 azel_module/azel_pipeline.py

    start_azel_thread()

    import threading as _t
    def inject_test_data():
        test_positions = [
    # ── Far NW — low elevation, AZ ~315° ─────────────────────────────────
      ("0x123456", 9.80, 75.80, 5000),   # AZ~315° EL~3°   far NW
      ("0x123456", 9.70, 75.90, 5000),   # AZ~320° EL~4°
      ("0x123456", 9.60, 76.00, 5000),   # AZ~325° EL~5°
      ("0x123456", 9.50, 76.10, 5000),   # AZ~330° EL~6°
      ("0x123456", 9.35, 76.25, 5000),   # AZ~335° EL~8°
      ("0x123456", 9.20, 76.40, 5000),   # AZ~340° EL~11°
      ("0x123456", 9.05, 76.55, 5000),   # AZ~345° EL~15°
      ("0x123456", 8.90, 76.65, 5000),   # AZ~350° EL~20°

    # ── Approaching overhead — elevation rising sharply ───────────────────
      ("0x123456", 8.75, 76.75, 5000),   # AZ~355° EL~28°
      ("0x123456", 8.65, 76.82, 5000),   # AZ~358° EL~38°
      ("0x123456", 8.58, 76.87, 5000),   # AZ~359° EL~50°
      ("0x123456", 8.53, 76.90, 5000),   # AZ~0°   EL~65°  nearly overhead
      ("0x123456", 8.51, 76.91, 5000),   # AZ~10°  EL~75°  almost directly above
      ("0x123456", 8.50, 76.92, 5000),   # AZ~90°  EL~80°  peak elevation

    # ── Moving away to SE — elevation dropping, AZ swinging to SE ─────────
      ("0x123456", 8.48, 76.95, 5000),   # AZ~100° EL~65°
      ("0x123456", 8.45, 77.05, 5000),   # AZ~110° EL~45°
      ("0x123456", 8.40, 77.15, 5000),   # AZ~115° EL~30°
      ("0x123456", 8.30, 77.25, 5000),   # AZ~118° EL~20°
      ("0x123456", 8.15, 77.35, 5000),   # AZ~120° EL~12°
      ("0x123456", 7.95, 77.45, 5000),   # AZ~122° EL~7°   far SE
    ]
        for pos in test_positions:
            time.sleep(0.5)
            print(f"[Test] Injecting position: {pos}")
            submit_decoded_position(*pos)
    _t.Thread(target=inject_test_data, daemon=True).start()

    print("[AzEl] Running standalone test. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_azel_thread()
        print("[AzEl] Done.")
        