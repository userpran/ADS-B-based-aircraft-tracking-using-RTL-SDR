"""
ADS-B Decoder Pipeline
Reads IQ samples from either a live FIFO or an existing .bin/.iq file,
decodes DF17 ADS-B messages, and feeds position data to the az/el pipeline.

Usage:
    # File mode — test with existing recording
    python3 -m src.decoder_module.adsb_decoder_pipeline --file captures/iq_samples_20260322_190751.bin .csv

    # File mode — no output save
    python3 -m src.decoder_module.adsb_decoder_pipeline --file src/decoder_module/iq_samples_20251019_172049_619.bin

    # Live FIFO mode — no output save (launcher handles this normally)
    python3 -m src.decoder_module.adsb_decoder_pipeline

    # Live FIFO mode — save CSV
    python3 -m src.decoder_module.adsb_decoder_pipeline .csv
"""

import numpy as np
import sys
import os
import math
import time
from collections import defaultdict
from src.azel_module.azel_pipeline import start_azel_thread, stop_azel_thread, submit_decoded_position

# ── Constants ────────────────────────────────────────────────────────────────
SAMPLE_RATE          = 2_000_000   # 2 Msps
PREAMBLE_SAMPLES     = 16          # 8 µs × 2 samples/µs
BITS_PER_FRAME       = 112
SAMPLES_PER_BIT      = 2           # 1 µs × 2 samples/µs
DATA_SAMPLES         = BITS_PER_FRAME * SAMPLES_PER_BIT   # 224 
FRAME_SAMPLES        = PREAMBLE_SAMPLES + DATA_SAMPLES    # 240
FRAME_BYTES          = FRAME_SAMPLES * 2                  # IQ bytes per frame
TAIL_BYTES           = (FRAME_SAMPLES - 1) * 2            # carry between chunks
CHUNK_SIZE           = 262_144                            # 256 KB per read
FIFO_PATH            = "/tmp/iq_pipe"
CRC_POLY             = 0xFFF409
THRESHOLD_MULTIPLIER = 4.5

# ── CRC table (built once at import) ─────────────────────────────────────────
def _build_crc_table():
    table = []
    for i in range(256):
        c = i << 16
        for _ in range(8):
            if c & 0x800000:
                c = (c << 1) ^ CRC_POLY
            else:
                c <<= 1
        table.append(c & 0xFFFFFF)
    return table

_CRC_TABLE = _build_crc_table()

def crc24(data_bytes):
    """Fast CRC-24 using lookup table."""
    rem = 0
    for b in data_bytes:
        rem = ((rem << 8) ^ _CRC_TABLE[((rem >> 16) ^ b) & 0xFF]) & 0xFFFFFF
    return rem

def check_crc(msg_bytes):
    """Returns True if the last 3 bytes are a valid CRC over the first 11 bytes."""
    return crc24(msg_bytes[:11]) == ((msg_bytes[11] << 16) | (msg_bytes[12] << 8) | msg_bytes[13])

# ── Vectorised preamble detection ────────────────────────────────────────────
# Mode S preamble at 2 Msps:
#   High samples: indices 0, 2, 7, 9
#   Low  samples: indices 1, 3, 4, 5, 6, 8
_HIGH = np.array([0, 2, 7, 9], dtype=np.intp)
_LOW  = np.array([1, 3, 4, 5, 6, 8], dtype=np.intp)

