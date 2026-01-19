# ADS-B Aircraft Tracking with RTL-SDR

A comprehensive tool for tracking an antenna to an aircraft using ADS-B signals using an RTL-SDR dongle.

## Features

- **Data Capture**: High-speed IQ sample capture (2 MHz) centered at 1090 MHz using `librtlsdr`.
- **Decoding**: Custom implementation for Mode S preamble detection and message decoding.
- **Integration**: Leverages `pyModeS` for robust packet parsing (DF17/ADS-B).
- **Analysis**: Tools to verify decoder accuracy and compare results against reference decoders.
- **Visualization**: Generate plots comparing Latitude, Longitude, and Altitude data.

## Prerequisites

### Hardware
- RTL-SDR Dongle (e.g., RTL-SDR Blog V3/V4)
- Antenna optimized for 1090 MHz (ADS-B frequency)

### Software
- **C++ Compiler**: `g++`, `clang`, or MSVC (for building the capture tool)
- **librtlsdr**: Driver library for RTL-SDR
- **Python 3.x**
- **Python Libraries**:
  - `numpy`
  - `pandas`
  - `matplotlib`
  - `pyModeS`

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

### 1. Capture ADS-B Signal
Run the compiled capture tool to record raw IQ samples.
```bash
./capture
```
*Note: The tool captures 5 seconds of data by default. This creates a file named `iq_samples_YYYYMMDD_HHMMSS_XXX.bin`.*

### 2. Decode Signals
Open `adsb_decode_2.py` and update the `input_file` variable to point to your captured binary file:
```python
# In adsb_decode_2.py
input_file = "iq_samples_20251016_200629_123.bin"  # <--- Update this filename
```
Then run the decoder:
```bash
python adsb_decode_2.py
```
This produces `decoded_summary_2.csv` containing detected aircraft info (ICAO, Call Sign, Lat, Lon, Alt).

### 3. Visualize & Verify
Use the tools in `src/decode_module/` to analyze results.

To verify frames and plot comparisons:
1. Open `src/decode_module/visualize_comparison.py`.
2. Update `FRAME_FILE` and `CSV_FILE` configurations to point to your data.
3. Run the visualization:
   ```bash
   python src/decode_module/visualize_comparison.py
   ```
   Output graphs will be saved to the `graphs_out/` directory.

## Project Structure

- **`rtlsdr_rec_2.cpp`**: Main C++ program for capturing raw IQ data from RTL-SDR.
- **`adsb_decode_2.py`**: Main Python script for detecting and decoding ADS-B messages.
- **`src/decode_module/`**:
    - **`visualize_comparison.py`**: Generates comparison plots (Custom vs pyModeS).
    - **`verify_frames.py`**: Helper script to verify frame integrity.
    - **`adsb_decoder.py`**: Alternative/Legacy decoder implementation.
- **`reference_commands.txt`**: Reference commands for using `dump1090`.