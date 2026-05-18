#!/usr/bin/env python3
"""
Compares your ADS-B decoder's CSV output against pyModeS global CPR decoded from the same .bin IQ file.

  Blue: your custom decoder (local CPR) — from CSV
  Red:  pyModeS global CPR — decoded fresh from .bin

Note: if capture has only even or only odd CPR frames, pyModeS will
show 0 valid positions - it needs both. This is expected for short duration captures. 
(Hence why local cpr decoder is useful)

Usage:
    python3 src/visualisation/visualise_decoder_comparison.py
"""

import os
import sys
import csv
from datetime import datetime
import matplotlib.pyplot as plt
import numpy as np

# ── Project root ──────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
# ── pyModeS ───────────────────────────────────────────────────────────────────
try:
    import pyModeS as pms
except ImportError:
    print("ERROR: pyModeS not installed.")
    print("Install with: pip3 install pyModeS --user")
    sys.exit(1)

# ── Config — edit these for each new capture ──────────────────────────────────
DECODER_CSV = os.path.join(PROJECT_ROOT, "decoder_output",
                           "20260305", "output1957.csv")

BIN_FILE    = os.path.join(PROJECT_ROOT, "captures",
                           "iq_samples_20260305_195744_072.bin")

# ── Load custom decoder CSV ───────────────────────────────────────────────────
def load_csv(filepath):
    positions = []
    try:
        with open(filepath, "r") as f:
            for idx, row in enumerate(csv.DictReader(f)):
                try:
                    positions.append({
                        "index": idx,
                        "icao":  row["icao"],
                        "lat":   float(row["lat"]),
                        "lon":   float(row["lon"]),
                        "alt":   int(float(row["alt"])),
                    })
                except (ValueError, KeyError):
                    continue
    except FileNotFoundError:
        print(f"  WARNING: CSV not found: {filepath}")
    print(f"  Custom decoder CSV: {len(positions)} entries")
    return positions

# ── IQ file → raw hex frames ──────────────────────────────────────────────────
def load_iq_frames(bin_path):
    print(f"  Loading: {os.path.basename(bin_path)}")
    raw = np.fromfile(bin_path, dtype=np.uint8)
    if len(raw) < 2:
        print("  ERROR: empty file")
        return []

    I = raw[0::2].astype(np.float32) - 127.5
    Q = raw[1::2].astype(np.float32) - 127.5
    mag = np.abs(I) + np.abs(Q)

    threshold = np.mean(mag) * 5
    FRAME_LEN = 240

    frames = []
    i = 0
    n = len(mag) - FRAME_LEN
    while i < n:
        if (mag[i]   > threshold and
            mag[i+2] > threshold and
            mag[i+7] > threshold and
            mag[i+9] > threshold):
            bits = []
            data_start = i + 16
            ok = True
            for j in range(112):
                offset = data_start + j * 2
                if offset + 1 >= len(mag):
                    ok = False
                    break
                bits.append(1 if mag[offset] > mag[offset+1] else 0)
            if ok:
                hex_msg = "".join(
                    f"{(bits[k]<<3)|(bits[k+1]<<2)|(bits[k+2]<<1)|bits[k+3]:X}"
                    for k in range(0, 112, 4)
                )
                frames.append(hex_msg)
            i += FRAME_LEN
        else:
            i += 1

    print(f"  Detected {len(frames)} raw frames from IQ file")
    return frames

# ── Decode with pyModeS (global CPR) ─────────────────────────────────────────
def decode_pymodes(frames):
    aircraft  = {}
    positions = []
    for idx, hex_msg in enumerate(frames):
        try:
            if pms.df(hex_msg) != 17: continue
            icao = pms.adsb.icao(hex_msg)
            tc   = pms.adsb.typecode(hex_msg)
            if not (9 <= tc <= 18): continue
            alt = pms.adsb.altitude(hex_msg)
            if alt is None: continue

            if icao not in aircraft:
                aircraft[icao] = {"even": None, "odd": None}
            if pms.adsb.oe_flag(hex_msg) == 0:
                aircraft[icao]["even"] = hex_msg
            else:
                aircraft[icao]["odd"]  = hex_msg

            lat = lon = 0.0
            if aircraft[icao]["even"] and aircraft[icao]["odd"]:
                pos = pms.adsb.position(
                    aircraft[icao]["even"], aircraft[icao]["odd"], 0, 1)
                if pos:
                    lat, lon = round(pos[0], 5), round(pos[1], 5)

            positions.append({
                "index": idx,
                "icao":  "0x" + icao.lower(),
                "lat":   lat, "lon": lon, "alt": alt
            })
        except Exception:
            continue

    valid = sum(1 for p in positions if p["lat"] != 0.0)
    print(f"  pyModeS: {len(positions)} messages, with {valid} valid position")
    if valid == 0:
        print("  (0 valid positions expected if capture has only even "
              "or only odd CPR frames)")
    return positions