def detect_preamble_vectorised(magnitude):
    """
    Vectorised preamble scan — evaluates all candidate positions simultaneously.
    Returns array of frame start indices.
    """
    n     = len(magnitude)
    limit = n - FRAME_SAMPLES
    if limit <= 0:
        return np.array([], dtype=np.intp)

    positions = np.arange(limit, dtype=np.intp)

    high_sum = np.zeros(limit, dtype=np.float32)
    for h in _HIGH:
        high_sum += magnitude[positions + h]

    low_sum = np.zeros(limit, dtype=np.float32)
    for l in _LOW:
        low_sum += magnitude[positions + l]

    mean_high = high_sum / len(_HIGH)
    mean_low  = low_sum  / len(_LOW)
    threshold = np.mean(magnitude) * THRESHOLD_MULTIPLIER

    candidates = np.where(
        (magnitude[positions + 0] > threshold) &
        (magnitude[positions + 2] > threshold) &
        (magnitude[positions + 7] > threshold) &
        (magnitude[positions + 9] > threshold) &
        (mean_high > mean_low * 2.5)
    )[0]

    if len(candidates) == 0:
        return candidates

    # Non-max suppression: one detection per frame window
    kept = []
    last = -FRAME_SAMPLES
    for idx in candidates:
        if idx - last >= FRAME_SAMPLES:
            kept.append(idx)
            last = idx
    return np.array(kept, dtype=np.intp)

# ── Bit decoding (vectorised) ─────────────────────────────────────────────────
def decode_bits_vectorised(magnitude, start_idx):
    """
    Decodes 112 PPM bits → 14 bytes in one NumPy operation.
    Returns list of 14 ints, or None if out-of-bounds.
    """
    data_start = start_idx + PREAMBLE_SAMPLES
    end        = data_start + DATA_SAMPLES
    if end > len(magnitude):
        return None

    data        = magnitude[data_start:end]
    first_half  = data[0::2]
    second_half = data[1::2]
    bits        = (first_half > second_half).astype(np.uint8)
    bit_matrix  = bits.reshape(14, 8)
    powers      = np.array([128, 64, 32, 16, 8, 4, 2, 1], dtype=np.uint16)
    msg_bytes   = (bit_matrix @ powers).astype(np.uint8)
    return msg_bytes.tolist()

# ── CPR Decoding ──────────────────────────────────────────────────────────────
def cpr_nl(lat):
    """NL(lat) — number of longitude zones."""
    if abs(lat) >= 87.0: return 1
    if abs(lat) == 0.0:  return 59
    inner = (1.0 - math.cos(math.pi / 30.0)) / (math.cos(math.radians(lat)) ** 2)
    if inner >= 1.0: return 1
    return int(math.floor(2.0 * math.pi / math.acos(1.0 - inner)))

def cpr_decode(even_msg, odd_msg):
    """
    Decodes global airborne position from an even + odd CPR pair.
    Returns (lat, lon) rounded to 5 decimal places, or None on failure.
    """
    MAX      = 131072.0
    lat0_enc, lon0_enc = even_msg
    lat1_enc, lon1_enc = odd_msg

    cpr_lat0 = lat0_enc / MAX
    cpr_lat1 = lat1_enc / MAX

    j    = math.floor(59.0 * cpr_lat0 - 60.0 * cpr_lat1 + 0.5)
    lat0 = (360.0 / 60.0) * (j % 60 + cpr_lat0)
    lat1 = (360.0 / 59.0) * (j % 59 + cpr_lat1)

    if lat0 >= 270.0: lat0 -= 360.0
    if lat1 >= 270.0: lat1 -= 360.0

    if cpr_nl(lat0) != cpr_nl(lat1):
        return None

    final_lat = lat0
    nl_val    = cpr_nl(final_lat)
    n_even    = max(nl_val, 1)

    cpr_lon0 = lon0_enc / MAX
    cpr_lon1 = lon1_enc / MAX

    m   = math.floor(cpr_lon0 * (nl_val - 1) - cpr_lon1 * nl_val + 0.5)
    lon = (360.0 / n_even) * (m % n_even + cpr_lon0)
    if lon >= 180.0:
        lon -= 360.0

    return round(final_lat, 5), round(lon, 5)

# ── Receiver reference position (for local CPR decode) ───────────────────────
# Set ground station coordinates as receriver reference position.
# Accuracy is good within ~200 NM of the receiver.
# Set both to None to fall back to global CPR.
RECEIVER_LAT = 8.5241
RECEIVER_LON = 76.9366

