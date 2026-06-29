#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  ZenVPS — Stop Script
#  Built by ZenDevelopment · www.zendevelopment.in
# ══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "zenvps.pid" ]; then
    PID=$(cat zenvps.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo "🛑 Stopping ZenVPS (PID: $PID)…"
        kill "$PID"
        sleep 2
        # Force kill if still running
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID" 2>/dev/null
        fi
        echo "✅ Stopped."
    else
        echo "⚠️  Process $PID not running."
    fi
    rm -f zenvps.pid
else
    echo "⚠️  No PID file found. Try: pkill -f 'python3 bot.py'"
fi
