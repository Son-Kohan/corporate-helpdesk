#!/usr/bin/env python3
import argparse
import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path


def create_backup(db_path: Path, backup_dir: Path, keep: int) -> Path:
    db_path = db_path.resolve()
    backup_dir = backup_dir.resolve()

    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"{db_path.stem}_{timestamp}{db_path.suffix}"
    with closing(sqlite3.connect(db_path)) as source, closing(sqlite3.connect(target)) as destination:
        source.backup(destination)

    backups = sorted(backup_dir.glob(f"{db_path.stem}_*{db_path.suffix}"))
    for old_backup in backups[:-keep]:
        old_backup.unlink()

    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Create SQLite database backup.")
    parser.add_argument("--db", default="helpdesk.db", type=Path)
    parser.add_argument("--backup-dir", default="backups", type=Path)
    parser.add_argument("--keep", default=7, type=int)
    args = parser.parse_args()

    backup = create_backup(args.db, args.backup_dir, args.keep)
    print(f"Backup created: {backup}")


if __name__ == "__main__":
    main()
