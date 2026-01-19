# ADS-B Aircraft Tracking with RTL-SDR

A comprehensive tool for tracking an antenna to an aircraft using ADS-B signals using an RTL-SDR dongle.

## Features

- **Antenna Tracking**: Real-time calculation of Azimuth and Elevation to point an antenna at a target aircraft.
- **Data Capture**: High-speed IQ sample capture (2 MHz) centered at 1090 MHz using `librtlsdr`.
- **Decoding**: Custom implementation for Mode S preamble detection and message decoding.
- **Integration**: Modular design with `position_provider`, `antenna_controller`, and `decode_module`.
- **Visualization**: Generate plots comparing Latitude, Longitude, and Altitude data.

## Prerequisites

### Hardware
- RTL-SDR Dongle (e.g., RTL-SDR Blog V3/V4)
- Antenna optimized for 1090 MHz (ADS-B frequency)
- Pan/Tilt Antenna Mount (for tracking)

### Software
- **C++ Compiler**: `g++`, `clang`, or MSVC (for building the capture tool)
- **librtlsdr**: Driver library for RTL-SDR
- **Python 3.x**: Core logic and controller.

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

### 1. Capture & Track
The system is designed to capture ADS-B signals and drive the antenna tracking mechanism.

```bash
python main.py
```

### 2. Decode Signals (Standalone)
To decode captured binary files manually:
```bash
python adsb_decode_2.py
```
This produces `decoded_summary_2.csv` containing detected aircraft info.

### 3. Verification & Visualization
Use the tools in `src/decode_module/` to analyze decoder performance:
- `adsb_decoder.py`: Alternative decoder implementation.
- `visualize_comparison.py`: Compare decoder outputs.

## Project Structure

- **Core Components**:
  - `main.py`: Main application entry point.
  - `src/antenna_controller.py`: Controls the antenna position (Azimuth/Elevation).
  - `src/position_provider.py`: Supplies target aircraft coordinates.

- **Capture & Decode**:
  - `rtlsdr_rec_2.cpp`: C++ IQ data recorder.
  - `adsb_decode_2.py`: Offline decoder script.
  - `src/decode_module/`: 
    - `adsb_decoder.py`: Modular decoder functionality.
    - `verify_frames.py`: Frame integrity check.
    - `visualize_comparison.py`: Performance visualization.
