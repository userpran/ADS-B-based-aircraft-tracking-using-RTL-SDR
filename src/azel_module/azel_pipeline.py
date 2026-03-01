import threading
import queue
import csv
import time
from datetime import datetime
import pymap3d as pm
import os

# ── Optional serial import ────────────────────────────────────────────────────
# If pyserial is not installed, Arduino mode is simply unavailable.
try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# ── Arduino serial config ─────────────────────────────────────────────────────
ARDUINO_PORT     = '/dev/ttyACM0'   # change to 'COM3' etc on Windows
ARDUINO_BAUDRATE = 115200

# ── Shared queue ──────────────────────────────────────────────────────────────
data_q = queue.Queue()

# ── Ground station position ───────────────────────────────────────────────────
gs_lat = 8.5000
gs_lon = 76.9000
gs_alt = 0   # metres, sea level

# ── Filters ───────────────────────────────────────────────────────────────────
MAX_ALT_FT        = 50000   # ignore impossible altitudes
MAX_ALT_CHANGE_FT = 2000    # ignore sudden spikes
MIN_LAT = -90;  MAX_LAT = 90
MIN_LON = -180; MAX_LON = 180

last_alt_ft = {}   # last altitude per ICAO for jump filtering
running     = False
thread_ref  = None

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
    last_alt_ft[icao] = alt_ft
    return True

# ── Called by decoder ─────────────────────────────────────────────────────────
def submit_decoded_position(icao, lat, lon, alt_ft):
    """Called by the ADS-B decoder immediately after CPR decode."""
    data_q.put((icao, lat, lon, alt_ft))

# ── Arduino serial helper ─────────────────────────────────────────────────────
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
        time.sleep(2)   # wait for Arduino to reset after serial connect
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
        return None   # caller sets ser = None, disabling further writes

# ── Az/El worker thread ───────────────────────────────────────────────────────
def azel_worker():
    print("[AzEl] Worker started")

    # ── CSV setup ─────────────────────────────────────────────────────────────
    now        = datetime.now()
    module_dir = os.path.dirname(__file__)
    filename   = os.path.join(module_dir, f"azel_{now.strftime('%m%d_%H%M')}.csv")
    out        = open(filename, "w", newline="")
    writer     = csv.writer(out)
    writer.writerow(["time", "icao", "lat", "lon", "alt_ft",
                     "az_deg", "el_deg", "range_m"])
    print(f"[AzEl] Writing to: {filename}")

    # ── Serial setup (optional) ───────────────────────────────────────────────
    # try_open_serial() returns None silently if Arduino is not connected.
    # The rest of the pipeline is completely unaffected either way.
    ser = try_open_serial()

    try:
        while running or not data_q.empty():
            try:
                icao, lat, lon, alt_ft = data_q.get(timeout=0.5)
            except queue.Empty:
                continue

            if not valid_row(icao, lat, lon, alt_ft):
                continue

            # ── Compute az/el ─────────────────────────────────────────────────
            alt_m          = alt_ft * 0.3048
            az, el, slant  = pm.geodetic2aer(lat, lon, alt_m,
                                             gs_lat, gs_lon, gs_alt)
            t = datetime.now().strftime("%H:%M:%S")

            # ── Write CSV (always) ────────────────────────────────────────────
            writer.writerow([t, icao, lat, lon, alt_ft, az, el, slant])
            out.flush()
            print(f"{t} {icao} AZ={az:.1f}° EL={el:.1f}° Range={slant/1000:.1f} km")

            # ── Send to Arduino (only if connected) ───────────────────────────
            if ser is not None:
                ser = send_to_arduino(ser, az, el)
                # send_to_arduino returns None on failure → ser becomes None
                # → all future iterations skip the serial block automatically

    finally:
        # Always close CSV
        out.close()
        print("[AzEl] Worker stopped")
        # Close serial if it was open
        if ser is not None:
            try:
                ser.close()
                print("[AzEl] Serial port closed.")
            except Exception:
                pass

# ── Thread control ────────────────────────────────────────────────────────────
def start_azel_thread():
    global running, last_alt_ft, thread_ref

    running = True
    last_alt_ft.clear()
    with data_q.mutex:
        data_q.queue.clear()

    thread_ref = threading.Thread(target=azel_worker, daemon=True)
    thread_ref.start()
    print("[AzEl] Thread running")

def stop_azel_thread():
    global running, thread_ref
    running = False
    if thread_ref is not None:
        thread_ref.join(timeout=2)
        print("[AzEl] Thread joined")
