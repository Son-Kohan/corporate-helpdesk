#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="/opt/helpdesk"
PURGE_DATA=0

while (($#)); do
  case "$1" in
    --install-dir) INSTALL_DIR="${2:?Missing value for --install-dir}"; shift ;;
    --purge-data) PURGE_DATA=1 ;;
    -h|--help)
      echo "Usage: bash deploy/uninstall-raspberry-pi.sh [--install-dir PATH] [--purge-data]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

sudo systemctl disable --now helpdesk helpdesk-backup.timer helpdesk-monitor.timer 2>/dev/null || true
sudo rm -f \
  /etc/systemd/system/helpdesk.service \
  /etc/systemd/system/helpdesk-backup.service \
  /etc/systemd/system/helpdesk-backup.timer \
  /etc/systemd/system/helpdesk-monitor.service \
  /etc/systemd/system/helpdesk-monitor.timer \
  /etc/nginx/sites-enabled/helpdesk \
  /etc/nginx/sites-available/helpdesk
sudo systemctl daemon-reload
sudo systemctl restart nginx 2>/dev/null || true

if [[ "$PURGE_DATA" -eq 1 ]]; then
  REAL_INSTALL_DIR="$(readlink -f "$INSTALL_DIR")"
  if [[ "$REAL_INSTALL_DIR" != /opt/*/helpdesk && "$REAL_INSTALL_DIR" != /srv/*/helpdesk && "$REAL_INSTALL_DIR" != "/opt/helpdesk" && "$REAL_INSTALL_DIR" != "/srv/helpdesk" ]]; then
    echo "Refusing to remove unsafe path: $REAL_INSTALL_DIR" >&2
    exit 1
  fi
  sudo rm -rf --one-file-system "$REAL_INSTALL_DIR"
  echo "Help Desk services and data were removed."
else
  echo "Help Desk services were removed. Data remains in $INSTALL_DIR."
fi
