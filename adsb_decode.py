# ----------------------
# ADS-B Python Decoder with dynamic CPR pairing
# ----------------------
import numpy as np # 
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
raw = np.fromfile(input_file, dtype=np.int8) # Read raw IQ samples
iq = raw.astype(np.float32).view(np.complex64) # Convert to complex64
# find size of raw and iq
print(f"Total raw samples read: {len(raw)}")
print(f"Total IQ samples read: {len(iq)}")

# ----------------------
# Step 3: Preamble detection (2 MHz)
# ----------------------
PREAMBLE_SAMPLES = 16  # 8 µs at 2 MHz
def detect_preambles(iq, threshold=0.5): 
    magnitude = np.abs(iq) # Compute magnitude
    magnitude = (magnitude - np.min(magnitude)) / (np.max(magnitude) - np.min(magnitude)) # Normalize to [0,1]
    print("length of magnitude array: ", len(magnitude))
    preambles = [] # List to hold preamble positions

    for i in range(len(magnitude) - PREAMBLE_SAMPLES): 
        window = magnitude[i:i+PREAMBLE_SAMPLES] # 16-sample window
        # Preamble pattern: 1,0,1,0,1,0,1,0,0,0,0,0,0,0,0,0

        # to optimise: right now, all indexes are being checked, can skip ahead by 16+(112*2) after finding a preamble
        
        # print("checking index:", i)
        # print("current window being checked for preamble:", window)
        
        corr = np.sum((window > 0.5).astype(int) == np.array([1,0,1,0,1,0,1,0,0,0,0,0,0,0,0,0])) # Correlation score
        if corr >= 14: # At least 14/16 matches
            print("detected preambles are at index:", i)
            print("detected preamble window:", window)
            
            preambles.append(i)
    return preambles

preamble_positions = detect_preambles(iq)
print(f"Detected {len(preamble_positions)} preambles")

# ----------------------

# ----------------------
# Step 4: Extract 112-bit messages with dynamic preamble shift
# ----------------------
BIT_SAMPLES = 2          # 2 samples per bit at 2 MHz
PREAMBLE_SAMPLES = 8 * BIT_SAMPLES    # 16 samples per 8 µs preamble

# copilot note: modified extract_bits to be vectorized for performance
# ...existing code...
def extract_bits(iq, start_idx, bit_samples=BIT_SAMPLES, preamble_samples=PREAMBLE_SAMPLES):
    """
    Vectorized extraction of up to 112 bits. Returns a list of bits.
    """
    total_needed = preamble_samples + 112 * bit_samples
    if start_idx + total_needed > len(iq): # prevent overflow
        # not enough samples to extract full message
        available_bits = (len(iq) - start_idx - preamble_samples) // bit_samples # number of bits that can be extracted
        if available_bits <= 0: 
            return []
        n_bits = min(112, available_bits)
    else:
        n_bits = 112

    start = start_idx + preamble_samples
    
    # why did we ever have this?
    # use magnitude instead of real part (phase invariant)
    # block = iq[start:start + n_bits * bit_samples]
    # windows = np.abs(block).reshape(n_bits, bit_samples)  # shape (n_bits, bit_samples)
    # means = windows.mean(axis=1, dtype=np.float64)
    # bits = (means > some_threshold).astype(int).tolist()
    

    # derive threshold from the preamble samples (data-driven)
    preamble_slice = np.abs(iq[start_idx:start_idx + preamble_samples]).astype(np.float32)
    mn = preamble_slice.min() # preamble min
    mx = preamble_slice.max() # preamble max
    rng = mx - mn # difference between preamble max and min (range)
    
    if rng > 1e-12: # avoid division by zero
        ps_norm = (preamble_slice - mn) / rng # normalized preamble
    else:
        # degenerate: tiny range -> fallback to zeros to avoid NaNs
        ps_norm = np.zeros_like(preamble_slice) # normalized preamble fallback

    pattern = np.array([1,0,1,0,1,0,1,0,0,0,0,0,0,0,0,0], dtype=bool)
    
    try:
        pulse_mean = ps_norm[pattern].mean() # mean of pulse positions
        noise_mean = ps_norm[~pattern].mean() # mean of noise positions
        some_threshold = 0.5 * (pulse_mean + noise_mean) # midpoint threshold
    except Exception:
        some_threshold = 0.5  # safe fallback if something goes wrong

    # normalize the message block using same mn/mx so "some_threshold" is meaningful
    block = np.abs(iq[start:start + n_bits * bit_samples]).astype(np.float32)  # use magnitude
    b_mn = block.min() # message block min 
    b_mx = block.max() # message block max
    b_rng = b_mx - b_mn # message block range
    
    if b_rng > 1e-12:
        block_norm = (block - b_mn) / b_rng  # normalize message block
    else:
        # if preamble was degenerate, use robust local scaling for block
        block_norm = (block - np.median(block)) / (np.std(block) + 1e-12) # robust normalization fallback

    windows = block_norm.reshape(n_bits, bit_samples) # shape (n_bits, bit_samples)
    means = windows.mean(axis=1, dtype=np.float64) # mean per bit
    bits = (means > some_threshold).astype(int).tolist() # thresholding to bits
    
    return bits

# ...existing code...

''' # chatgpt original
def extract_bits(iq, start_idx, bit_samples=BIT_SAMPLES, preamble_samples=PREAMBLE_SAMPLES):
    """
    Extract 112-bit ADS-B message starting from preamble index.
    Returns a list of 112 bits.
    """
    bits = []  # List to hold extracted bits
    for i in range(112): # 112 bits
        idx_start = start_idx + preamble_samples + i * bit_samples # start of bit interval; jumps by 2 indices with each value in i
        idx_end = idx_start + bit_samples # end of bit interval
        if idx_end > len(iq): # prevent overflow
            break
        avg = np.mean(np.real(iq[idx_start:idx_end]))  # average over bit interval
        bits.append(1 if avg > 0 else 0)
    return bits
'''

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
