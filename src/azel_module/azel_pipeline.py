import threading
import queue
import csv
import time
from datetime import datetime
import pymap3d as pm
import os


data_q = queue.Queue() #create a shared fifo

# Ground station position
gs_lat = 8.5000
gs_lon = 76.9000
gs_alt = 0   # sea level

# Filters
MAX_ALT_FT = 50000          # ignore impossible altitudes
MAX_ALT_CHANGE_FT = 2000    # ignore sudden spikes
MIN_LAT = -90
MAX_LAT = 90
MIN_LON = -180
MAX_LON = 180


last_alt_ft = {}  # store last altitude per ICAO for jump filtering

running = False   # Thread running flag
thread_ref = None # Store thread reference

def valid_row(icao, lat, lon, alt_ft):
    # Reject completely missing or zero values
    if lat == 0 or lon == 0:
        return False

    # Reject out-of-range coordinates
    if not (MIN_LAT <= lat <= MAX_LAT):
        return False
    if not (MIN_LON <= lon <= MAX_LON):
        return False

    # Reject impossible altitudes
    if alt_ft <= 0 or alt_ft > MAX_ALT_FT:
        return False

    # Reject sudden altitude jumps
    if icao in last_alt_ft:
        if abs(alt_ft - last_alt_ft[icao]) > MAX_ALT_CHANGE_FT:
            return False

    # Passed all filters → store last altitude
    last_alt_ft[icao] = alt_ft
    return True


# DECODER CALLS THIS FUNCTION
def submit_decoded_position(icao, lat, lon, alt_ft):
    """ called by your decoder immediately after CPR decode """
    data_q.put((icao, lat, lon, alt_ft))

# ======================================================
# AZ/EL WORKER THREAD
# ======================================================
def azel_worker():
    print("[AzEl] Worker started")

    
    # Create CSV with timestamp name
    
    now = datetime.now()

    # Build path to the azel_module folder (where this script is located)
    module_dir = os.path.dirname(__file__)
    filename = os.path.join(module_dir, f"azel_{now.strftime('%m%d_%H%M')}.csv")

    out = open(filename, "w", newline="")
    writer = csv.writer(out)
    writer.writerow(["time", "icao", "lat", "lon", "alt_ft", "az_deg", "el_deg", "range_m"])
    print(f"[AzEl] Writing to: {filename}")

    try:
        while running or not data_q.empty():
            try:
                icao, lat, lon, alt_ft = data_q.get(timeout=0.5)
            except queue.Empty:
                continue

            if not valid_row(icao, lat, lon, alt_ft):
                continue

            alt_m = alt_ft * 0.3048
            az, el, slant = pm.geodetic2aer(lat, lon, alt_m, gs_lat, gs_lon, gs_alt)
            t = datetime.now().strftime("%H:%M:%S")

            writer.writerow([t, icao, lat, lon, alt_ft, az, el, slant])
            out.flush()
            print(f"{t} {icao} AZ={az:.1f}° EL={el:.1f}° Range={slant/1000:.1f} km")
    finally:
        out.close()
        print("[AzEl] Worker stopped")


# ======================================================
# CALL THIS ONCE IN main()
# ======================================================
def start_azel_thread():
    global running, last_alt_ft, thread_ref

    # Reset state for a fresh run
    running = True
    last_alt_ft.clear()
    with data_q.mutex:
        data_q.queue.clear()

    # Start worker thread
    thread_ref = threading.Thread(target=azel_worker, daemon=True)
    thread_ref.start()
    print("[AzEl] Thread running")

def stop_azel_thread():
    global running, thread_ref
    running = False
    if thread_ref is not None:
        thread_ref.join(timeout=2)
        print("[AzEl] Thread joined")