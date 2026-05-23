#!/usr/bin/env bash
# =============================================================================
# Project Spotless - One-Command Pi Bootstrap (Phase 1)
# =============================================================================
# Takes a freshly-flashed Raspberry Pi OS Bookworm machine to a fully working
# Spotless kiosk in ~10 minutes. Idempotent: safe to re-run on the same Pi.
#
# Usage (cold start, on a fresh Pi):
#   curl -fsSL https://raw.githubusercontent.com/petgully/IOT_Spotless/main/raspberry_pi/scripts/bootstrap.sh | sudo bash
#
# Usage (from an existing clone):
#   sudo bash raspberry_pi/scripts/bootstrap.sh
#
# Non-interactive (CI / repeat deployments):
#   sudo SPOTLESS_MACHINE_ID=BS01 SPOTLESS_STATIC_IP=192.168.0.20 \
#        SPOTLESS_DB_HOST=... SPOTLESS_DB_USER=... SPOTLESS_DB_PASSWORD=... \
#        SPOTLESS_ADMIN_PASSWORD=... \
#        SPOTLESS_NONINTERACTIVE=1 \
#        bash raspberry_pi/scripts/bootstrap.sh
# =============================================================================

set -euo pipefail

# --- Constants ---
readonly REPO_URL="https://github.com/petgully/IOT_Spotless.git"
readonly REPO_BRANCH="${SPOTLESS_REPO_BRANCH:-main}"
readonly SPOTLESS_USER="spotless"
readonly SPOTLESS_HOME="/home/${SPOTLESS_USER}"
readonly REPO_DIR="${SPOTLESS_HOME}/IOT_Spotless"
readonly PI_DIR="${REPO_DIR}/raspberry_pi"
readonly CONFIG_DIR="${SPOTLESS_HOME}/.spotless"
readonly SERVICE_NAME="spotless-kiosk.service"
readonly KIOSK_PORT=5000

# --- Colors ---
if [[ -t 1 ]]; then
    BOLD=$'\033[1m'; RED=$'\033[0;31m'; GREEN=$'\033[0;32m'
    YELLOW=$'\033[1;33m'; CYAN=$'\033[0;36m'; NC=$'\033[0m'
else
    BOLD=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; NC=""
fi

log()    { echo -e "${CYAN}→${NC} $*"; }
ok()     { echo -e "  ${GREEN}✓${NC} $*"; }
warn()   { echo -e "  ${YELLOW}⚠${NC} $*"; }
err()    { echo -e "  ${RED}✗${NC} $*" >&2; }
header() {
    echo ""
    echo -e "${CYAN}=============================================${NC}"
    echo -e "${BOLD}  $*${NC}"
    echo -e "${CYAN}=============================================${NC}"
}

trap 'err "bootstrap failed at line $LINENO. Check output above."' ERR

# =============================================================================
# 0. Pre-flight checks
# =============================================================================
preflight() {
    header "Pre-flight checks"

    if [[ "$(id -u)" -ne 0 ]]; then
        err "Must run as root. Try: sudo bash $0"
        exit 1
    fi
    ok "Running as root"

    if ! id -u "$SPOTLESS_USER" >/dev/null 2>&1; then
        warn "User '$SPOTLESS_USER' does not exist. Creating it..."
        adduser --disabled-password --gecos "" "$SPOTLESS_USER"
        usermod -aG sudo,gpio,i2c,spi,dialout,video,plugdev,users "$SPOTLESS_USER" 2>/dev/null || true
        echo "${SPOTLESS_USER}:spotless" | chpasswd
        ok "Created user '$SPOTLESS_USER' (default password: spotless — CHANGE IT)"
    else
        ok "User '$SPOTLESS_USER' exists"
    fi

    if ! ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
        err "No internet connectivity. Connect to WiFi first, then re-run."
        exit 1
    fi
    ok "Internet reachable"

    if ! command -v apt-get >/dev/null 2>&1; then
        err "apt-get not found. This script is for Debian/Raspberry Pi OS."
        exit 1
    fi
    ok "Debian-based OS detected"
}

