"""
Live Az/El Plotter
Reads the CSV being actively written by azel_pipeline.py and plots
azimuth/elevation/range in real time using matplotlib animation.

Usage (from project root):
    python3 src/visualisation/azel_live_plot.py

    # Or point at a specific CSV:
    python3 src/visualisation/azel_live_plot.py azel_output/azel_0227_1430.csv

The script auto-finds the most recently modified azel_*.csv in the
azel_output folder if no path is given.
"""

import sys
import os
import csv
import glob
import time
from collections import defaultdict

import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.gridspec as gridspec
from matplotlib.lines import Line2D
import numpy as np

# ── Config ────────────────────────────────────────────────────────────────────
AZEL_MODULE_DIR = os.path.join(os.path.dirname(__file__),
                                "..", "..", "azel_output")
REFRESH_MS       = 500       # plot refresh interval in milliseconds
MAX_TRAIL_POINTS = 200       # max history points shown per aircraft on polar
ICAO_COLORS = plt.colormaps["tab10"]

# ── Find CSV ──────────────────────────────────────────────────────────────────
def find_latest_csv(directory):
    """Returns the most recently modified azel_*.csv in directory."""
    pattern = os.path.join(directory, "azel_*.csv")
    files   = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)

def resolve_csv_path():
    if len(sys.argv) >= 2:
        path = sys.argv[1]
        if not os.path.isfile(path):
            print(f"[Plotter] ERROR: File not found: {path}")
            sys.exit(1)
        return path
    # Auto-find latest
    path = find_latest_csv(AZEL_MODULE_DIR)
    if path is None:
        print(f"[Plotter] No azel_*.csv found in {AZEL_MODULE_DIR}")
        print(f"[Plotter] Make sure the azel pipeline is running first.")
        sys.exit(1)
    print(f"[Plotter] Auto-selected: {path}")
    return path

