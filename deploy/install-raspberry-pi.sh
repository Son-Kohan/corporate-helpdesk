#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="/opt/helpdesk"
HOST_NAME="helpdesk"
LAN_CIDR=""
COPY_DATA=0
ENABLE_FIREWALL=0
SET_HOSTNAME=1

usage() {
  cat <<'EOF'
Install Help Desk on Raspberry Pi OS / Debian.

Usage:
  bash deploy/install-raspberry-pi.sh [options]

Options:
  --copy-data          Copy helpdesk.db from the project into the installation.
  --enable-firewall    Enable UFW and allow HTTP/SSH only from the local subnet.
  --lan CIDR           Local subnet, for example 192.168.1.0/24.
  --hostname NAME      Local host name without .local (default: helpdesk).
  --install-dir PATH   Installation directory (default: /opt/helpdesk).
  --keep-hostname      Do not change the Raspberry Pi host name.
  -h, --help           Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --copy-data) COPY_DATA=1 ;;
    --enable-firewall) ENABLE_FIREWALL=1 ;;
    --lan) LAN_CIDR="${2:?Missing value for --lan}"; shift ;;
    --hostname) HOST_NAME="${2:?Missing value for --hostname}"; shift ;;
    --install-dir) INSTALL_DIR="${2:?Missing value for --install-dir}"; shift ;;
    --keep-hostname) SET_HOSTNAME=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This installer must be run on Raspberry Pi OS or another Debian-based Linux system." >&2
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get was not found. Raspberry Pi OS or Debian is required." >&2
  exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cat "$SOURCE_DIR/VERSION" 2>/dev/null || echo "1.0.0")"
SERVICE_USER="${SUDO_USER:-$USER}"
if [[ "$SERVICE_USER" == "root" ]]; then
  echo "Run the installer as the desktop user, not as root: bash deploy/install-raspberry-pi.sh" >&2
  exit 1
fi
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"

if [[ -z "$LAN_CIDR" ]]; then
  DEFAULT_INTERFACE="$(ip -4 route show default | awk '{print $5; exit}')"
  if [[ -n "$DEFAULT_INTERFACE" ]]; then
    LAN_CIDR="$(ip -4 route show dev "$DEFAULT_INTERFACE" scope link | awk '$1 ~ /^[0-9]+\./ {print $1; exit}')"
  fi
fi
if [[ -z "$LAN_CIDR" ]]; then
  echo "Could not detect the local subnet. Run again with --lan, for example --lan 192.168.1.0/24." >&2
  exit 1
fi

SERVER_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i=="src") {print $(i+1); exit}}')"
if [[ -z "$SERVER_IP" ]]; then
  SERVER_IP="$(hostname -I | awk '{print $1}')"
fi
if [[ -z "$SERVER_IP" ]]; then
  echo "Could not detect the server IPv4 address." >&2
  exit 1
fi

