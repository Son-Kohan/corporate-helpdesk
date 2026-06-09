#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="${1:-/opt/helpdesk}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  echo "Help Desk is not installed in $INSTALL_DIR." >&2
  exit 1
fi

SERVICE_USER="$(stat -c '%U' "$INSTALL_DIR")"
SERVICE_GROUP="$(stat -c '%G' "$INSTALL_DIR")"

trap 'sudo systemctl start helpdesk >/dev/null 2>&1 || true' ERR

sudo systemctl stop helpdesk
sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/python' scripts/backup.py --db helpdesk.db --backup-dir backups --keep 14"

if [[ -d "$INSTALL_DIR/.git" ]]; then
  CURRENT_BRANCH="$(sudo -u "$SERVICE_USER" git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD)"
  sudo -u "$SERVICE_USER" git -C "$INSTALL_DIR" fetch --prune origin
  sudo -u "$SERVICE_USER" git -C "$INSTALL_DIR" pull --ff-only origin "$CURRENT_BRANCH"
elif [[ "$SOURCE_DIR" != "$INSTALL_DIR" ]]; then
  sudo rsync -a --delete \
    --exclude='.env' --exclude='.venv/' --exclude='.pytest_cache/' \
    --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.db' \
    --exclude='backups/' --exclude='logs/' --exclude='uploads/' \
    --exclude='.chrome-test-profile/' --exclude='*-preview.png' \
    "$SOURCE_DIR/" "$INSTALL_DIR/"
else
  echo "Git repository was not found in $INSTALL_DIR. Install the project from GitHub to use web updates." >&2
  exit 1
fi

sudo chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt"
sudo -u "$SERVICE_USER" bash -c "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/python' scripts/migrate.py"
sudo systemctl start helpdesk
trap - ERR

for _ in {1..20}; do
  if curl -fsS http://127.0.0.1/health >/dev/null; then
    echo "Help Desk was updated successfully."
    exit 0
  fi
  sleep 1
done

echo "The service did not pass the health check." >&2
sudo journalctl -u helpdesk -n 30 --no-pager
exit 1