def cpr_decode_local(lat_enc, lon_enc, f_flag, ref_lat, ref_lon):
    """
    Local CPR decode using receiver position as reference.
    Works on a SINGLE frame — no even+odd pair needed.
    f_flag: 0 = even frame, 1 = odd frame
    Returns (lat, lon) rounded to 5 decimal places.
    """
    MAX     = 131072.0
    NZ      = 15
    d_lat   = (360.0 / (4 * NZ)) if (f_flag == 0) else (360.0 / (4 * NZ - 1))
    cpr_lat = lat_enc / MAX

    j       = math.floor(ref_lat / d_lat) + math.floor(
              0.5 + ((ref_lat % d_lat) / d_lat) - cpr_lat)
    lat     = d_lat * (j + cpr_lat)

    nl_lat  = cpr_nl(lat)
    n       = (max(nl_lat, 1)) if (f_flag == 0) else (max(nl_lat - 1, 1))
    d_lon   = 360.0 / n
    cpr_lon = lon_enc / MAX

    m   = math.floor(ref_lon / d_lon) + math.floor(
              0.5 + ((ref_lon % d_lon) / d_lon) - cpr_lon)
    lon = d_lon * (m + cpr_lon)

    return round(lat, 5), round(lon, 5)

# ── Aircraft CPR state store ──────────────────────────────────────────────────
# icao -> {'even': (lat_enc, lon_enc), 'odd': (lat_enc, lon_enc)}
aircraft_cpr = defaultdict(dict)

# ── DF17 parser ───────────────────────────────────────────────────────────────
def parse_df17(msg_bytes, detected_signals):
    """Parses a 14-byte DF17 message, updates CPR store, appends to detected_signals."""
    try:
        df = (msg_bytes[0] >> 3) & 0x1F
        if df != 17:
            return

        icao = (msg_bytes[1] << 16) | (msg_bytes[2] << 8) | msg_bytes[3]
        data = msg_bytes[4:11]
        tc   = (data[0] >> 3) & 0x1F

        if not (9 <= tc <= 18):
            return

        # Altitude
        # alt_bits = ME bits 8-19 (12 bits): 8 from data[1], 4 from data[2] top nibble
        # q_bit    = ME bit 15 = LSB of data[1]  (NOT from data[2])
        # if Q=1: strip q_bit → n = top 7 bits shifted left 4 + bottom 4 bits
        alt_bits = ((data[1] & 0xFF) << 4) | ((data[2] >> 4) & 0x0F)   # 12-bit field
        q_bit    = data[1] & 0x01                                      # LSB of data[1]
        if q_bit:
            n        = ((alt_bits >> 5) << 4) | (alt_bits & 0x0F)      # remove Q bit
            altitude = n * 25 - 1000
        else:
            altitude = alt_bits * 100 - 1000

        # CPR position
        f_flag  = (data[2] >> 2) & 0x01
        lat_enc = ((data[2] & 0x03) << 15) | (data[3] << 7) | (data[4] >> 1)
        lon_enc = ((data[4] & 0x01) << 16) | (data[5] << 8) | data[6]

        if f_flag == 0:
            aircraft_cpr[icao]['even'] = (lat_enc, lon_enc)
        else:
            aircraft_cpr[icao]['odd']  = (lat_enc, lon_enc)

        lat, lon  = 0.0, 0.0
        cpr_store = aircraft_cpr[icao]

        if RECEIVER_LAT is not None and RECEIVER_LON is not None:
            # Primary: local CPR — works on every single frame
            result = cpr_decode_local(lat_enc, lon_enc, f_flag,
                                      RECEIVER_LAT, RECEIVER_LON)
            if result:
                lat, lon = result
        elif 'even' in cpr_store and 'odd' in cpr_store:
            # Fallback: global CPR — needs an even+odd pair
            result = cpr_decode(cpr_store['even'], cpr_store['odd'])
            if result:
                lat, lon = result

        hex_msg = ''.join(f'{b:02X}' for b in msg_bytes)
        detected_signals.append({
            "icao": f"0x{icao:06X}",
            "type": "Airborne Position",
            "alt":  altitude,
            "lat":  lat,
            "lon":  lon,
            "raw":  hex_msg,
        })

        submit_decoded_position(f"0x{icao:06X}", lat, lon, altitude)

    except Exception:
        pass

