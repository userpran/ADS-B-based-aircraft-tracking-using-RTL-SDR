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
ARDUINO_PORT     = '/dev/ttyUSB0'
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
ser_global  = None   # module-level serial handle — shared between worker and stop

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
    
    # ── Serial setup (optional) ───────────────────────────────────────────────
    # try_open_serial() returns None silently if Arduino is not connected.
    #ser = try_open_serial()

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

            if ser is not None:
                ser = send_to_arduino(ser, az, el)
                ser_global = ser   # keep module-level ref in sync

    finally:
        out.close()
        print("[AzEl] Worker stopped")
        if ser is not None:
            try:
                ser.close()
                print("[AzEl] Serial port closed.")
            except Exception:
                pass
        ser_global = None

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

    # Send HOME command using the module-level ser reference
    # (worker may have already closed it so open fresh if needed)
    if SERIAL_AVAILABLE:
        try:
            # Open a fresh connection for homing
            ser = serial.Serial(ARDUINO_PORT, ARDUINO_BAUDRATE, timeout=3)
            time.sleep(1)
            ser.reset_input_buffer()
            ser.write(b"HOME\n")
            print("[AzEl] Waiting for motors to return home...")
            deadline = time.time() + 30
            while time.time() < deadline:
                response = ser.readline().decode().strip()
                if "Homed" in response:
                    print("[AzEl] Motors at home position.")
                    break
                elif response:
                    print(f"[AzEl] Arduino: {response}")
            else:
                print("[AzEl] WARNING: Homing timeout.")
            ser.close()
        except Exception as e:
            print(f"[AzEl] Could not home Arduino: {e}")

# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    # TEMPORARY MOTOR TEST — only runs when azel_pipeline.py run standalone
    # run with: python3 src/azel_module/azel_pipeline.py

    start_azel_thread()

    import threading as _t
    def inject_test_data():
        test_positions = [
    # ── Sweep North → Southeast (AZ 0° → 120°) — 20 steps ───────────────
    ("0x123456", 9.60, 76.90, 4000),   # AZ ~0°
    ("0x123456", 9.55, 76.96, 4000),   # AZ ~6°
    ("0x123456", 9.50, 77.02, 4000),   # AZ ~12°
    ("0x123456", 9.44, 77.08, 4000),   # AZ ~18°
    ("0x123456", 9.38, 77.14, 4000),   # AZ ~24°
    ("0x123456", 9.30, 77.19, 4000),   # AZ ~30°
    ("0x123456", 9.22, 77.24, 4000),   # AZ ~36°
    ("0x123456", 9.13, 77.29, 4000),   # AZ ~42°
    ("0x123456", 9.03, 77.33, 4000),   # AZ ~48°
    ("0x123456", 8.93, 77.37, 4000),   # AZ ~54°
    ("0x123456", 8.82, 77.41, 4000),   # AZ ~60°
    ("0x123456", 8.71, 77.47, 4000),   # AZ ~66°
    ("0x123456", 8.62, 77.53, 4000),   # AZ ~72°
    ("0x123456", 8.55, 77.59, 4000),   # AZ ~78°
    ("0x123456", 8.51, 77.65, 4000),   # AZ ~84°
    ("0x123456", 8.50, 77.71, 4000),   # AZ ~90°
    ("0x123456", 8.38, 77.68, 4000),   # AZ ~96°
    ("0x123456", 8.25, 77.63, 4000),   # AZ ~102°
    ("0x123456", 8.10, 77.55, 4000),   # AZ ~111°
    ("0x123456", 7.90, 77.40, 4000),   # AZ ~120°

    # ── Return Southeast → North (AZ 120° → 0°) — 20 steps ───────────────
    ("0x123456", 8.10, 77.55, 4000),   # AZ ~111°
    ("0x123456", 8.25, 77.63, 4000),   # AZ ~102°
    ("0x123456", 8.38, 77.68, 4000),   # AZ ~96°
    ("0x123456", 8.50, 77.71, 4000),   # AZ ~90°
    ("0x123456", 8.51, 77.65, 4000),   # AZ ~84°
    ("0x123456", 8.55, 77.59, 4000),   # AZ ~78°
    ("0x123456", 8.62, 77.53, 4000),   # AZ ~72°
    ("0x123456", 8.71, 77.47, 4000),   # AZ ~66°
    ("0x123456", 8.82, 77.41, 4000),   # AZ ~60°
    ("0x123456", 8.93, 77.37, 4000),   # AZ ~54°
    ("0x123456", 9.03, 77.33, 4000),   # AZ ~48°
    ("0x123456", 9.13, 77.29, 4000),   # AZ ~42°
    ("0x123456", 9.22, 77.24, 4000),   # AZ ~36°
    ("0x123456", 9.30, 77.19, 4000),   # AZ ~30°
    ("0x123456", 9.38, 77.14, 4000),   # AZ ~24°
    ("0x123456", 9.44, 77.08, 4000),   # AZ ~18°
    ("0x123456", 9.50, 77.02, 4000),   # AZ ~12°
    ("0x123456", 9.55, 76.96, 4000),   # AZ ~6°
    ("0x123456", 9.60, 76.90, 4000),   # AZ ~0°
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
        