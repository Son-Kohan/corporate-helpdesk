#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Help Desk backup archive.")
    parser.add_argument("--db", default=None, type=Path, help="Legacy SQLite database path override")
    parser.add_argument("--backup-dir", default=None, type=Path)
    parser.add_argument("--keep", default=None, type=int)
    parser.add_argument("--note", default="scheduled backup")
    args = parser.parse_args()

    if args.db:
        os.environ["HELPDESK_DATABASE_URL"] = f"sqlite+aiosqlite:///{args.db.as_posix()}"
    if args.backup_dir:
        os.environ["HELPDESK_BACKUP_DIR"] = str(args.backup_dir)
    if args.keep is not None:
        os.environ["HELPDESK_BACKUP_KEEP_COUNT"] = str(args.keep)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.backup_manager import backup_dir, create_backup

    backup = create_backup(args.note)
    print(f"Backup created: {backup_dir() / backup.filename}")


if __name__ == "__main__":
    main()