# ── Signal processing ─────────────────────────────────────────────────────────
def process_signals(magnitude):
    """Detects preambles, decodes, CRC-checks, parses DF17. Returns signal list."""
    start_indices = detect_preamble_vectorised(magnitude)
    valid_signals = []
    for idx in start_indices:
        msg_bytes = decode_bits_vectorised(magnitude, idx)
        if msg_bytes is None or len(msg_bytes) != 14:
            continue
        if not check_crc(msg_bytes):
            continue
        parse_df17(msg_bytes, valid_signals)
    return valid_signals

# ── IQ conversion ─────────────────────────────────────────────────────────────
def iq_bytes_to_magnitude(raw_bytes):
    """Converts raw RTL-SDR IQ bytes to magnitude array."""
    iq        = np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32) - 127.5
    i_samples = iq[0::2]
    q_samples = iq[1::2]
    return np.abs(i_samples) + np.abs(q_samples) #Use np.sqrt(i_samples ** 2 + q_samples ** 2) for true magnitude, but abs sum is faster and good enough for detection

# ── Chunk iterators ───────────────────────────────────────────────────────────
def iter_chunks_fifo(fifo_path):
    """
    Yields raw IQ byte chunks from the FIFO.
    Blocks until data arrives. Stops when the write-end closes (EOF).
    """
    print(f"[ADS-B decoder] Opening FIFO: {fifo_path}")
    with open(fifo_path, "rb") as f:
        print("[ADS-B decoder] FIFO open — waiting for data...\n")
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                # EOF — C++ capture finished and closed the write end
                return
            yield chunk

def iter_chunks_file(file_path):
    """
    Yields raw IQ byte chunks from an existing .bin/.iq file until EOF.
    """
    if not os.path.isfile(file_path):
        print(f"[ADS-B decoder] ERROR: File not found: {file_path}")
        return
    file_size = os.path.getsize(file_path)
    print(f"[ADS-B decoder] Reading file : {file_path}")
    print(f"[ADS-B decoder] File size    : {file_size / 1024 / 1024:.2f} MB "
          f"({file_size // 2:,} samples)\n")
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                return   # EOF
            yield chunk

# ── Shared decode loop ────────────────────────────────────────────────────────
def run_decode_loop(chunk_iterator):
    """
    Runs the decode loop over any chunk iterator (works for both FIFO and file).
    Returns list of all decoded signals.
    """
    all_signals  = []
    carry        = b""
    total_chunks = 0

    for chunk in chunk_iterator:
        total_chunks += 1
        raw = carry + chunk

        if len(raw) < FRAME_BYTES:
            carry = raw
            continue

        magnitude = iq_bytes_to_magnitude(raw)
        signals   = process_signals(magnitude)

        if signals:
            display_signals(signals)
            all_signals.extend(signals)

        # Keep tail so frames crossing chunk boundaries are not lost
        carry = raw[-TAIL_BYTES:] if len(raw) > TAIL_BYTES else raw

    print(f"\n[ADS-B decoder] Processed {total_chunks} chunk(s).")
    return all_signals

# ── Display ───────────────────────────────────────────────────────────────────
def display_signals(valid_signals):
    print(f"\n{'─'*70}")
    print(f"  Decoded {len(valid_signals)} ADS-B message(s)")
    print(f"{'─'*70}")
    print(f"  {'ICAO':<12} {'ALT (ft)':>10}  {'LAT':>12}  {'LON':>12}  RAW")
    print(f"{'─'*70}")
    for s in valid_signals:
        lat_str = f"{s['lat']:>12.5f}" if s['lat'] != 0.0 else f"{'Partial':>12}"
        lon_str = f"{s['lon']:>12.5f}" if s['lon'] != 0.0 else f"{'Partial':>12}"
        print(f"  {s['icao']:<12} {s['alt']:>10}  {lat_str}  {lon_str}  {s['raw']}")

