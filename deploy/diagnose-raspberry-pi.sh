#!/usr/bin/env bash
set -u

INSTALL_DIR="${1:-/opt/helpdesk}"
FAILED=0

check_command() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    printf '[OK]   %s\n' "$label"
  else
    printf '[FAIL] %s\n' "$label"
    FAILED=1
  fi
}

echo "Help Desk diagnostics"
echo "Version: $(cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo unknown)"
echo "IP addresses: $(hostname -I 2>/dev/null || echo unknown)"
echo

check_command "Help Desk service is active" systemctl is-active --quiet helpdesk
check_command "Nginx service is active" systemctl is-active --quiet nginx
check_command "Backup timer is active" systemctl is-active --quiet helpdesk-backup.timer
check_command "Monitor timer is active" systemctl is-active --quiet helpdesk-monitor.timer
check_command "Nginx configuration is valid" sudo nginx -t
check_command "HTTP health endpoint responds" curl -fsS http://127.0.0.1/health
check_command "Database exists" test -f "$INSTALL_DIR/helpdesk.db"
check_command "Database integrity is valid" bash -c "sqlite3 '$INSTALL_DIR/helpdesk.db' 'PRAGMA quick_check;' | grep -qx ok"

echo
echo "Recent application log:"
sudo journalctl -u helpdesk -n 10 --no-pager
exit "$FAILED"
