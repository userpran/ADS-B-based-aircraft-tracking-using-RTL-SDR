import numpy as np
import matplotlib.pyplot as plt

# Parameters
fs = 2_000_000   # Sample rate (2 MHz)

# Load raw I/Q data (unsigned 8-bit interleaved)
with open("iq_samples.bin", "rb") as f:
    raw = np.fromfile(f, dtype=np.uint8)

# Convert to complex baseband: I + jQ (normalize to -1..+1)
I = raw[0::2].astype(np.float32) - 128.0
Q = raw[1::2].astype(np.float32) - 128.0
iq = I + 1j * Q


# Plot real & imaginary parts
plt.figure(0)
plt.plot(iq.real, label="I")
plt.plot(iq.imag, label="Q")
plt.title("Raw IQ Data")
plt.xlabel("Sample Index")
plt.ylabel("Amplitude")
plt.legend()
plt.grid()
plt.show()