# ── Plots ─────────────────────────────────────────────────────────────────────
def make_plots(csv_data, pymodes_data):
    csv_v = [p for p in csv_data     if p["lat"] != 0.0 and p["lon"] != 0.0]
    py_v  = [p for p in pymodes_data if p["lat"] != 0.0 and p["lon"] != 0.0]

    print(f"\n  Valid positions — CSV: {len(csv_v)}  |  pyModeS: {len(py_v)}")

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle(
        "ADS-B Decoder Comparison\n"
        "● Blue: Custom decoder (local CPR) from CSV   "
        "● Red: pyModeS (global CPR) from .bin",
        fontsize=12, fontweight="bold"
    )

    def plot_pair(ax, y_key, title, ylabel):
        if csv_v:
            ax.plot([p["index"] for p in csv_v],
                    [p[y_key]  for p in csv_v],
                    "b-o", label="Custom decoder", markersize=4, linewidth=1.5)
        if py_v:
            ax.plot([p["index"] for p in py_v],
                    [p[y_key]  for p in py_v],
                    "r--s", label="pyModeS", markersize=4,
                    linewidth=1.5, alpha=0.7)
        if y_key == "alt":
            for p in csv_v:
                ax.annotate(str(p["alt"]), (p["index"], p["alt"]),
                            textcoords="offset points", xytext=(0, 5),
                            fontsize=6, color="blue", ha="center")
            for p in py_v:
                ax.annotate(str(p["alt"]), (p["index"], p["alt"]),
                            textcoords="offset points", xytext=(0, -10),
                            fontsize=6, color="red", ha="center")
        ax.set_title(title)
        ax.set_xlabel("Message Index")
        ax.set_ylabel(ylabel)
        ax.legend(fontsize=7)
        ax.grid(alpha=0.3)
        y_min, y_max = ax.get_ylim()
        min_range = 0.1 if y_key in ("lat", "lon") else 100
        if y_max - y_min < min_range:
            mid = (y_min + y_max) / 2
            ax.set_ylim(mid - min_range/2, mid + min_range/2)

    plot_pair(axes[0, 0], "lat", "Latitude",  "Latitude (°)")
    plot_pair(axes[0, 1], "lon", "Longitude", "Longitude (°)")
    plot_pair(axes[1, 0], "alt", "Altitude",  "Altitude (ft)")

    ax4 = axes[1, 1]
    if csv_v:
        ax4.plot([p["lon"] for p in csv_v], [p["lat"] for p in csv_v],
                 "b-o", label="Custom decoder", markersize=6, linewidth=1.5)
        for p in csv_v:
            ax4.annotate(f'#{p["index"]}', (p["lon"], p["lat"]),
                         textcoords="offset points", xytext=(5, 5),
                         fontsize=6, color="blue")
    if py_v:
        ax4.plot([p["lon"] for p in py_v], [p["lat"] for p in py_v],
                 "r--s", label="pyModeS", markersize=6,
                 linewidth=1.5, alpha=0.7)
        for p in py_v:
            ax4.annotate(f'#{p["index"]}', (p["lon"], p["lat"]),
                         textcoords="offset points", xytext=(5, -10),
                         fontsize=6, color="red")
    ax4.set_title("2D Position Track")
    ax4.set_xlabel("Longitude (°)")
    ax4.set_ylabel("Latitude (°)")
    ax4.legend(fontsize=7)
    ax4.grid(alpha=0.3)
    ax4.axis("equal")

    plt.tight_layout()
    plt.show()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("ADS-B Decoder Comparison")
    print("=" * 65)
    print(f"  BIN : {BIN_FILE}")
    print(f"  CSV : {DECODER_CSV}")

    missing = []
    if not os.path.exists(BIN_FILE):
        missing.append(f"BIN_FILE:    {BIN_FILE}")
    if not os.path.exists(DECODER_CSV):
        missing.append(f"DECODER_CSV: {DECODER_CSV}")
    if missing:
        print("\nERROR — files not found, edit paths at top of script:")
        for m in missing: print(f"  {m}")
        sys.exit(1)

    print("\nLoading custom decoder CSV...")
    csv_data = load_csv(DECODER_CSV)

    print("\nDecoding IQ file...")
    frames = load_iq_frames(BIN_FILE)

    print("\nDecoding with pyModeS (global CPR)...")
    pymodes_data = decode_pymodes(frames)

    print("\nGenerating plots...")
    make_plots(csv_data, pymodes_data)

    print("\nDone.")

if __name__ == "__main__":
    main()