# =============================================================================
# 1. Gather inputs (interactive or via env vars)
# =============================================================================
# Important:
#   - All `read` calls use `</dev/tty` so the script works under
#     `curl ... | sudo bash` (where stdin is the script body, not the keyboard).
#   - `nmcli` detection is intentionally deferred to `configure_static_ip`
#     so this function can run before `network-manager` is apt-installed.
# =============================================================================

# Helper: read a value from the terminal, falling back to a default if no tty.
_read_tty() {
    # _read_tty <prompt> <default> <var_name> [-s for password]
    local prompt="$1" default="$2" __var="$3" silent="${4:-}"
    local input=""
    if [[ ! -e /dev/tty ]] || [[ "${SPOTLESS_NONINTERACTIVE:-0}" == "1" ]]; then
        printf -v "$__var" '%s' "$default"
        return
    fi
    if [[ "$silent" == "-s" ]]; then
        read -r -s -p "$prompt" input </dev/tty || true
        echo ""  # newline after silent input
    else
        read -r -p "$prompt" input </dev/tty || true
    fi
    if [[ -z "$input" ]]; then
        printf -v "$__var" '%s' "$default"
    else
        printf -v "$__var" '%s' "$input"
    fi
}

gather_inputs() {
    header "Configuration"

    # --- Machine ID ---
    MACHINE_ID="${SPOTLESS_MACHINE_ID:-}"
    if [[ -z "$MACHINE_ID" ]] && [[ -f "${CONFIG_DIR}/machine_id.txt" ]]; then
        MACHINE_ID="$(cat "${CONFIG_DIR}/machine_id.txt" 2>/dev/null || true)"
        [[ -n "$MACHINE_ID" ]] && ok "Found existing machine ID: ${BOLD}${MACHINE_ID}${NC}"
    fi
    if [[ -z "$MACHINE_ID" ]]; then
        echo ""
        echo -e "${BOLD}Machine ID${NC} (e.g. BS01 for Booth-Spotless-01)"
        _read_tty "  > " "" MACHINE_ID
        MACHINE_ID="$(echo "$MACHINE_ID" | tr '[:lower:]' '[:upper:]' | tr -d ' ')"
    fi
    if [[ -z "$MACHINE_ID" ]]; then
        err "Machine ID required. Set SPOTLESS_MACHINE_ID or run interactively (with a real terminal)."
        exit 1
    fi
    ok "Machine ID: ${BOLD}${MACHINE_ID}${NC}"

    # --- Network: detect gateway + suggest IP (no nmcli yet) ---
    GATEWAY="$(ip route | awk '/^default/ {print $3; exit}')"
    if [[ -z "$GATEWAY" ]]; then
        err "Could not detect default gateway. Are you connected to a network?"
        exit 1
    fi
    SUBNET="$(echo "$GATEWAY" | awk -F. '{print $1"."$2"."$3}')"
    DEFAULT_IP="${SUBNET}.20"
    CURRENT_IP="$(hostname -I | awk '{print $1}')"
    NET_CONNECTION=""  # detected later, after apt installs network-manager

    log "Detected gateway: ${GATEWAY}"
    log "Detected current IP: ${CURRENT_IP}"

    STATIC_IP="${SPOTLESS_STATIC_IP:-}"
    if [[ -z "$STATIC_IP" ]]; then
        echo ""
        echo -e "${BOLD}Static IP for this Pi${NC} (suggested: ${DEFAULT_IP} for Machine 1, ${SUBNET}.21 for Machine 2)"
        _read_tty "  > [${DEFAULT_IP}] " "$DEFAULT_IP" STATIC_IP
    fi
    ok "Static IP: ${BOLD}${STATIC_IP}${NC}"

    # --- DB credentials ---
    DB_HOST="${SPOTLESS_DB_HOST:-}"
    DB_USER="${SPOTLESS_DB_USER:-}"
    DB_PASSWORD="${SPOTLESS_DB_PASSWORD:-}"
    DB_NAME="${SPOTLESS_DB_NAME:-petgully_db}"

    if [[ -z "$DB_HOST" ]] && [[ "${SPOTLESS_NONINTERACTIVE:-0}" != "1" ]] && [[ -e /dev/tty ]]; then
        echo ""
        echo -e "${BOLD}Database (AWS RDS Aurora MySQL)${NC} — leave blank to skip (offline mode)"
        _read_tty "  DB host (e.g. xxx.cluster-yyy.rds.amazonaws.com): " "" DB_HOST
        if [[ -n "$DB_HOST" ]]; then
            _read_tty "  DB user [spotless001]: " "spotless001" DB_USER
            _read_tty "  DB password: " "" DB_PASSWORD -s
            _read_tty "  DB name [petgully_db]: " "petgully_db" DB_NAME
        fi
    fi
    if [[ -n "$DB_HOST" ]]; then
        ok "Database: ${DB_HOST}"
    else
        warn "No DB configured — kiosk will run in offline mode (sessions logged locally)"
    fi

    # --- Admin password (Phase 3 placeholder) ---
    ADMIN_PASSWORD="${SPOTLESS_ADMIN_PASSWORD:-}"
    if [[ -z "$ADMIN_PASSWORD" ]] && [[ "${SPOTLESS_NONINTERACTIVE:-0}" != "1" ]] && [[ -e /dev/tty ]]; then
        echo ""
        echo -e "${BOLD}Admin UI password${NC} (used later for the operator settings page; min 6 chars; press Enter to use default)"
        local attempts=0
        while [[ ${#ADMIN_PASSWORD} -lt 6 ]] && (( attempts < 3 )); do
            _read_tty "  > " "" ADMIN_PASSWORD -s
            if [[ -z "$ADMIN_PASSWORD" ]]; then
                break  # user pressed Enter to accept default
            fi
            if [[ ${#ADMIN_PASSWORD} -lt 6 ]]; then
                warn "Too short — please use at least 6 characters"
                ADMIN_PASSWORD=""
            fi
            ((attempts++)) || true
        done
    fi
    if [[ -z "$ADMIN_PASSWORD" ]]; then
        ADMIN_PASSWORD="spotless-admin"
        warn "Using default admin password '${ADMIN_PASSWORD}' — CHANGE IT in ${PI_DIR}/.env"
    else
        ok "Admin password set"
    fi

    # --- Confirmation ---
    echo ""
    echo -e "${CYAN}Summary:${NC}"
    echo "  Machine ID:    ${MACHINE_ID}"
    echo "  Static IP:     ${STATIC_IP}/24 (gateway ${GATEWAY})"
    echo "  DB host:       ${DB_HOST:-<offline mode>}"
    echo "  Repo:          ${REPO_URL} (branch: ${REPO_BRANCH})"
    echo "  Install path:  ${REPO_DIR}"
    if [[ "${SPOTLESS_NONINTERACTIVE:-0}" != "1" ]] && [[ -e /dev/tty ]]; then
        echo ""
        local confirm=""
        _read_tty "Proceed? (y/N) " "n" confirm
        # Accept y, Y, yes, YES, etc. — anything starting with "y"
        if [[ ! "${confirm,,}" =~ ^y ]]; then
            warn "Aborted by user."
            exit 0
        fi
    fi
}

# =============================================================================
# 2. APT packages
# =============================================================================
install_apt_packages() {
    header "Installing system packages"

    log "Running apt-get update..."
    apt-get update -qq

    local pkgs=(
        git curl ca-certificates
        mosquitto mosquitto-clients
        python3 python3-pip python3-venv python3-libgpiod
        chromium-browser unclutter
        logrotate cron
        network-manager
    )
    log "Installing: ${pkgs[*]}"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${pkgs[@]}" >/dev/null
    ok "All apt packages installed"
}

# =============================================================================
# 3. Repo clone or pull
# =============================================================================
clone_or_pull_repo() {
    header "Source code"

    # If we're already running from inside a clone, use it
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo '')"
    if [[ -n "$script_dir" ]] && [[ -f "${script_dir}/../main.py" ]]; then
        local detected_repo
        detected_repo="$(cd "${script_dir}/../.." && pwd)"
        if [[ "$detected_repo" != "$REPO_DIR" ]]; then
            warn "Running from existing clone at ${detected_repo}"
            warn "Will copy/sync to canonical location ${REPO_DIR}"
            mkdir -p "$(dirname "$REPO_DIR")"
            if [[ -d "${REPO_DIR}/.git" ]]; then
                run_as_spotless "cd '$REPO_DIR' && git pull --ff-only || true"
            else
                # Copy current checkout into canonical location
                rm -rf "$REPO_DIR"
                cp -a "$detected_repo" "$REPO_DIR"
            fi
        else
            ok "Already at canonical location: ${REPO_DIR}"
            run_as_spotless "cd '$REPO_DIR' && git pull --ff-only 2>/dev/null || true"
        fi
    elif [[ -d "${REPO_DIR}/.git" ]]; then
        ok "Repo already cloned at ${REPO_DIR}"
        log "Pulling latest from origin/${REPO_BRANCH}..."
        run_as_spotless "cd '$REPO_DIR' && git fetch --quiet origin && git checkout --quiet '$REPO_BRANCH' && git pull --ff-only --quiet"
        ok "Repo updated"
    else
        log "Cloning ${REPO_URL} to ${REPO_DIR}..."
        mkdir -p "$(dirname "$REPO_DIR")"
        run_as_spotless "git clone --branch '$REPO_BRANCH' --quiet '$REPO_URL' '$REPO_DIR'"
        ok "Repo cloned"
    fi

    chown -R "${SPOTLESS_USER}:${SPOTLESS_USER}" "$REPO_DIR"
}

# Helper: run a shell command as the spotless user (preserving HOME)
run_as_spotless() {
    sudo -u "$SPOTLESS_USER" -H bash -c "$1"
}

# =============================================================================
# 4. Mosquitto MQTT broker
# =============================================================================
configure_mosquitto() {
    header "Mosquitto MQTT broker"

    local conf="/etc/mosquitto/conf.d/spotless.conf"
    cat > "$conf" <<'EOF'
# Project Spotless MQTT Configuration
listener 1883
allow_anonymous true
EOF
    ok "Wrote ${conf}"

    # Remove any conflicting default conf
    if [[ -f /etc/mosquitto/conf.d/local.conf ]]; then
        mv /etc/mosquitto/conf.d/local.conf /etc/mosquitto/conf.d/local.conf.legacy
        warn "Renamed conflicting /etc/mosquitto/conf.d/local.conf → .legacy"
    fi

    systemctl enable mosquitto >/dev/null 2>&1
    systemctl restart mosquitto
    sleep 1

    if systemctl is-active --quiet mosquitto; then
        ok "Mosquitto running on :1883"
    else
        err "Mosquitto failed to start. Logs: journalctl -u mosquitto -n 30"
        exit 1
    fi

    if mosquitto_pub -h localhost -t "spotless/_bootstrap_test" -m "ping" >/dev/null 2>&1; then
        ok "Mosquitto self-test (publish) passed"
    else
        warn "Mosquitto self-test failed — proceeding anyway"
    fi
}

# =============================================================================
# 5. Static IP via nmcli (runs after install_apt_packages)
# =============================================================================
configure_static_ip() {
    header "Static IP configuration"

    if ! command -v nmcli >/dev/null 2>&1; then
        warn "nmcli not available. Skipping static IP — set it manually:"
        warn "  sudo nmcli connection modify <name> ipv4.addresses ${STATIC_IP}/24 ipv4.gateway ${GATEWAY} ipv4.method manual"
        return
    fi

    NET_CONNECTION="$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null | grep -v lo | head -1 | cut -d: -f1)"
    if [[ -z "$NET_CONNECTION" ]]; then
        warn "Could not auto-detect active connection name. Skipping static IP."
        warn "Set it manually later: sudo nmcli connection modify <name> ipv4.addresses ${STATIC_IP}/24 ipv4.gateway ${GATEWAY} ipv4.method manual"
        return
    fi
    log "Detected active connection: ${NET_CONNECTION}"

    log "Setting ${STATIC_IP}/24 on connection '${NET_CONNECTION}'..."
    nmcli connection modify "$NET_CONNECTION" \
        ipv4.addresses "${STATIC_IP}/24" \
        ipv4.gateway "${GATEWAY}" \
        ipv4.dns "8.8.8.8,1.1.1.1" \
        ipv4.method manual

    # Apply without dropping current SSH session if possible
    nmcli connection up "$NET_CONNECTION" >/dev/null 2>&1 || warn "Connection bounce may have hiccupped — IP will apply on next reboot"

    sleep 2
    local new_ip
    new_ip="$(hostname -I | awk '{print $1}')"
    if [[ "$new_ip" == "$STATIC_IP" ]]; then
        ok "Static IP applied: ${STATIC_IP}"
    else
        warn "Current IP is ${new_ip} (expected ${STATIC_IP}). Will take effect after reboot."
    fi
}

# =============================================================================
# 6. Spotless config dirs (run as spotless user)
# =============================================================================
setup_spotless_dirs() {
    header "Spotless config directory"

    run_as_spotless "mkdir -p '${CONFIG_DIR}/logs' '${CONFIG_DIR}/sessions'"
    ok "Created ${CONFIG_DIR}/{logs,sessions}"

    # Write machine ID
    run_as_spotless "echo '${MACHINE_ID}' > '${CONFIG_DIR}/machine_id.txt'"
    ok "Wrote machine ID to ${CONFIG_DIR}/machine_id.txt"
}

# =============================================================================
# 7. .env file
# =============================================================================
# Built with `printf %s` so DB/admin passwords containing $, backticks, #,
# spaces, or other shell metacharacters are written literally, not expanded.
# python-dotenv parses unquoted values fine; we only quote if the value
# contains characters that python-dotenv would otherwise interpret.
# =============================================================================

# Helper: emit `KEY=VALUE` to FD 3, quoting VALUE safely for python-dotenv.
#
# python-dotenv parsing:
#   KEY=value          → literal string (no expansion, ends at #)
#   KEY="value $VAR"   → expands $VAR (we DO NOT want this for passwords)
#   KEY='value $VAR'   → literal $VAR (single quotes are safe)
#
# So if value contains '$', we always single-quote (escaping any embedded
# single quotes via the standard '\'' trick). Otherwise, we use double quotes
# with backslash-escaping when whitespace / # / quotes are present.
_env_line() {
    local key="$1" value="$2"
    if [[ -z "$value" ]]; then
        printf '%s=\n' "$key" >&3
        return
    fi
    if [[ "$value" == *'$'* ]]; then
        # Single-quote (literal) — escape single quotes via '\''
        local escaped="${value//\'/\'\\\'\'}"
        printf "%s='%s'\n" "$key" "$escaped" >&3
    elif [[ "$value" =~ [[:space:]\#\"\'] ]] || [[ "$value" =~ ^[\"\'] ]]; then
        # Double-quote with backslash escapes (no $ inside, so no expansion risk)
        local escaped="${value//\\/\\\\}"
        escaped="${escaped//\"/\\\"}"
        printf '%s="%s"\n' "$key" "$escaped" >&3
    else
        printf '%s=%s\n' "$key" "$value" >&3
    fi
}

write_env_file() {
    header ".env file"

    local env_file="${PI_DIR}/.env"

    if [[ -f "$env_file" ]] && [[ "${SPOTLESS_FORCE_ENV:-0}" != "1" ]]; then
        warn ".env already exists at ${env_file} — keeping it (set SPOTLESS_FORCE_ENV=1 to overwrite)"
        return
    fi

    # Open env_file on FD 3 so _env_line can write to it safely
    exec 3>"$env_file"
    {
        printf '# =============================================================================\n'
        printf '# Project Spotless - Environment (generated by bootstrap.sh on %s)\n' "$(date -Iseconds)"
        printf '# Edit this file directly if you need to change DB / admin / API key values.\n'
        printf '# After edits: sudo systemctl restart %s\n' "$SERVICE_NAME"
        printf '# =============================================================================\n\n'
        printf '# --- Machine identity ---\n'
    } >&3
    _env_line "SPOTLESS_MACHINE_ID" "$MACHINE_ID"

    {
        printf '\n# --- AWS RDS Aurora MySQL ---\n'
    } >&3
    _env_line "SPOTLESS_DB_HOST"     "$DB_HOST"
    _env_line "SPOTLESS_DB_PORT"     "3306"
    _env_line "SPOTLESS_DB_USER"     "$DB_USER"
    _env_line "SPOTLESS_DB_PASSWORD" "$DB_PASSWORD"
    _env_line "SPOTLESS_DB_NAME"     "$DB_NAME"
    _env_line "SPOTLESS_DB_SSL"      "true"

    {
        printf '\n# --- SpotlessBooking API ---\n'
        printf '# Optional shared secret. Must match KIOSK_API_KEY on the booking server.\n'
        printf '# Leave blank for now; set later when the booking team provisions one.\n'
    } >&3
    _env_line "KIOSK_API_KEY" ""

    {
        printf '\n# --- Admin UI (Phase 3 - operator settings page) ---\n'
    } >&3
    _env_line "SPOTLESS_ADMIN_PASSWORD" "$ADMIN_PASSWORD"

    {
        printf '\n# --- Email notifications (optional) ---\n'
        printf '# EMAIL_SENDER=spotlessbs02@gmail.com\n'
        printf '# EMAIL_PASSWORD=your-gmail-app-password\n'
        printf '# EMAIL_RECEIVER=management@petgully.com\n'
    } >&3
    exec 3>&-

    chown "${SPOTLESS_USER}:${SPOTLESS_USER}" "$env_file"
    chmod 600 "$env_file"
    ok "Wrote ${env_file} (mode 600)"
}

# =============================================================================
# 8. Python venv + deps (run as spotless user)
# =============================================================================
setup_python_env() {
    header "Python virtualenv"

    if [[ ! -d "${PI_DIR}/venv" ]]; then
        log "Creating venv at ${PI_DIR}/venv..."
        run_as_spotless "cd '$PI_DIR' && python3 -m venv venv"
        ok "venv created"
    else
        ok "venv already exists"
    fi

    log "Installing/upgrading Python dependencies (this can take a few minutes)..."
    run_as_spotless "cd '$PI_DIR' && source venv/bin/activate && pip install --upgrade --quiet pip && pip install --quiet -r requirements.txt"
    ok "Python dependencies installed"

    # Verify key imports
    local checks=("paho.mqtt.client" "flask" "flask_socketio" "dotenv")
    for mod in "${checks[@]}"; do
        if run_as_spotless "cd '$PI_DIR' && source venv/bin/activate && python3 -c 'import $mod' 2>/dev/null"; then
            ok "import ${mod}: OK"
        else
            warn "import ${mod}: failed"
        fi
    done

    if run_as_spotless "cd '$PI_DIR' && source venv/bin/activate && python3 -c 'import gpiod' 2>/dev/null"; then
        ok "import gpiod: OK"
    else
        warn "gpiod not importable — GPIO will be simulated (OK on dev machines, not on real Pi)"
    fi
}

# =============================================================================
# 9. systemd service
# =============================================================================
install_systemd_service() {
    header "systemd service (${SERVICE_NAME})"

    local unit="/etc/systemd/system/${SERVICE_NAME}"

    cat > "$unit" <<EOF
[Unit]
Description=Project Spotless - Kiosk Web Server
After=network-online.target mosquitto.service
Wants=network-online.target mosquitto.service

[Service]
Type=simple
User=${SPOTLESS_USER}
Group=${SPOTLESS_USER}
WorkingDirectory=${PI_DIR}
EnvironmentFile=-${PI_DIR}/.env
ExecStart=${PI_DIR}/venv/bin/python ${PI_DIR}/main.py --kiosk
Restart=always
RestartSec=5
StartLimitIntervalSec=120
StartLimitBurst=10
StandardOutput=journal
StandardError=journal
# Allow up to 2 minutes for clean shutdown (in-progress sessions)
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
    ok "Wrote ${unit}"
    ok "Service enabled (will auto-start on boot)"
}

# =============================================================================
# 10. logrotate
# =============================================================================
install_logrotate() {
    header "Log rotation"

    cat > /etc/logrotate.d/spotless <<EOF
${CONFIG_DIR}/logs/*.log {
    daily
    rotate 7
    maxsize 50M
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    su ${SPOTLESS_USER} ${SPOTLESS_USER}
}
EOF
    ok "Wrote /etc/logrotate.d/spotless (daily, 7 days, 50MB cap)"
}

# =============================================================================
# 11. Weekly reboot cron
# =============================================================================
install_weekly_reboot() {
    header "Weekly reboot (Sunday 3 AM)"

    cat > /etc/cron.d/spotless-weekly-reboot <<'EOF'
# Project Spotless — weekly preventive reboot
# Sunday 03:00 local time (no customers active at this hour)
SHELL=/bin/sh
PATH=/usr/sbin:/usr/bin:/sbin:/bin
0 3 * * 0 root /sbin/shutdown -r now "Weekly maintenance reboot" >/dev/null 2>&1
EOF
    chmod 644 /etc/cron.d/spotless-weekly-reboot
    ok "Cron installed: /etc/cron.d/spotless-weekly-reboot"
}

# =============================================================================
# 12. Chromium kiosk autostart
# =============================================================================
setup_kiosk_browser() {
    header "Chromium kiosk autostart"

    local autostart_dir="${SPOTLESS_HOME}/.config/autostart"
    run_as_spotless "mkdir -p '$autostart_dir'"

    # Detect chromium binary (Bookworm: chromium-browser; some images: chromium)
    local chrome_bin="chromium-browser"
    if ! command -v chromium-browser >/dev/null 2>&1; then
        if command -v chromium >/dev/null 2>&1; then
            chrome_bin="chromium"
        fi
    fi

    cat > "${autostart_dir}/spotless-browser.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Spotless Kiosk Browser
Comment=Open Spotless kiosk UI in fullscreen
Exec=bash -c 'until curl -sf http://localhost:${KIOSK_PORT} >/dev/null; do sleep 2; done; ${chrome_bin} --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble --disable-features=TranslateUI --no-first-run --check-for-update-interval=604800 --incognito http://localhost:${KIOSK_PORT}'
X-GNOME-Autostart-enabled=true
EOF
    chown "${SPOTLESS_USER}:${SPOTLESS_USER}" "${autostart_dir}/spotless-browser.desktop"
    ok "Chromium will open fullscreen on login (waits for Flask to be ready)"

    # Disable screen blanking (X11 autostart)
    local lxde_autostart="${SPOTLESS_HOME}/.config/lxsession/LXDE-pi/autostart"
    run_as_spotless "mkdir -p '$(dirname "$lxde_autostart")'"
    if [[ ! -f "$lxde_autostart" ]]; then
        cat > "$lxde_autostart" <<'EOF'
@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@xset s off
@xset -dpms
@xset s noblank
@unclutter -idle 0.5 -root
EOF
    else
        for line in "@xset s off" "@xset -dpms" "@xset s noblank" "@unclutter -idle 0.5 -root"; do
            grep -qF "$line" "$lxde_autostart" || echo "$line" >> "$lxde_autostart"
        done
    fi
    chown -R "${SPOTLESS_USER}:${SPOTLESS_USER}" "${SPOTLESS_HOME}/.config/lxsession" 2>/dev/null || true
    ok "Screen blanking disabled"

    # Auto-login
    if [[ -f /etc/lightdm/lightdm.conf ]]; then
        if grep -q "^autologin-user=" /etc/lightdm/lightdm.conf; then
            sed -i "s|^autologin-user=.*|autologin-user=${SPOTLESS_USER}|" /etc/lightdm/lightdm.conf
        else
            sed -i "s|^#autologin-user=.*|autologin-user=${SPOTLESS_USER}|" /etc/lightdm/lightdm.conf || \
                echo "autologin-user=${SPOTLESS_USER}" >> /etc/lightdm/lightdm.conf
        fi
        ok "LightDM auto-login set to '${SPOTLESS_USER}'"
    elif command -v raspi-config >/dev/null 2>&1; then
        raspi-config nonint do_boot_behaviour B4 >/dev/null 2>&1 || true
        ok "Auto-login configured via raspi-config"
    else
        warn "Could not configure auto-login automatically. Run: sudo raspi-config → System → Boot → Desktop Autologin"
    fi
}

# =============================================================================
# 13. Start the service + verify
# =============================================================================
start_and_verify() {
    header "Starting kiosk service"

    systemctl restart "$SERVICE_NAME" || warn "Service restart returned non-zero (will check status anyway)"
    sleep 5

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "${SERVICE_NAME} is active"
    else
        warn "${SERVICE_NAME} is not active — check: journalctl -u ${SERVICE_NAME} -n 50"
    fi

    log "Waiting up to 30s for Flask to respond on :${KIOSK_PORT}..."
    local attempts=0
    while (( attempts < 15 )); do
        if curl -sf "http://localhost:${KIOSK_PORT}/api/status" >/dev/null 2>&1; then
            ok "Flask responding on :${KIOSK_PORT}"
            break
        fi
        ((attempts++)) || true
        sleep 2
    done
    if (( attempts >= 15 )); then
        warn "Flask did not respond in time. Check: journalctl -u ${SERVICE_NAME} -n 50"
    fi

    # ESP32 status check (best-effort, non-blocking)
    log "Checking for ESP32 nodes (5s scan)..."
    local nodes_seen
    nodes_seen=$(timeout 5 mosquitto_sub -h localhost -t "spotless/nodes/+/status" -C 3 2>/dev/null | wc -l || echo 0)
    if (( nodes_seen >= 3 )); then
        ok "All 3 ESP32 nodes online"
    elif (( nodes_seen > 0 )); then
        warn "${nodes_seen}/3 ESP32 nodes detected (others may connect once powered)"
    else
        warn "No ESP32 nodes detected yet (power them on; they'll auto-connect)"
    fi
}

# =============================================================================
# 14. Final summary
# =============================================================================
print_summary() {
    local final_ip
    final_ip="$(hostname -I | awk '{print $1}')"

    echo ""
    echo -e "${GREEN}=============================================${NC}"
    echo -e "${BOLD}${GREEN}  Bootstrap complete!${NC}"
    echo -e "${GREEN}=============================================${NC}"
    echo ""
    echo -e "  ${BOLD}Machine ID:${NC}     ${MACHINE_ID}"
    echo -e "  ${BOLD}IP address:${NC}     ${final_ip}"
    echo -e "  ${BOLD}Kiosk URL:${NC}      http://${final_ip}:${KIOSK_PORT}"
    echo -e "  ${BOLD}Repo path:${NC}      ${REPO_DIR}"
    echo -e "  ${BOLD}Config file:${NC}    ${CONFIG_DIR}/config.json"
    echo -e "  ${BOLD}Env file:${NC}       ${PI_DIR}/.env"
    echo ""
    echo -e "${CYAN}Next steps${NC}"
    echo "  1. Reboot to apply auto-login + static IP cleanly:"
    echo "       sudo reboot"
    echo ""
    echo "  2. After reboot, the kiosk opens fullscreen automatically."
    echo ""
    echo "  3. Power on the 3 ESP32 nodes — they'll connect on their own."
    echo "     To verify:  bash ${PI_DIR}/scripts/check_nodes.sh"
    echo ""
    echo -e "${CYAN}Service management${NC}"
    echo "       sudo systemctl status ${SERVICE_NAME}"
    echo "       sudo systemctl restart ${SERVICE_NAME}"
    echo "       journalctl -u ${SERVICE_NAME} -f         (live logs)"
    echo ""
    echo -e "${CYAN}Re-run this bootstrap (safe; idempotent)${NC}"
    echo "       sudo bash ${PI_DIR}/scripts/bootstrap.sh"
    echo ""
}

# =============================================================================
# Main
# =============================================================================
main() {
    header "Project Spotless — Pi Bootstrap"
    echo "  Time:  $(date)"
    echo "  Host:  $(hostname)"
    echo ""

    preflight
    gather_inputs
    install_apt_packages
    clone_or_pull_repo
    configure_mosquitto
    configure_static_ip
    setup_spotless_dirs
    write_env_file
    setup_python_env
    install_systemd_service
    install_logrotate
    install_weekly_reboot
    setup_kiosk_browser
    start_and_verify
    print_summary
}

main "$@"
