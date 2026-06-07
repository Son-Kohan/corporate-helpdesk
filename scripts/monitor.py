#!/usr/bin/env python3
import argparse
import datetime as dt
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

import psutil


def get_cpu_temp() -> float | None:
    thermal_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if not thermal_path.exists():
        return None
    try:
        return int(thermal_path.read_text(encoding="utf-8").strip()) / 1000.0
    except (OSError, ValueError):
        return None


def send_alert(message: str) -> None:
    sender = os.getenv("ALERT_EMAIL_FROM")
    receiver = os.getenv("ALERT_EMAIL_TO")
    smtp_host = os.getenv("ALERT_SMTP_HOST", "localhost")
    if not sender or not receiver:
        return

    msg = MIMEText(message, _charset="utf-8")
    msg["Subject"] = "Help Desk Server Alert"
    msg["From"] = sender
    msg["To"] = receiver

    with smtplib.SMTP(smtp_host) as server:
        server.send_message(msg)


def collect_alerts(args: argparse.Namespace) -> list[str]:
    alerts: list[str] = []
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage(args.disk_path).percent
    temp = get_cpu_temp()

    if cpu > args.cpu:
        alerts.append(f"CPU usage high: {cpu:.1f}%")
    if ram > args.ram:
        alerts.append(f"RAM usage high: {ram:.1f}%")
    if disk > args.disk:
        alerts.append(f"Disk usage high: {disk:.1f}%")
    if temp is not None and temp > args.temp:
        alerts.append(f"CPU temperature high: {temp:.1f} C")

    return alerts


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor Help Desk host resources.")
    parser.add_argument("--cpu", default=80.0, type=float)
    parser.add_argument("--ram", default=85.0, type=float)
    parser.add_argument("--disk", default=90.0, type=float)
    parser.add_argument("--temp", default=75.0, type=float)
    parser.add_argument("--disk-path", default="/")
    parser.add_argument("--log", default="logs/helpdesk_monitor.log", type=Path)
    args = parser.parse_args()

    alerts = collect_alerts(args)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} - {', '.join(alerts) or 'OK'}\n"
    with args.log.open("a", encoding="utf-8") as log_file:
        log_file.write(line)

    if alerts:
        send_alert("\n".join(alerts))
        print("\n".join(alerts))
    else:
        print("OK")


if __name__ == "__main__":
    main()
