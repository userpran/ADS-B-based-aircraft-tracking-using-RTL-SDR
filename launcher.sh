#!/bin/bash
# launcher.sh
# Runs RTL-SDR capture (C++) and ADS-B decoder (Python) in parallel.
# The az/el pipeline starts automatically inside the decoder.
#
# Usage: ./launcher.sh [.csv|.json]
#   Optional arg: output format for decoded results. Defaults to no file save.
#
# Requirements:
#   - rtlsdr_rec_pipeline compiled and in current directory (or on PATH)
#   - Python decoder at src/decode_module/adsb_decoder_pipeline_2.py
#   - RTL-SDR device connected

set -euo pipefail

FIFO="/tmp/iq_pipe"
CPP_BIN="./rtlsdr_rec_pipeline"
DECODER_MODULE="src.decode_module.adsb_decoder_pipeline_2"
OUTPUT_FMT="${1:-}"          # optional: .csv or .json
#DECODER_READY_FLAG="/tmp/.decoder_ready" #not currently used, but could be a simple file created by decoder when ready to signal the C++ code to start

# ── Cleanup on exit ───────────────────────────────────────────────────────────
PID_CPP=""
PID_DEC=""

cleanup() {
    echo ""
    echo "[launcher] Shutting down..."

    # Kill by stored PIDs
    [ -n "$PID_DEC" ] && kill "$PID_DEC" 2>/dev/null && echo "[launcher] Decoder stopped."
    [ -n "$PID_CPP" ] && kill "$PID_CPP" 2>/dev/null && echo "[launcher] Capture stopped."

    # Belt-and-suspenders: kill by process name in case PID tracking drifted
    pkill -f "rtlsdr_rec_pipeline" 2>/dev/null || true
    pkill -f "adsb_decoder_pipeline_2" 2>/dev/null || true

    echo "[launcher] Done."
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# ── Sanity checks ─────────────────────────────────────────────────────────────

# ── Compile C++ if binary is missing or source is newer ──────────────────────
CPP_SRC="src/rtlsdr_rec_pipeline.cpp"

if [ ! -f "$CPP_BIN" ] || [ "$CPP_SRC" -nt "$CPP_BIN" ]; then
    # -nt = "newer than" — recompiles if source was modified after last build
    if [ ! -f "$CPP_SRC" ]; then
        echo "[launcher] ERROR: Source file $CPP_SRC not found."
        exit 1
    fi
    echo "[launcher] Compiling $CPP_SRC..." #command: g++ -o rtlsdr_rec_pipeline rtlsdr_rec_pipeline.cpp -lrtlsdr
    g++ -O2 -o "$CPP_BIN" "$CPP_SRC" -lrtlsdr 
    if [ $? -ne 0 ]; then
        echo "[launcher] ERROR: Compilation failed."
        exit 1
    fi
    echo "[launcher] Compilation successful."
else
    echo "[launcher] Binary up to date, skipping compilation."
fi

DECODER_PATH="src/decode_module/adsb_decoder_pipeline_2.py"
if [ ! -f "$DECODER_PATH" ]; then
    echo "[launcher] ERROR: Decoder script not found at $DECODER_PATH"
    exit 1
fi

# ── FIFO setup ────────────────────────────────────────────────────────────────
# Remove stale FIFO from a previous crashed run (a regular file with same name
# would silently break everything).
if [ -e "$FIFO" ] && [ ! -p "$FIFO" ]; then
    echo "[launcher] WARNING: $FIFO exists but is not a FIFO — removing."
    rm -f "$FIFO"
fi

if [ ! -p "$FIFO" ]; then
    mkfifo "$FIFO"
    echo "[launcher] FIFO created: $FIFO"
else
    echo "[launcher] FIFO already exists: $FIFO"
fi

# after FIFO creation (requires sudo once) #removed because we set it from C++ with fcntl(F_SETPIPE_SZ) which works without sudo
#sudo sysctl -w fs.pipe-max-size=4194304  # 4MB 
#sudo sysctl -w fs.pipe-user-pages-soft=0

echo "[launcher] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[launcher]  RTL-SDR ADS-B Pipeline"
echo "[launcher] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Step 1: Start the decoder FIRST (it is the FIFO reader) ──────────────────
# The FIFO open() for writing in C++ will BLOCK until a reader opens it.
# So we must start the decoder (reader) before the C++ writer.
# We wrap it in a loop for auto-restart on crash.


# ── Start decoder (reader) ────────────────────────────────────────────────────
(
    while true; do
        echo "[decoder] Starting..."
        if [ -n "$OUTPUT_FMT" ]; then
            python3 -m "$DECODER_MODULE" "$OUTPUT_FMT"
        else
            python3 -m "$DECODER_MODULE"
        fi
        STATUS=$?
        if [ $STATUS -eq 0 ]; then
            echo "[decoder] Exited normally — not restarting."
            break
        else
            echo "[decoder] Crashed (exit $STATUS). Restarting in 2s..."
            sleep 2
        fi
    done
) &
PID_DEC=$!
echo "[launcher] Decoder started (PID $PID_DEC)"

# Give Python time to start up and open the FIFO
sleep 3

# ── Step 2: Wait until decoder has opened the FIFO before starting C++ ───────

echo "[launcher] Waiting for decoder to initialise..."
sleep 3
echo "[launcher] Starting C++ capture..."

# ── Step 3: Start C++ capture (FIFO writer) ───────────────────────────────────
"$CPP_BIN" &
PID_CPP=$!
echo "[launcher] C++ capture started (PID $PID_CPP)"
echo "[launcher] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[launcher] All processes running. Press Ctrl+C to stop."
echo "[launcher] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Step 4: Monitor — exit when C++ capture finishes ─────────────────────────
# The C++ process runs for a fixed duration (CAPTURE_DURATION_SEC = 5s).
# When it exits, the FIFO write-end closes, the decoder sees EOF and exits cleanly.
# We wait on the C++ PID specifically so the script doesn't hang forever.

wait "$PID_CPP"
CPP_EXIT=$?
echo "[launcher] C++ capture finished (exit $CPP_EXIT)."
echo "[launcher] Waiting for decoder to finish processing remaining buffer..."

# Give decoder up to 10 seconds to drain whatever is left in its carry buffer
DRAIN_WAIT=0
while kill -0 "$PID_DEC" 2>/dev/null; do
    sleep 0.5
    DRAIN_WAIT=$((DRAIN_WAIT + 1))
    if [ $DRAIN_WAIT -ge 20 ]; then   # 10 seconds
        echo "[launcher] Decoder did not finish draining — forcing stop."
        break
    fi
done