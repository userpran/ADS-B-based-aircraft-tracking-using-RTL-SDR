import numpy as np
import pyModeS as pms
import pandas as pd
import os

# ----------------------
# Configuration
# ----------------------
input_file = "flight_20251016_03.bin"
output_csv = "decoded_summary_2.csv"
SAMPLE_RATE = 2_000_000  # 2 MHz
MODES_PREAMBLE_US = 8  # 8 microseconds
MODES_LONG_MSG_BITS = 112
MODES_SHORT_MSG_BITS = 56

if not os.path.isfile(input_file):
    raise FileNotFoundError(f"Input file '{input_file}' not found.")

# ----------------------
# Read IQ samples
# ----------------------
print("Reading IQ samples...")
raw_data = np.fromfile(input_file, dtype=np.uint8)
print(f"Total raw samples: {len(raw_data)}")

# ----------------------
# Compute Magnitude Vector
# ----------------------
def compute_magnitude_vector(data):
    """Convert I/Q samples to magnitude"""
    i_samples = data[0::2].astype(np.int32) - 127
    q_samples = data[1::2].astype(np.int32) - 127
    magnitude = np.sqrt(i_samples**2 + q_samples**2).astype(np.uint16)
    return magnitude

print("Computing magnitude vector...")
magnitude = compute_magnitude_vector(raw_data)
print(f"Magnitude samples: {len(magnitude)}")
print(f"Magnitude range: {magnitude.min()} to {magnitude.max()}")

# ----------------------
# Detect Mode S Messages
# ----------------------
def detect_mode_s(m, mlen):
    """Detect Mode S messages with preamble detection"""
    messages = []
    j = 0
    
    print("Detecting Mode S messages...")
    full_len = MODES_PREAMBLE_US * 2 + MODES_LONG_MSG_BITS * 2
    
    while j < mlen - full_len:
        if j % 500000 == 0 and j > 0:
            print(f"  Scanned {j:,}/{mlen:,} samples, found {len(messages)} messages")
        
        # Preamble detection
        p = m[j:j+10]
        peaks = [p[0], p[2], p[7], p[9]]
        valleys = [p[1], p[3], p[4], p[5], p[6], p[8]]
        
        avg_peak = np.mean(peaks)
        avg_valley = np.mean(valleys)
        
        if avg_peak <= avg_valley * 1.5:
            j += 1
            continue
        
        if not (p[0] > p[1] and p[2] > p[3] and p[7] > p[8] and p[9] > p[6]):
            j += 1
            continue
        
        high_threshold = avg_peak * 0.7
        if p[4] > high_threshold or p[5] > high_threshold:
            j += 1
            continue
        
        if j + 15 < mlen:
            gap = m[j+11:j+15]
            if np.any(gap > high_threshold):
                j += 1
                continue
        
        # Decode bits
        bits = []
        errors = 0
        
        for i in range(0, MODES_LONG_MSG_BITS * 2, 2):
            idx = j + MODES_PREAMBLE_US * 2 + i
            if idx + 1 >= mlen:
                break
            
            low = int(m[idx])
            high = int(m[idx + 1])
            delta = abs(low - high)
            
            if i > 0 and delta < 2:
                bits.append(bits[-1])
            elif low == high:
                bits.append(2)
                if len(bits) <= MODES_SHORT_MSG_BITS:
                    errors += 1
            elif low > high:
                bits.append(1)
            else:
                bits.append(0)
        
        if len(bits) < MODES_LONG_MSG_BITS:
            j += 1
            continue
        
        if errors > 5:
            j += 1
            continue
        
        bits_clean = [0 if b == 2 else b for b in bits[:MODES_LONG_MSG_BITS]]
        
        # Pack bits into bytes
        msg_bytes = []
        for i in range(0, MODES_LONG_MSG_BITS, 8):
            byte = (bits_clean[i] << 7 | bits_clean[i+1] << 6 | 
                   bits_clean[i+2] << 5 | bits_clean[i+3] << 4 | 
                   bits_clean[i+4] << 3 | bits_clean[i+5] << 2 | 
                   bits_clean[i+6] << 1 | bits_clean[i+7])
            msg_bytes.append(byte)
        
        msg = bytes(msg_bytes)
        msgtype = msg[0] >> 3
        
        if msgtype in [16, 17, 19, 20, 21]:
            msglen = MODES_LONG_MSG_BITS // 8
        else:
            msglen = MODES_SHORT_MSG_BITS // 8
        
        # Signal quality check
        delta_sum = 0
        for i in range(0, min(msglen * 8 * 2, MODES_LONG_MSG_BITS * 2), 2):
            idx = j + MODES_PREAMBLE_US * 2 + i
            if idx + 1 < mlen:
                delta_sum += abs(int(m[idx]) - int(m[idx + 1]))
        
        delta_avg = delta_sum // (msglen * 4) if msglen > 0 else 0
        
        if delta_avg < 5:
            j += 1
            continue
        
        hex_msg = msg[:msglen].hex().upper()
        messages.append({
            'hex': hex_msg,
            'errors': errors
        })
        
        j += MODES_PREAMBLE_US * 2 + msglen * 8 * 2
    
    print(f"  Final scan complete: {len(messages)} messages detected")
    return messages

