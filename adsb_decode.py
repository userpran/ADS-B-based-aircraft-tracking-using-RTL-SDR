import numpy as np
from math import floor, cos, acos, pi

# -------------------------
# 1. Read IQ samples
# -------------------------
def read_iq(filename, fs=2_400_000):
    raw = np.fromfile(filename, dtype=np.uint8)
    # Convert to float centered at zero
    # Raw is 0..255; subtract midpoint to make it signed
    raw = raw.astype(np.float32) - 127.5
    I = raw[0::2]
    Q = raw[1::2]
    samples = I + 1j * Q
    return samples, fs

# -------------------------
# 2. Magnitude stream
# -------------------------
def get_magnitude(samples):
    return np.abs(samples)

# -------------------------
# 3. Preamble detection
#    (simplified version)
# -------------------------
def detect_preambles(mag, fs):
    sps = fs / 1_0e6  # samples per microsecond
    # We'll require some window; subtract some margin so we don't run off
    window = int(8 * sps + 10)  # 8 µs preamble + small slack
    positions = []
    N = len(mag)
    for i in range(N - window):
        # Check for energy peaks roughly at 0, 0.5, 1.0, 3.5 µs
        # You might implement a matched filter here; we do crude checks:
        p0 = mag[i]
        p1 = mag[i + int(0.5 * sps)]
        p2 = mag[i + int(1.0 * sps)]
        p3 = mag[i + int(3.5 * sps)]
        # use threshold heuristic
        if p0 > 2 and p1 > 2 and p2 > 2 and p3 > 2:
            # assume message data starts just after the 8 µs preamble
            start = i + int(8 * sps)
            positions.append(start)
    return positions

# -------------------------
# 4. Demodulate bits via PPM
# -------------------------
def demodulate_bits(mag, start, fs):
    sps = fs / 1e6
    bits = []
    for b in range(112):
        pos = int(start + b * sps)
        # split into two halves
        half = int(sps / 2)
        e1 = np.sum(mag[pos : pos + half])
        e2 = np.sum(mag[pos + half : pos + 2 * half])
        bits.append(1 if e1 > e2 else 0)
    return bits

# -------------------------
# 5. Utility: bits → integer
# -------------------------
def bits_to_int(bits, i, length):
    val = 0
    for j in bits[i : i + length]:
        val = (val << 1) | j
    return val

# -------------------------
# 6. Altitude decoding (per mode-s spec)
# -------------------------
def decode_altitude(bits, type_code):
    def decode_altitude(bits, type_code):
    """
    Decode the 12-bit altitude field (bits 41–52 of ME).
    Returns (altitude_value, source_string).
    source_string is 'Barometric' or 'GNSS'.
    """
    alt_bits = bits_to_int(bits, 40, 12)  # 41–52 in spec (1-based)
    q = (alt_bits >> 4) & 1  # Q-bit (8th bit of the 12-bit field)

    top = (alt_bits >> 5) << 4   # bits above Q
    bottom = alt_bits & 0xF      # 4 LSBs
    N = top | bottom             # 11-bit integer (without Q)

    if 9 <= type_code <= 18:
        # Barometric altitude
        if q == 1:
            return N * 25 - 1000, "Barometric"
        else:
            # Q=0 → Gray-code 100 ft steps (rare)
            return None, "Barometric (Gray-code, unsupported)"
    elif 20 <= type_code <= 22:
        # GNSS altitude (in meters)
        return N, "GNSS"
    else:
        return None, "Not an altitude frame"



# -------------------------
# 7. CPR decode global (per mode-s formulas)
# -------------------------
N_Z = 15  # number of latitude zones per hemisphere

def NL(lat):
    # Implementation of NL(lat) per spec
    if lat < 0:
        lat = -lat
    if lat >= 87:
        return 1
    if lat <= 0:
        return 59
    # compute using formula:
    a = 1 - cos(pi / (2 * N_Z))
    b = cos(pi / 180.0 * lat) ** 2
    val = 2 * pi / acos(1 - a / b)
    return int(floor(val))

def cpr_global(lat_even_cpr, lat_odd_cpr, lon_even_cpr, lon_odd_cpr, t_even, t_odd):
    # convert to fractions
    dlat_even = 360.0 / (4 * N_Z)
    dlat_odd  = 360.0 / (4 * N_Z - 1)
    j = floor(59 * lat_even_cpr - 60 * lat_odd_cpr + 0.5)
    lat_even = dlat_even * ( (j % 60) + lat_even_cpr )
    lat_odd  = dlat_odd  * ( (j % 59) + lat_odd_cpr )
    # choose more recent
    lat = lat_even if t_even >= t_odd else lat_odd

    # NL check
    nl = NL(lat)
    if nl == 0:
        return None, None  # cannot decode

    # longitude index m
    # per spec:  
    m = floor( lon_even_cpr * (nl - 1) - lon_odd_cpr * nl + 0.5 )
    # compute zone sizes
    ni_even = nl
    ni_odd  = nl - 1
    dlon_even = 360.0 / ni_even
    dlon_odd  = 360.0 / ni_odd if ni_odd > 0 else 360.0
    lon_even = dlon_even * ( (m % ni_even) + lon_even_cpr )
    lon_odd  = dlon_odd * ( (m % ni_odd) + lon_odd_cpr ) if ni_odd > 0 else lon_even
    lon = lon_even if t_even >= t_odd else lon_odd

    # adjust longitude to −180..+180
    if lon >= 180:
        lon -= 360
    return lat, lon

# -------------------------
# 8. Main loop
# -------------------------
def process_iq(filename):
    samples, fs = read_iq(filename)
    mag = get_magnitude(samples)
    starts = detect_preambles(mag, fs)
    cpr_store = {}  # store per ICAO: { odd/even: (lat_cpr, lon_cpr, time) }

    for s in starts:
        bits = demodulate_bits(mag, s, fs)
        df = bits_to_int(bits, 0, 5)
        if df != 17:
            continue
        type_code = bits_to_int(bits, 32, 5)
        # Altitude decode
        alt, alt_type = decode_altitude(bits, type_code)



        # bit 53 (0-based) is T field, bit 54 is F flag (odd/even) per spec
        t_bit = bits[53]
        f_flag = bits[54]
        lat_bits = bits_to_int(bits, 55, 17)
        lon_bits = bits_to_int(bits, 72, 17)

        # convert to CPR fractions
        lat_cpr = lat_bits / (2**17)
        lon_cpr = lon_bits / (2**17)

        # Here, we skip ICAO tracking, assume one aircraft
        if f_flag not in cpr_store:
            cpr_store[f_flag] = (lat_cpr, lon_cpr, t_bit)
        else:
            # we already have the other frame, try decode
            # pick the pair (even, odd)
            if 0 in cpr_store and 1 in cpr_store:
                 lat, lon = cpr_global(
                         cpr_store[0][0], cpr_store[1][0],
                  cpr_store[0][1], cpr_store[1][1],
                  cpr_store[0][2], cpr_store[1][2]
    )
    print(f"Decoded position: lat={lat:.6f}, lon={lon:.6f}, Altitude={alt} ({alt_type})")



    print("Done.")


