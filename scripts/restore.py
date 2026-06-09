#!/usr/bin/env python3
import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore Help Desk from backup archive.")
    parser.add_argument("backup", help="Backup filename from HELPDESK_BACKUP_DIR or a local archive path")
    parser.add_argument("--backup-dir", default=None, type=Path)
    args = parser.parse_args()

    if args.backup_dir:
        os.environ["HELPDESK_BACKUP_DIR"] = str(args.backup_dir)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.backup_manager import backup_dir, restore_backup, save_uploaded_backup

    backup_name = Path(args.backup).name
    archive_path = Path(args.backup)
    if archive_path.exists():
        with archive_path.open("rb") as handle:
            class LocalUpload:
                filename = backup_name
                file = handle

            uploaded = save_uploaded_backup(LocalUpload())
            backup_name = uploaded.filename
    else:
        existing = backup_dir() / backup_name
        if not existing.exists():
            raise FileNotFoundError(f"Backup archive was not found: {args.backup}")

    restored = restore_backup(backup_name)
    print(f"Restored backup: {restored.filename}")


if __name__ == "__main__":
    main()
