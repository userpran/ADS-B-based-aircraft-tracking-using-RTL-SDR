# ----------------------
# ADS-B Python Decoder with dynamic CPR pairing
# ----------------------
import numpy as np
import pyModeS as pms
import pandas as pd
import os

# ----------------------
# Step 1: Input/output files
# ----------------------
input_file = "flight_20251016_03.bin"  # raw IQ samples at 2 MHz
output_csv = "decoded_summary.csv"

if not os.path.isfile(input_file):
    raise FileNotFoundError(f"Input file '{input_file}' not found.")

# ----------------------
# Step 2: Read raw IQ samples
# ----------------------
raw = np.fromfile(input_file, dtype=np.int8)
iq = raw.astype(np.float32).view(np.complex64)
print(f"Total IQ samples read: {len(iq)}")

# ----------------------
# Step 3: Preamble detection (2 MHz)
# ----------------------
PREAMBLE_SAMPLES = 16  # 8 µs at 2 MHz
def detect_preambles(iq, threshold=0.5):
    magnitude = np.abs(iq)
    magnitude = (magnitude - np.min(magnitude)) / (np.max(magnitude) - np.min(magnitude))
    preambles = []
    for i in range(len(magnitude) - PREAMBLE_SAMPLES):
        window = magnitude[i:i+PREAMBLE_SAMPLES]
        corr = np.sum((window > 0.5).astype(int) == np.array([1,0,1,0,1,0,1,0,0,0,0,0,0,0,0,0]))
        if corr >= 14:
            preambles.append(i)
    return preambles

preamble_positions = detect_preambles(iq)
print(f"Detected {len(preamble_positions)} preambles")

# ----------------------
# ----------------------
# Step 4: Extract 112-bit messages with robust bit sampling
# ----------------------
# ----------------------
# Step 4: Extract 112-bit messages with dynamic preamble shift
# ----------------------
BIT_SAMPLES = 2          # 2 samples per bit at 2 MHz
PREAMBLE_SAMPLES = 16    # 16 samples per 8 µs preamble

def extract_bits(iq, start_idx, bit_samples=BIT_SAMPLES, preamble_samples=PREAMBLE_SAMPLES):
    """
    Extract 112-bit ADS-B message starting from preamble index.
    Returns a list of 112 bits.
    """
    bits = []
    for i in range(112):
        idx_start = start_idx + preamble_samples + i * bit_samples
        idx_end = idx_start + bit_samples
        if idx_end > len(iq):
            break
        avg = np.mean(np.real(iq[idx_start:idx_end]))  # average over bit interval
        bits.append(1 if avg > 0 else 0)
    return bits

def bits_to_hex(bits):
    """
    Convert list of bits to hex string for pyModeS.
    """
    s = ''.join(str(b) for b in bits)
    return '{:028X}'.format(int(s, 2))

def extract_valid_hex(iq, preamble_idx, shift_range=(-2,3)):
    """
    Try multiple preamble shifts to get valid CRC.
    Returns first valid hex message or None if all fail.
    """
    for shift in range(*shift_range):
        bits = extract_bits(iq, preamble_idx + shift)
        if len(bits) != 112:
            continue
        hex_msg = bits_to_hex(bits)
        # CRC check for DF17 only
        if pms.df(hex_msg) == 17 and pms.crc(hex_msg) is not None:
            return hex_msg
    return None


# ----------------------
# Step 5: Decode messages with dynamic even/odd CPR
# ----------------------
messages_list = []
aircraft_state = {}  # ICAO -> last even/odd DF17 messages

for idx in preamble_positions:
    bits = extract_bits(iq, idx)
    if len(bits) != 112:
        continue
    hex_msg = bits_to_hex(bits)

    try:
        if pms.df(hex_msg) != 17:
            continue

        # CRC check
        if pms.crc(hex_msg) is None:
            continue

        icao = pms.icao(hex_msg)
        type_code = pms.typecode(hex_msg)

        if icao not in aircraft_state:
            aircraft_state[icao] = {"even": None, "odd": None}

        row = {"Hex": icao, "Flight": "", "Altitude": "", "Speed": "",
               "Lat": "", "Lon": "", "Track": ""}

        # Callsign
        if type_code in range(1,5):
            callsign = pms.callsign(hex_msg)
            if callsign:
                row["Flight"] = callsign.strip()

        # Altitude / Position
        if type_code >= 9 and type_code <= 18:
            alt = pms.altitude(hex_msg)
            if alt is not None:
                row["Altitude"] = alt

            oe = pms.oe_flag(hex_msg)
            if oe == 0:
                aircraft_state[icao]["even"] = hex_msg
            else:
                aircraft_state[icao]["odd"] = hex_msg

            even_msg = aircraft_state[icao]["even"]
            odd_msg = aircraft_state[icao]["odd"]
            if even_msg and odd_msg:
                lat, lon = pms.position(even_msg, odd_msg)
                if lat is not None and lon is not None:
                    row["Lat"] = lat
                    row["Lon"] = lon

        # Velocity / Track
        if type_code >= 19 and type_code <= 27:
            speed = pms.airspeed(hex_msg)
            heading = pms.heading(hex_msg)
            if speed is not None:
                row["Speed"] = speed
            if heading is not None:
                row["Track"] = heading

        if any([row["Flight"], row["Altitude"], row["Speed"], row["Lat"], row["Lon"], row["Track"]]):
            messages_list.append(row)

    except Exception:
        continue

# ----------------------
# Step 6: DataFrame & summary
# ----------------------
df_summary = pd.DataFrame(messages_list)
if not df_summary.empty:
    df_summary["Messages Seen"] = df_summary.groupby("Hex")["Hex"].transform("count")
    df_summary = df_summary.sort_values(by="Messages Seen", ascending=False)

# ----------------------
# Step 7: Save CSV and print
# ----------------------
df_summary.to_csv(output_csv, index=False)
print(f"Summary saved to {output_csv}")
print(df_summary)
print(f"Total valid messages: {len(df_summary)}")
print("Sampling rate set to 2 MHz (for SDR acquisition).")
