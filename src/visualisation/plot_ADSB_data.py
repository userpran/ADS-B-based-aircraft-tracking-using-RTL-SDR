import numpy as np
import matplotlib.pyplot as plt

# ── Config ────────────────────────────────────────────────────────────────────
BIN_FILE = "captures/iq_samples_20260305_195744_072.bin"
fs = 2_000_000        # 2 MHz sample rate
FRAME_US = 120        # 8µs preamble + 112µs data = 120µs total
FRAME_SAMPLES = FRAME_US * (fs // 1_000_000)   # 240 samples

# ── Load IQ data ──────────────────────────────────────────────────────────────
raw = np.fromfile(BIN_FILE, dtype=np.uint8)
I = raw[0::2].astype(np.float32) - 127.5
Q = raw[1::2].astype(np.float32) - 127.5
iq = I + 1j * Q
magnitude = np.abs(I) + np.abs(Q)

# ── Find first real ADS-B preamble ────────────────────────────────────────────
threshold = np.mean(magnitude) * 5
frame_start = 0
for i in range(len(magnitude) - FRAME_SAMPLES):
    if (magnitude[i]   > threshold and
        magnitude[i+2] > threshold and
        magnitude[i+7] > threshold and
        magnitude[i+9] > threshold):
        frame_start = i
        print(f"Preamble found at sample {i} ({i/fs*1e6:.1f} µs into capture)")
        break
else:
    raise RuntimeError("No preamble found in file — check threshold or file path")

frame = iq[frame_start : frame_start + FRAME_SAMPLES]

# ── Plot 1: IQ time domain of one frame ──────────────────────────────────────
plt.figure(figsize=(12, 4))
t_us = np.arange(len(frame)) * (1e6 / fs)
plt.plot(t_us, frame.real, label="I", linewidth=0.8)
plt.plot(t_us, frame.imag, label="Q", linewidth=0.8)
plt.axvspan(0, 8, alpha=0.1, color='yellow', label="Preamble (8µs)")
plt.axvspan(8, 120, alpha=0.1, color='green', label="Data (112µs)")
plt.title(f"ADS-B Frame IQ — sample {frame_start}")
plt.xlabel("Time (µs)")
plt.ylabel("Amplitude")
plt.legend()
plt.grid()
plt.tight_layout()
plt.show()

# ── Plot 2: Magnitude (easier to read than I/Q separately) ───────────────────
plt.figure(figsize=(12, 4))
mag = np.abs(frame.real) + np.abs(frame.imag)
plt.plot(t_us, mag, color='orange', linewidth=0.8)
plt.axvspan(0, 8, alpha=0.1, color='yellow', label="Preamble")
plt.axvspan(8, 120, alpha=0.1, color='green', label="Data bits")
plt.axhline(y=np.mean(magnitude)*5, color='red', linestyle='--', label="Threshold")
plt.title("ADS-B Frame Magnitude")
plt.xlabel("Time (µs)")
plt.ylabel("|I| + |Q|")
plt.legend()
plt.grid()
plt.tight_layout()
plt.show()

# ── Plot 3: Spectrum (wider window for frequency resolution) ──────────────────
spectrum_len = min(len(iq), 20000)  # first 10ms
fft_vals = np.fft.fftshift(np.fft.fft(iq[:spectrum_len]))
freqs = np.fft.fftshift(np.fft.fftfreq(spectrum_len, 1/fs))
plt.figure(figsize=(12, 4))
plt.plot(freqs/1e6, 20*np.log10(np.abs(fft_vals) + 1e-10), linewidth=0.5)
plt.title("Spectrum (first 10ms of capture)")
plt.xlabel("Frequency relative to 1090 MHz (MHz)")
plt.ylabel("Power (dB)")
plt.grid()
plt.tight_layout()
plt.show()