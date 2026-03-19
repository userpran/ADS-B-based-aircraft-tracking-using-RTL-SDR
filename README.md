# ADS-B Aircraft Tracking with RTL-SDR

A comprehensive tool for tracking an antenna to an aircraft using ADS-B signals using an RTL-SDR dongle.

## Features

- **Antenna Tracking**: Real-time calculation of Azimuth and Elevation to point an antenna at a target aircraft.
- **Data Capture**: High-speed IQ sample capture (2 MHz) centered at 1090 MHz using `librtlsdr`.
- **Decoding**: Custom implementation for Mode S preamble detection and message decoding.
- **Integration**: Modular design with `position_provider`, `antenna_controller`, and `decode_module`.
- **Visualization**: Generate plots comparing Latitude, Longitude, and Altitude data.

## Prerequisites

### Platform Support

| Platform | Status | Notes |
|----------|--------|-------|
| Linux |  Fully supported | Primary development platform |
| macOS |  Partial | launcher.sh works, `F_SETPIPE_SZ` not supported (pipe buffer resize skipped), Arduino port name differs (`/dev/tty.usbmodem*`) |
| Windows |  Not supported | launcher.sh requires Bash, FIFO requires Unix named pipes — would need full rewrite to PowerShell + Windows Named Pipes |

> **Note**: All development and testing was done on Ubuntu Linux. The Python decoder, az/el pipeline, and visualisation scripts are platform-independent. Only `launcher.sh` and `rtlsdr_rec_pipeline.cpp` are Linux-specific.

### Hardware
- RTL-SDR Dongle (e.g., RTL-SDR Blog V3/V4)
- Antenna optimized for 1090 MHz (ADS-B frequency)
- Microcontroller(Arduino Uno)
- Motors and motor drivers, one each for elevation and azimuth axis 
- Pan/Tilt Antenna Mount (for tracking)

### Software
- **C++ Compiler**: `g++`, `clang`, or MSVC (for building the capture tool)
- **librtlsdr**: Driver library for RTL-SDR
- **Python 3.x**: Core logic and controller.

```bash
# System
sudo apt install g++ librtlsdr-dev

# Python
pip3 install pymap3d pyserial matplotlib numpy --user
```

## Project Structure

```
ADS-B-based-aircraft-tracking-using-RTL-SDR/
├── captures/                    # Raw IQ captures (.bin) — gitignored
├── cpp/
│   └── rtlsdr_rec_pipeline.cpp  # C++ RTL-SDR IQ capture
├── scripts/
│   └── launcher.sh              # Main entry point
├── rtlsdr_rec_pipeline          # Compiled binary (gitignored)
└── src/
    ├── decode_module/
    │   └── adsb_decoder_pipeline.py   # ADS-B decoder (local CPR)
    ├── azel_module/
    │   └── azel_pipeline.py           # Az/El computation + Arduino serial
    ├── azel_output/                   # Az/El CSV outputs — gitignored
    ├── output/                        # Decoded CSV outputs — gitignored
    └── visualisation/
        ├── azel_live_plot.py          # Live az/el sky view plot
        ├── visualise_decoder_comparison.py  # Decoder vs pyModeS comparison
        └── plot_ADSB_data.py          # IQ signal visualizer

```
## Installation

1. **Clone the repository**:
   ```bash
   git clone <repo_url>
   cd ADS-B-based-aircraft-tracking-using-RTL-SDR
   ```

2. **Compile the Recorder**:
   Ensure you have the `librtlsdr` headers and library available.
   
   **Linux/WSL/MinGW:**
   ```bash
   g++ rtlsdr_rec_2.cpp -o capture -lrtlsdr
   ```

   **Windows (MSVC):**
   Link against `rtlsdr.lib` and ensure `rtlsdr.dll` is in your path.

## Usage

### Live Tracking

> **Linux only** — launcher.sh requires Bash and Unix FIFOs.
> On macOS minor changes needed. Windows not supported without rewrite.

1. Connect RTL-SDR dongle and antenna
2. Connect Arduino via USB
3. Run from project root:

```bash
./scripts/launcher.sh .csv
```

4. Optionally open live plot in a second terminal:

```bash
python3 src/visualisation/azel_live_plot.py
```

5. Press **Ctrl+C** to stop

### Decode an Existing Capture

```bash
python3 -m src.decode_module.adsb_decoder_pipeline \
    --file captures/iq_samples_XXXXXXXX.bin .csv
```

### Standalone Motor Test (no RTL-SDR needed)

```bash
python3 src/azel_module/azel_pipeline.py
```

Injects test positions every 3 seconds and drives motors via serial.

## Configuration

### Ground Station Coordinates
Edit in `src/decode_module/adsb_decoder_pipeline.py`:
```python
RECEIVER_LAT = 8.5241   # your latitude
RECEIVER_LON = 76.9366  # your longitude
```

Edit in `src/azel_module/azel_pipeline.py`:
```python
gs_lat = 8.5000
gs_lon = 76.9000
```

### Capture Duration
Edit in `cpp/rtlsdr_rec_pipeline.cpp`:
```cpp
#define CAPTURE_DURATION_SEC  10   // seconds
```

### Arduino Serial Port
Edit in `src/azel_module/azel_pipeline.py`:
```python
ARDUINO_PORT = '/dev/ttyUSB0'   # Linux
# ARDUINO_PORT = 'COM3'         # Windows
# ARDUINO_PORT = '/dev/tty.usbmodem14201'  # macOS
```

## Arduino

Upload `antenna_tracker.ino` to Arduino Uno before running.


## Visualisation

| Script | Usage |
|--------|-------|
| `azel_live_plot.py` | Live sky view, altitude and range plots — run alongside launcher |
| `plot_ADSB_data.py` | IQ signal, preamble, and spectrum plots from .bin file |
| `visualise_decoder_comparison.py` | Compare decoder CSV vs pyModeS global CPR |

