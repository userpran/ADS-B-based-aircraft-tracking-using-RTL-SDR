import numpy as np
import matplotlib.pyplot as plt

# Parameters
fs = 2_000_000   # Sample rate (2 MHz)
frame_bits = 120
frame_us = frame_bits       # 120 bits → 120 microseconds
samples_per_us = fs // 1_000_000
frame_samples = frame_us * samples_per_us

# Load raw I/Q data (unsigned 8-bit interleaved)
with open("iq_samples.bin", "rb") as f:
    raw = np.fromfile(f, dtype=np.uint8)

# Convert to complex baseband: I + jQ (normalize to -1..+1)
I = raw[0::2].astype(np.float32) - 128.0
Q = raw[1::2].astype(np.float32) - 128.0
iq = I + 1j * Q

# Just grab the first frame worth of samples
frame = iq[:frame_samples]

# Plot real & imaginary parts
plt.figure(figsize=(10,4))
plt.plot(frame.real, label="I")
plt.plot(frame.imag, label="Q")
plt.title("ADS-B Signal (first 120 µs)")
plt.xlabel("Sample Index")
plt.ylabel("Amplitude")
plt.legend()
plt.grid()
plt.show()

# Optional: Spectrum
plt.figure(figsize=(10,4))
fft_vals = np.fft.fftshift(np.fft.fft(frame))
freqs = np.fft.fftshift(np.fft.fftfreq(len(frame), 1/fs))
plt.plot(freqs/1e6, 20*np.log10(np.abs(fft_vals)))
plt.title("ADS-B Spectrum (first frame)")
plt.xlabel("Frequency [MHz]")
plt.ylabel("Power [dB]")
plt.grid()
plt.show()