detected_messages = detect_mode_s(magnitude, len(magnitude))
print(f"\nDetected {len(detected_messages)} potential messages")

if len(detected_messages) == 0:
    print("\nNo messages detected.")
    exit(1)

# ----------------------
# Decode and Validate Messages
# ----------------------
print("\nValidating and decoding messages...")
valid_messages = []
aircraft_state = {}

for idx, msg_data in enumerate(detected_messages):
    if (idx + 1) % 100 == 0:
        print(f"  Processing {idx+1}/{len(detected_messages)}")
    
    hex_msg = msg_data['hex']
    hex_msg_padded = hex_msg.ljust(28, '0')
    
    try:
        df = pms.df(hex_msg_padded)
        
        if df != 17:
            continue
        
        crc = pms.crc(hex_msg_padded, encode=False)
        if crc != 0:
            continue
        
        icao = pms.icao(hex_msg_padded)
        type_code = pms.typecode(hex_msg_padded)
        
        if icao not in aircraft_state:
            aircraft_state[icao] = {"even": None, "odd": None, "callsign": ""}
        
        row = {
            "Hex": icao,
            "Flight": "",
            "Altitude": "",
            "Lat": "",
            "Lon": ""
        }
        
        # Decode callsign (Type Code 1-4)
        if 1 <= type_code <= 4:
            callsign = pms.adsb.callsign(hex_msg_padded)
            if callsign:
                callsign = callsign.strip()
                row["Flight"] = callsign
                aircraft_state[icao]["callsign"] = callsign
        
        # Decode position and altitude (Type Code 9-18)
        if 9 <= type_code <= 18:
            alt = pms.adsb.altitude(hex_msg_padded)
            if alt is not None:
                row["Altitude"] = alt
            
            oe_flag = pms.adsb.oe_flag(hex_msg_padded)
            if oe_flag == 0:
                aircraft_state[icao]["even"] = hex_msg_padded
            else:
                aircraft_state[icao]["odd"] = hex_msg_padded
            
            even_msg = aircraft_state[icao]["even"]
            odd_msg = aircraft_state[icao]["odd"]
            
            if even_msg and odd_msg:
                try:
                    lat, lon = pms.adsb.position(even_msg, odd_msg, 0, 0)
                    if lat is not None and lon is not None:
                        if -90 <= lat <= 90 and -180 <= lon <= 180:
                            row["Lat"] = round(lat, 6)
                            row["Lon"] = round(lon, 6)
                except:
                    pass
        
        # Use persistent callsign
        if not row["Flight"] and aircraft_state[icao]["callsign"]:
            row["Flight"] = aircraft_state[icao]["callsign"]
        
        # Save if has useful data
        if any([row["Flight"], row["Altitude"], row["Lat"], row["Lon"]]):
            valid_messages.append(row)
    
    except Exception as e:
        continue

print(f"\nDecoded {len(valid_messages)} valid messages")

# ----------------------
# Create Summary
# ----------------------
if not valid_messages:
    print("\nWARNING: No valid messages decoded!")
    exit(1)

df = pd.DataFrame(valid_messages)
df["Messages"] = df.groupby("Hex")["Hex"].transform("count")

# Aggregate by aircraft
summary = df.groupby("Hex").agg({
    "Flight": lambda x: x[x != ""].iloc[-1] if len(x[x != ""]) > 0 else "",
    "Altitude": lambda x: x[x != ""].iloc[-1] if len(x[x != ""]) > 0 else "",
    "Lat": lambda x: x[x != ""].iloc[-1] if len(x[x != ""]) > 0 else "",
    "Lon": lambda x: x[x != ""].iloc[-1] if len(x[x != ""]) > 0 else "",
    "Messages": "first"
}).reset_index()

summary = summary.sort_values("Messages", ascending=False)

# Save to CSV
summary.to_csv(output_csv, index=False)
print(f"\nSummary saved to {output_csv}")
print("\n" + "="*80)
print(summary.to_string(index=False))
print("="*80)
print(f"\nTotal aircraft detected: {len(summary)}")
print(f"Total messages decoded: {len(df)}")