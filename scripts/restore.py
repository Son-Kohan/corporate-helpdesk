#!/usr/bin/env python3
import argparse
import shutil
import sqlite3
from pathlib import Path


def restore_backup(backup: Path, target: Path) -> None:
    backup = backup.resolve()
    target = target.resolve()
    if not backup.exists():
        raise FileNotFoundError(f"Backup not found: {backup}")
    with sqlite3.connect(backup) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup database integrity check failed")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a verified SQLite backup.")
    parser.add_argument("backup", type=Path)
    parser.add_argument("--target", default="helpdesk.db", type=Path)
    args = parser.parse_args()
    restore_backup(args.backup, args.target)
    print(f"Database restored to: {args.target.resolve()}")


if __name__ == "__main__":
    main()
