#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  ZenVPS — Start Script
#  Built by ZenDevelopment · www.zendevelopment.in
# ══════════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Check Python ─────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "❌ python3 not found. Install Python 3.10+"
    exit 1
fi

# ── Create virtual environment if missing ────────────────────
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment…"
    python3 -m venv venv
fi

# ── Activate & install deps ──────────────────────────────────
echo "🔧 Activating venv and installing dependencies…"
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# ── Check config ─────────────────────────────────────────────
if grep -q "YOUR_BOT_TOKEN_HERE" config.py; then
    echo "⚠️  WARNING: BOT_TOKEN is not set in config.py!"
    echo "   Edit config.py before running the bot."
    exit 1
fi

# ── Stop any existing instance ───────────────────────────────
if [ -f "zenvps.pid" ]; then
    OLD_PID=$(cat zenvps.pid)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "🛑 Stopping existing instance (PID $OLD_PID)…"
        kill "$OLD_PID"
        sleep 2
    fi
    rm -f zenvps.pid
fi

# ── Launch ───────────────────────────────────────────────────
echo "🚀 Starting ZenVPS Bot…"
nohup python3 bot.py >> zenvps.log 2>&1 &
echo $! > zenvps.pid
sleep 2

if kill -0 "$(cat zenvps.pid)" 2>/dev/null; then
    PID=$(cat zenvps.pid)
    echo "✅ ZenVPS is running! (PID: $PID)"
    echo "   Bot Log:   $SCRIPT_DIR/zenvps.log"
    echo "   PID File:  $SCRIPT_DIR/zenvps.pid"
    if grep -q "DASHBOARD_ENABLED = True" config.py; then
        PORT=$(grep "DASHBOARD_PORT" config.py | head -1 | grep -oP '\d+')
        echo "   Dashboard: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT:-8080}"
    fi
    echo ""
    echo "   To stop:  bash stop.sh"
    echo "   To view:  tail -f zenvps.log"
else
    echo "❌ Failed to start. Check zenvps.log for errors."
    rm -f zenvps.pid
    exit 1
fi
