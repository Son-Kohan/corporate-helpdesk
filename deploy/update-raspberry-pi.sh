#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="${1:-/opt/helpdesk}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  echo "Help Desk is not installed in $INSTALL_DIR." >&2
  exit 1
fi

SERVICE_USER="$(stat -c '%U' "$INSTALL_DIR")"
CURRENT_USER="$(id -un)"
RUNNING_AS_ROOT=0
if [[ "$(id -u)" -eq 0 ]]; then
  RUNNING_AS_ROOT=1
elif [[ "$CURRENT_USER" != "$SERVICE_USER" ]]; then
  echo "Run this script as $SERVICE_USER or root." >&2
  exit 1
fi

run_as_service_user() {
  if [[ "$RUNNING_AS_ROOT" -eq 1 ]]; then
    sudo -u "$SERVICE_USER" "$@"
  else
    "$@"
  fi
}

run_shell_as_service_user() {
  if [[ "$RUNNING_AS_ROOT" -eq 1 ]]; then
    sudo -u "$SERVICE_USER" bash -c "$1"
  else
    bash -c "$1"
  fi
}

echo "Updating Help Desk in $INSTALL_DIR"

if [[ "${HELPDESK_SKIP_SCRIPT_BACKUP:-0}" != "1" ]]; then
  run_shell_as_service_user "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/python' scripts/backup.py --db helpdesk.db --backup-dir backups --keep 14"
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  CURRENT_BRANCH="$(run_as_service_user git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD)"
  run_as_service_user git -C "$INSTALL_DIR" fetch --prune origin
  run_as_service_user git -C "$INSTALL_DIR" pull --ff-only origin "$CURRENT_BRANCH"
elif [[ "$SOURCE_DIR" != "$INSTALL_DIR" ]]; then
  if [[ "$RUNNING_AS_ROOT" -ne 1 ]]; then
    echo "Rsync update requires root when the project is not a Git repository." >&2
    exit 1
  fi
  sudo rsync -a --delete \
    --exclude='.env' --exclude='.venv/' --exclude='venv/' --exclude='.pytest_cache/' \
    --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.db' \
    --exclude='backups/' --exclude='logs/' --exclude='uploads/' \
    --exclude='.chrome-test-profile/' --exclude='*-preview.png' \
    "$SOURCE_DIR/" "$INSTALL_DIR/"
  sudo chown -R "$SERVICE_USER:$(id -gn "$SERVICE_USER")" "$INSTALL_DIR"
else
  echo "Git repository was not found in $INSTALL_DIR. Install the project from GitHub to use web updates." >&2
  exit 1
fi

run_as_service_user "$INSTALL_DIR/venv/bin/python" -m pip install -r "$INSTALL_DIR/requirements.txt"
run_shell_as_service_user "cd '$INSTALL_DIR' && '$INSTALL_DIR/venv/bin/python' scripts/migrate.py"

if [[ "$RUNNING_AS_ROOT" -eq 1 ]]; then
  sudo systemctl restart helpdesk
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
fi

echo "Help Desk files were updated successfully. The application process will restart now."