# ── CSV reader ────────────────────────────────────────────────────────────────
def read_csv(path):
    """
    Reads all rows from the CSV (including rows written since last read).
    Returns list of dicts with keys: time, icao, lat, lon, alt_ft,
                                     az_deg, el_deg, range_m
    """
    rows = []
    try:
        with open(path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    rows.append({
                        "time":    row["time"],
                        "icao":    row["icao"],
                        "lat":     float(row["lat"]),
                        "lon":     float(row["lon"]),
                        "alt_ft":  float(row["alt_ft"]),
                        "az_deg":  float(row["az_deg"]),
                        "el_deg":  float(row["el_deg"]),
                        "range_m": float(row["range_m"]),
                    })
                except (ValueError, KeyError):
                    continue   # skip malformed rows
    except FileNotFoundError:
        pass
    return rows

# ── Per-aircraft data store ───────────────────────────────────────────────────
# icao → list of (az_deg, el_deg, alt_ft, range_km, time)
aircraft_history = defaultdict(list)
icao_color_map   = {}
color_index      = [0]

def get_color(icao):
    if icao not in icao_color_map:
        icao_color_map[icao] = ICAO_COLORS(color_index[0] % 10)
        color_index[0] += 1
    return icao_color_map[icao]

# ── Figure setup ──────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(14, 8), facecolor="#0d1117")
fig.suptitle("Live ADS-B Az/El Tracker", fontsize=14,
             color="#e6edf3", fontfamily="monospace", y=0.98)

gs = gridspec.GridSpec(2, 2, figure=fig,
                       left=0.06, right=0.97,
                       top=0.93, bottom=0.08,
                       hspace=0.38, wspace=0.32)

# ── Polar sky plot (Az/El) ────────────────────────────────────────────────────
ax_polar = fig.add_subplot(gs[:, 0], projection="polar")
ax_polar.set_facecolor("#0d1117")
ax_polar.set_theta_zero_location("N")    # North at top
ax_polar.set_theta_direction(-1)         # clockwise (compass convention)
ax_polar.set_ylim(0, 90)                 # 0=zenith centre, 90=horizon edge
ax_polar.set_yticks([0, 30, 60, 90])
ax_polar.set_yticklabels(["90°", "60°", "30°", "0°"],
                          color="#8b949e", fontsize=7)
ax_polar.set_rlabel_position(45)
ax_polar.tick_params(colors="#8b949e", labelsize=7)
ax_polar.set_title("Sky View  (Az/El)", color="#e6edf3",
                   fontsize=9, pad=10, fontfamily="monospace")
for spine in ax_polar.spines.values():
    spine.set_edgecolor("#30363d")
ax_polar.grid(color="#21262d", linewidth=0.6)

# ── Altitude vs time ──────────────────────────────────────────────────────────
ax_alt = fig.add_subplot(gs[0, 1])
ax_alt.set_facecolor("#0d1117")
ax_alt.set_title("Altitude (ft)", color="#e6edf3",
                  fontsize=9, fontfamily="monospace")
ax_alt.tick_params(colors="#8b949e", labelsize=7)
ax_alt.set_xlabel("Sample #", color="#8b949e", fontsize=7)
ax_alt.set_ylabel("ft", color="#8b949e", fontsize=7)
for spine in ax_alt.spines.values():
    spine.set_edgecolor("#30363d")
ax_alt.grid(color="#21262d", linewidth=0.5)

# ── Range vs time ─────────────────────────────────────────────────────────────
ax_range = fig.add_subplot(gs[1, 1])
ax_range.set_facecolor("#0d1117")
ax_range.set_title("Range (km)", color="#e6edf3",
                    fontsize=9, fontfamily="monospace")
ax_range.tick_params(colors="#8b949e", labelsize=7)
ax_range.set_xlabel("Sample #", color="#8b949e", fontsize=7)
ax_range.set_ylabel("km", color="#8b949e", fontsize=7)
for spine in ax_range.spines.values():
    spine.set_edgecolor("#30363d")
ax_range.grid(color="#21262d", linewidth=0.5)

# Status text at bottom
status_text = fig.text(0.5, 0.01, "Waiting for data...",
                        ha="center", va="bottom",
                        color="#8b949e", fontsize=8,
                        fontfamily="monospace")

# ── Animation update ──────────────────────────────────────────────────────────
csv_path    = resolve_csv_path()
last_count  = [0]   # track how many rows we've seen

def update(frame):
    rows = read_csv(csv_path)

    if len(rows) == last_count[0]:
        return   # no new data — nothing to redraw

    last_count[0] = len(rows)

    # Only process rows we haven't seen yet
    new_rows = rows[last_count[0]:]   # slice from last known count
    last_count[0] = len(rows)

    for row in new_rows:              
      icao = row["icao"]
      aircraft_history[icao].append((
            np.radians(row["az_deg"]),    # polar needs radians
            90 - row["el_deg"],           # invert: 0=zenith, 90=horizon
            row["alt_ft"],
            row["range_m"] / 1000.0,
            row["time"],
        ))

    # ── Redraw polar ──────────────────────────────────────────────────────────
    ax_polar.cla()
    ax_polar.set_theta_zero_location("N")
    ax_polar.set_theta_direction(-1)
    ax_polar.set_ylim(0, 90)
    ax_polar.set_yticks([0, 30, 60, 90])
    ax_polar.set_yticklabels(["90°", "60°", "30°", "0°"],
                              color="#8b949e", fontsize=7)
    ax_polar.set_rlabel_position(45)
    ax_polar.tick_params(colors="#8b949e", labelsize=7)
    ax_polar.set_facecolor("#0d1117")
    ax_polar.set_title("Sky View  (Az/El)", color="#e6edf3",
                       fontsize=9, pad=10, fontfamily="monospace")
    ax_polar.grid(color="#21262d", linewidth=0.6)

    legend_handles = []
    for icao, history in aircraft_history.items():
        trail  = history[-MAX_TRAIL_POINTS:]
        azs    = [p[0] for p in trail]
        els    = [p[1] for p in trail]
        color  = get_color(icao)

        # Trail (faded)
        ax_polar.plot(azs, els, "-", color=color, alpha=0.3, linewidth=1)
        # Current position (bright dot)
        ax_polar.plot(azs[-1], els[-1], "o", color=color,
                      markersize=7, markeredgecolor="white",
                      markeredgewidth=0.5)
        # Label
        ax_polar.annotate(
            icao,
            (azs[-1], els[-1]),
            textcoords="offset points", xytext=(6, 4),
            color=color, fontsize=6, fontfamily="monospace"
        )
        legend_handles.append(
            Line2D([0], [0], marker="o", color="w",
                   markerfacecolor=color, markersize=6,
                   label=icao)
        )

    if legend_handles:
        ax_polar.legend(handles=legend_handles,
                        loc="upper right", fontsize=6,
                        facecolor="#161b22", edgecolor="#30363d",
                        labelcolor="#e6edf3",
                        bbox_to_anchor=(1.25, 1.1))

    # ── Redraw altitude ───────────────────────────────────────────────────────
    ax_alt.cla()
    ax_alt.set_facecolor("#0d1117")
    ax_alt.set_title("Altitude (ft)", color="#e6edf3",
                      fontsize=9, fontfamily="monospace")
    ax_alt.tick_params(colors="#8b949e", labelsize=7)
    ax_alt.set_xlabel("Sample #", color="#8b949e", fontsize=7)
    ax_alt.set_ylabel("ft", color="#8b949e", fontsize=7)
    ax_alt.grid(color="#21262d", linewidth=0.5)
    for spine in ax_alt.spines.values():
        spine.set_edgecolor("#30363d")

    for icao, history in aircraft_history.items():
        trail = history[-MAX_TRAIL_POINTS:]
        alts  = [p[2] for p in trail]
        color = get_color(icao)
        ax_alt.plot(alts, "-o", color=color, markersize=2,
                    linewidth=1, label=icao)

    # ── Redraw range ──────────────────────────────────────────────────────────
    ax_range.cla()
    ax_range.set_facecolor("#0d1117")
    ax_range.set_title("Range (km)", color="#e6edf3",
                        fontsize=9, fontfamily="monospace")
    ax_range.tick_params(colors="#8b949e", labelsize=7)
    ax_range.set_xlabel("Sample #", color="#8b949e", fontsize=7)
    ax_range.set_ylabel("km", color="#8b949e", fontsize=7)
    ax_range.grid(color="#21262d", linewidth=0.5)
    for spine in ax_range.spines.values():
        spine.set_edgecolor("#30363d")

    for icao, history in aircraft_history.items():
        trail  = history[-MAX_TRAIL_POINTS:]
        ranges = [p[3] for p in trail]
        color  = get_color(icao)
        ax_range.plot(ranges, "-o", color=color, markersize=2,
                      linewidth=1, label=icao)

    # ── Status bar ────────────────────────────────────────────────────────────
    n_aircraft = len(aircraft_history)
    last_time  = rows[-1]["time"] if rows else "—"
    status_text.set_text(
        f"CSV: {os.path.basename(csv_path)}   |   "
        f"Aircraft tracked: {n_aircraft}   |   "
        f"Last update: {last_time}   |   "
        f"Total messages: {len(rows)}"
    )

# ── Run ───────────────────────────────────────────────────────────────────────
ani = animation.FuncAnimation(
    fig, update,
    interval=REFRESH_MS,
    cache_frame_data=False
)

plt.show()