if [[ ! "$HOST_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$ ]]; then
  echo "Invalid host name: $HOST_NAME" >&2
  exit 1
fi
if [[ ! "$LAN_CIDR" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]]; then
  echo "Invalid local subnet: $LAN_CIDR" >&2
  exit 1
fi
if [[ "$INSTALL_DIR" != /* ]]; then
  echo "Installation directory must be an absolute path." >&2
  exit 1
fi

echo "Installing Help Desk $VERSION"
echo "  User:       $SERVICE_USER"
echo "  Directory:  $INSTALL_DIR"
echo "  Local IP:   $SERVER_IP"
echo "  Local LAN:  $LAN_CIDR"
echo "  Local name: http://${HOST_NAME}.local"

sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip python3-dev \
  build-essential libssl-dev libffi-dev \
  nginx sqlite3 rsync curl git openssl avahi-daemon ufw

sudo install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" \
  "$INSTALL_DIR" "$INSTALL_DIR/uploads" "$INSTALL_DIR/logs" "$INSTALL_DIR/backups"

RSYNC_EXCLUDES=(
  --exclude='.env'
  --exclude='.venv/'
  --exclude='.pytest_cache/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='*.db'
  --exclude='backups/'
  --exclude='logs/'
  --exclude='uploads/'
  --exclude='.chrome-test-profile/'
  --exclude='*-preview.png'
)
if [[ "$SOURCE_DIR" != "$INSTALL_DIR" ]]; then
  sudo rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$SOURCE_DIR/" "$INSTALL_DIR/"
fi

if [[ "$COPY_DATA" -eq 1 && -f "$SOURCE_DIR/helpdesk.db" && ! -f "$INSTALL_DIR/helpdesk.db" ]]; then
  sudo install -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 640 "$SOURCE_DIR/helpdesk.db" "$INSTALL_DIR/helpdesk.db"
fi

FRESH_DATABASE=0
if [[ ! -f "$INSTALL_DIR/helpdesk.db" ]]; then
  FRESH_DATABASE=1
fi

ADMIN_PASSWORD=""
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  ADMIN_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(14))')"
  sudo tee "$INSTALL_DIR/.env" >/dev/null <<EOF
HELPDESK_DATABASE_URL=sqlite+aiosqlite:///./helpdesk.db
HELPDESK_SECRET_KEY=$SECRET_KEY
HELPDESK_TOKEN_MINUTES=480
HELPDESK_ADMIN_USERNAME=admin
HELPDESK_ADMIN_PASSWORD=$ADMIN_PASSWORD
HELPDESK_ADMIN_EMAIL=admin@helpdesk.local
HELPDESK_UPLOAD_DIR=$INSTALL_DIR/uploads
HELPDESK_NOTIFICATION_LOG=$INSTALL_DIR/logs/notifications.log
HELPDESK_LOGIN_ATTEMPT_LIMIT=8
HELPDESK_LOGIN_LOCK_SECONDS=300
HELPDESK_CORS_ORIGINS=http://${HOST_NAME}.local,http://$SERVER_IP
HELPDESK_BACKUP_DIR=$INSTALL_DIR/backups
HELPDESK_BACKUP_KEEP_COUNT=14
HELPDESK_RUNTIME_MODE=systemd
HELPDESK_REPO_DIR=$INSTALL_DIR
HELPDESK_UPDATE_LOG=$INSTALL_DIR/logs/update.log
HELPDESK_UPDATE_STATE_FILE=$INSTALL_DIR/logs/update-state.json
HELPDESK_ENABLE_WEB_UPDATE=true
HELPDESK_WEB_UPDATE_COMMAND=$INSTALL_DIR/deploy/update-raspberry-pi.sh
EOF
  sudo chown "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/.env"
  sudo chmod 600 "$INSTALL_DIR/.env"
fi

append_env_if_missing() {
  local key="$1"
  local value="$2"
  if ! sudo grep -q "^${key}=" "$INSTALL_DIR/.env"; then
    echo "${key}=${value}" | sudo tee -a "$INSTALL_DIR/.env" >/dev/null
  fi
}

append_env_if_missing "HELPDESK_BACKUP_DIR" "$INSTALL_DIR/backups"
append_env_if_missing "HELPDESK_BACKUP_KEEP_COUNT" "14"
append_env_if_missing "HELPDESK_RUNTIME_MODE" "systemd"
append_env_if_missing "HELPDESK_REPO_DIR" "$INSTALL_DIR"
append_env_if_missing "HELPDESK_UPDATE_LOG" "$INSTALL_DIR/logs/update.log"
append_env_if_missing "HELPDESK_UPDATE_STATE_FILE" "$INSTALL_DIR/logs/update-state.json"
append_env_if_missing "HELPDESK_ENABLE_WEB_UPDATE" "true"
append_env_if_missing "HELPDESK_WEB_UPDATE_COMMAND" "$INSTALL_DIR/deploy/update-raspberry-pi.sh"
sudo chown "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/.env"
sudo chmod 600 "$INSTALL_DIR/.env"

sudo chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"

if [[ ! -x "$INSTALL_DIR/venv/bin/python" ]]; then
  sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/venv"
fi
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" -m pip install --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt"
sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/python' scripts/migrate.py"

sudo tee /etc/systemd/system/helpdesk.service >/dev/null <<EOF
[Unit]
Description=Corporate Help Desk Application
After=network-online.target
Wants=network-online.target

[Service]
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$INSTALL_DIR

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/helpdesk-backup.service >/dev/null <<EOF
[Unit]
Description=Backup Corporate Help Desk SQLite database

[Service]
Type=oneshot
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python scripts/backup.py --db helpdesk.db --backup-dir backups --keep 14
EOF

sudo tee /etc/systemd/system/helpdesk-backup.timer >/dev/null <<'EOF'
[Unit]
Description=Daily Corporate Help Desk backup

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo tee /etc/systemd/system/helpdesk-monitor.service >/dev/null <<EOF
[Unit]
Description=Monitor Corporate Help Desk host

[Service]
Type=oneshot
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=-$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/python scripts/monitor.py --log logs/helpdesk_monitor.log
EOF

sudo tee /etc/systemd/system/helpdesk-monitor.timer >/dev/null <<'EOF'
[Unit]
Description=Monitor Corporate Help Desk every five minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo tee /etc/nginx/sites-available/helpdesk >/dev/null <<EOF
server {
    listen 80;
    server_name ${HOST_NAME}.local $SERVER_IP;

    allow 127.0.0.1;
    allow ::1;
    allow $LAN_CIDR;
    deny all;

    client_max_body_size 16m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
    }

    location /static/ {
        alias $INSTALL_DIR/static/;
        expires 1h;
        add_header Cache-Control "public";
        add_header X-Content-Type-Options "nosniff";
    }
}
EOF

sudo ln -sfn /etc/nginx/sites-available/helpdesk /etc/nginx/sites-enabled/helpdesk
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t

if [[ "$SET_HOSTNAME" -eq 1 ]]; then
  sudo hostnamectl set-hostname "$HOST_NAME"
fi

if [[ "$ENABLE_FIREWALL" -eq 1 ]]; then
  sudo ufw default deny incoming
  sudo ufw default allow outgoing
  sudo ufw allow from "$LAN_CIDR" to any port 22 proto tcp
  sudo ufw allow from "$LAN_CIDR" to any port 80 proto tcp
  sudo ufw --force enable
fi

sudo systemctl daemon-reload
sudo systemctl enable --now avahi-daemon nginx helpdesk helpdesk-backup.timer helpdesk-monitor.timer
sudo systemctl restart nginx helpdesk

for _ in {1..20}; do
  if curl -fsS http://127.0.0.1/health >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1/health >/dev/null

echo
echo "Help Desk $VERSION is installed."
echo "Open from another computer in the local network:"
echo "  http://$SERVER_IP"
echo "  http://${HOST_NAME}.local"
echo
echo "Diagnostics:"
echo "  bash $INSTALL_DIR/deploy/diagnose-raspberry-pi.sh"
if [[ -n "$ADMIN_PASSWORD" && "$FRESH_DATABASE" -eq 1 ]]; then
  echo
  echo "Initial administrator:"
  echo "  Login:    admin"
  echo "  Password: $ADMIN_PASSWORD"
  echo "Change this password after the first login."
fi
