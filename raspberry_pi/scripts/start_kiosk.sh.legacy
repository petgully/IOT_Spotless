#!/bin/bash
# =============================================================================
# Petgully Spotless - Kiosk Startup Script
# =============================================================================
# This script starts the kiosk in full-screen mode
#
# Usage:
#   ./start_kiosk.sh
#
# Auto-start:
#   Add to /etc/xdg/lxsession/LXDE-pi/autostart:
#   @bash /home/spotless/Project_Spotless/raspberry_pi/scripts/start_kiosk.sh
# =============================================================================

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
KIOSK_URL="http://localhost:5000"
LOG_FILE="$HOME/.spotless/logs/kiosk.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting Petgully Spotless Kiosk..."
log "Project directory: $PROJECT_DIR"

# Wait for network (optional)
sleep 5

# Disable screen blanking and power management
log "Disabling screen blanking..."
xset s off
xset s noblank
xset -dpms

# Hide mouse cursor after inactivity
if command -v unclutter &> /dev/null; then
    log "Starting unclutter (hide mouse cursor)..."
    unclutter -idle 0.5 -root &
fi

# Start the Flask server in the background
log "Starting Flask server..."
cd "$PROJECT_DIR"

# Activate virtual environment if it exists
if [ -f "$PROJECT_DIR/venv/bin/activate" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

# Start the main application with kiosk mode
log "Starting main.py with --kiosk flag..."
python3 "$PROJECT_DIR/main.py" --kiosk >> "$LOG_FILE" 2>&1 &

FLASK_PID=$!
log "Main application started with PID: $FLASK_PID"

# Wait for server to be ready
log "Waiting for server to be ready..."
sleep 5

# Check if server is running
if ! curl -s "$KIOSK_URL" > /dev/null; then
    log "WARNING: Server not responding, waiting more..."
    sleep 10
fi

# Start Chromium in kiosk mode
log "Starting Chromium browser in kiosk mode..."
chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --disable-translate \
    --disable-features=TranslateUI \
    --disable-sync \
    --no-first-run \
    --fast \
    --fast-start \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --check-for-update-interval=604800 \
    --disable-component-update \
    "$KIOSK_URL" >> "$LOG_FILE" 2>&1 &

BROWSER_PID=$!
log "Chromium started with PID: $BROWSER_PID"

# Wait for browser to exit
wait $BROWSER_PID

log "Browser exited, cleaning up..."

# Cleanup
kill $FLASK_PID 2>/dev/null

log "Kiosk shutdown complete."
