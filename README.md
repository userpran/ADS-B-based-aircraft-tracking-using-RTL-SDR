# ADS-B Aircraft Tracking with RTL-SDR

A comprehensive tool for tracking an antenna to an aircraft using ADS-B signals using an RTL-SDR dongle.

## Features

- **Antenna Tracking**: Real-time calculation of Azimuth and Elevation to point an antenna at a target aircraft.
- **Data Capture**: High-speed IQ sample capture (2 MHz) centered at 1090 MHz using `librtlsdr`.
- **Decoding**: Custom implementation for Mode S preamble detection and message decoding.
- **Integration**: Modular design with `position_provider`, `antenna_controller`, and `decode_module`.
- **Visualization**: Generate plots for aircraft position, altitude, azimuth, elevation, and range.

## Prerequisites

### Platform Support

| Platform | Support         |
| -------- | --------------- |
| Linux    | Fully supported |
| macOS    | Partial support |
| Windows  | Not supported   |

> **Note**: All development and testing was done on Ubuntu Linux. The decoder, az/el pipeline, and visualisation scripts are platform-independent. Only `launcher.sh` and `rtlsdr_rec_pipeline.cpp` are Linux-specific.

### Hardware
- RTL-SDR Dongle (e.g., RTL-SDR Blog V3/V4)
- Antenna optimized for 1090 MHz (ADS-B frequency)
- Microcontroller (Arduino Uno)
- Motors and motor drivers for azimuth and elevation control
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
├── scripts/
│   └── launcher.sh              # Script to start the full live pipeline 
└── src/
    ├── capture_module/
    │   └── rtlsdr_rec_pipeline.cpp # C++ RTL-SDR IQ capture
    ├── decoder_module/
    │   └── adsb_decoder_pipeline.py   # ADS-B decoder
    ├── azel_module/
    │   └── azel_pipeline.py           # Az/El computation + Arduino serial
    └── visualisation/
        ├── azel_live_plot.py                # Live azimuth/elevation sky view with altitude and range plots
        ├── visualise_decoder_comparison.py  # Decoder csv vs pyModeS comparison
        └── plot_ADSB_data.py                # IQ signal visualizer
├── arduino/
│   └── antenna_tracker.ino              # Code for arduino
```
## Installation

1. **Clone the repository**

2. **Compile the Recorder**:
   Ensure you have the `librtlsdr` headers and library available.
   
   **Linux/WSL/MinGW:**
   ```bash
   g++ rtlsdr_rec_pipeline.cpp -o rtlsdr_rec_pipeline -lrtlsdr
   ```

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
RECEIVER_LAT = 8.5000   # your latitude
RECEIVER_LON = 76.9000  # your longitude
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
ARDUINO_PORT = '/dev/ttyUSB0'              # Linux
```

## Arduino

Upload `antenna_tracker.ino` to Arduino Uno before running.