# ── File output ───────────────────────────────────────────────────────────────
def save_output(valid_signals, ext):
    from datetime import datetime
    now      = datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H%M")

    script_dir   = os.path.dirname(os.path.abspath(__file__))  # src/decoder_module/
    project_root = os.path.dirname(os.path.dirname(script_dir))                  # project_root/
    out_dir      = os.path.join(project_root, "decoder_output", date_str)
    os.makedirs(out_dir, exist_ok=True)

    out_path = os.path.join(out_dir, f"output{time_str}{ext}")

    if ext == ".csv":
        import csv
        with open(out_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["icao", "alt", "lat", "lon", "raw"])
            for s in valid_signals:
                w.writerow([s['icao'], s['alt'], s['lat'], s['lon'], s['raw']])
        print(f"CSV saved  → {out_path}")
    else:
        import json
        with open(out_path, 'w') as f:
            json.dump(
                [{"icao": s['icao'], "alt": s['alt'],
                  "lat":  s['lat'],  "lon": s['lon']} for s in valid_signals],
                f, indent=2
            )
        print(f"JSON saved → {out_path}")

# ── Argument parsing ──────────────────────────────────────────────────────────
def parse_args():
    """
    Parses sys.argv. Returns (mode, file_path, out_ext).

    Supported signatures:
        decoder.py                               → fifo,  no save
        decoder.py .csv                          → fifo,  save CSV
        decoder.py .json                         → fifo,  save JSON
        decoder.py --file data.bin               → file,  no save
        decoder.py --file data.bin .csv          → file,  save CSV
        decoder.py --file data.bin .json         → file,  save JSON
    """
    args      = sys.argv[1:]
    mode      = "fifo"
    file_path = None
    out_ext   = None

    if "--file" in args:
        idx  = args.index("--file")
        mode = "file"
        if idx + 1 < len(args):
            file_path = args[idx + 1]
        else:
            print("[ADS-B decoder] ERROR: --file requires a path argument.")
            print("  Usage: decoder.py --file path/to/iq_samples.bin [.csv|.json]")
            sys.exit(1)
        # Any remaining arg that looks like an extension is the output format
        remaining = [a for i, a in enumerate(args) if i != idx and i != idx + 1]
        if remaining and remaining[0].lower() in (".csv", ".json"):
            out_ext = remaining[0].lower()
    else:
        if args and args[0].lower() in (".csv", ".json"):
            out_ext = args[0].lower()

    return mode, file_path, out_ext

# ── Main ──────────────────────────────────────────────────────────────────────
def main():

    mode, file_path, out_ext = parse_args()

    print(f"[ADS-B decoder] Mode   : {'FILE → ' + file_path if mode == 'file' else 'LIVE FIFO'}")
    print(f"[ADS-B decoder] Output : {out_ext if out_ext else 'none (console only)'}")
    print(f"[ADS-B decoder] Az/El  : enabled\n")

    start_azel_thread()
    all_signals = []

    try:
        chunk_iter  = iter_chunks_file(file_path) if mode == "file" else iter_chunks_fifo(FIFO_PATH)
        all_signals = run_decode_loop(chunk_iter)

    except KeyboardInterrupt:
        print("\n[ADS-B decoder] Stopped by user.")
    except FileNotFoundError as e:
        print(f"[ADS-B decoder] Not found: {e}")
    finally:
        stop_azel_thread()

    if out_ext and all_signals:
        save_output(all_signals, out_ext)
    elif not all_signals:
        print("[ADS-B decoder] No valid ADS-B messages decoded.")

    print("[ADS-B decoder] Done.")


if __name__ == "__main__":
    main()
