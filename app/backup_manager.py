from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.engine import make_url

from app.config import Settings, get_settings
from app.schemas import BackupRead

BACKUP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz$")


def runtime_mode(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    value = settings.runtime_mode.strip().lower()
    if value in {"docker", "systemd"}:
        return value
    return "docker" if database_type(settings) == "postgresql" else "systemd"


def database_type(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return "postgresql" if settings.database_url.startswith("postgresql") else "sqlite"


def repo_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    base = Path(__file__).resolve().parent.parent
    target = Path(settings.repo_dir or ".")
    return target if target.is_absolute() else (base / target).resolve()


def backup_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    configured = (settings.backup_dir or "").strip()
    if configured:
        target = Path(configured)
    elif os.name == "nt":
        target = repo_dir(settings) / "backups"
    else:
        target = Path("/app/backups" if runtime_mode(settings) == "docker" else "/opt/helpdesk/backups")
    return target if target.is_absolute() else (repo_dir(settings) / target).resolve()


def upload_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    target = Path(settings.upload_dir)
    return target if target.is_absolute() else (repo_dir(settings) / target).resolve()


def sqlite_db_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    url = make_url(settings.database_url)
    database = url.database or "helpdesk.db"
    target = Path(database)
    return target if target.is_absolute() else (repo_dir(settings) / target).resolve()


def _git_commit(settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_dir(settings)), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def _read_version(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    version_file = repo_dir(settings) / "VERSION"
    if version_file.exists():
        value = version_file.read_text(encoding="utf-8").strip()
        if value:
            return value
    return settings.app_version


def _backup_filename() -> str:
    return f"helpdesk_backup_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.tar.gz"


def _resolve_backup_file(filename: str, settings: Settings | None = None) -> Path:
    if not BACKUP_NAME_PATTERN.fullmatch(filename):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректное имя backup-файла")
    root = backup_dir(settings)
    path = (root / filename).resolve()
    if not path.is_relative_to(root.resolve()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Недопустимый путь к backup-файлу")
    return path


def backup_file_path(filename: str, settings: Settings | None = None) -> Path:
    return _resolve_backup_file(filename, settings)


def _pg_env(url: Any) -> dict[str, str]:
    env = os.environ.copy()
    if url.password:
        env["PGPASSWORD"] = url.password
    return env


def _pg_base_command(settings: Settings | None = None) -> tuple[list[str], Any]:
    settings = settings or get_settings()
    url = make_url(settings.database_url)
    if not url.database:
        raise RuntimeError("PostgreSQL database name is not configured")
    command = []
    if url.host:
        command.extend(["--host", url.host])
    if url.port:
        command.extend(["--port", str(url.port)])
    if url.username:
        command.extend(["--username", url.username])
    command.append(url.database)
    return command, url


def _create_database_dump(target_dir: Path, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    target_dir.mkdir(parents=True, exist_ok=True)
    if database_type(settings) == "sqlite":
        source_path = sqlite_db_path(settings)
        if not source_path.exists():
            raise FileNotFoundError(f"Database file not found: {source_path}")
        target_path = target_dir / source_path.name
        with closing(sqlite3.connect(source_path)) as source, closing(sqlite3.connect(target_path)) as destination:
            source.backup(destination)
        return f"database/{target_path.name}"

    command, url = _pg_base_command(settings)
    dump_name = "postgresql.sql"
    dump_path = target_dir / dump_name
    subprocess.run(
        [
            "pg_dump",
            "--format=plain",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(dump_path),
            *command,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_pg_env(url),
    )
    return f"database/{dump_name}"


def _write_manifest(staging_dir: Path, payload: dict[str, Any]) -> None:
    (staging_dir / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_archive(archive_path: Path, staging_dir: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path.unlink()
    with tarfile.open(archive_path, "w:gz") as archive:
        for item in sorted(staging_dir.iterdir()):
            archive.add(item, arcname=item.name)


def _prune_old_backups(root: Path, keep: int) -> None:
    backups = sorted(root.glob("helpdesk_backup_*.tar.gz"), reverse=True)
    for old_file in backups[keep:]:
        old_file.unlink(missing_ok=True)


def _manifest_payload(filename: str, contents: list[str], note: str | None, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "app_version": _read_version(settings),
        "database_type": database_type(settings),
        "backup_file": filename,
        "size_bytes": 0,
        "contents": contents,
        "runtime_mode": runtime_mode(settings),
        "git_commit": _git_commit(settings),
        "note": note,
    }


def create_backup(note: str | None = None, settings: Settings | None = None) -> BackupRead:
    settings = settings or get_settings()
    root = backup_dir(settings)
    filename = _backup_filename()
    archive_path = root / filename

    with tempfile.TemporaryDirectory(prefix="helpdesk-backup-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        staging_dir = temp_dir / "payload"
        database_dir = staging_dir / "database"
        uploads_snapshot = staging_dir / "uploads"
        staging_dir.mkdir(parents=True, exist_ok=True)
        uploads_snapshot.mkdir(parents=True, exist_ok=True)

        db_entry = _create_database_dump(database_dir, settings)
        live_upload_dir = upload_dir(settings)
        if live_upload_dir.exists():
            shutil.copytree(live_upload_dir, uploads_snapshot, dirs_exist_ok=True)

        contents = [db_entry, "uploads", "manifest.json"]
        manifest = _manifest_payload(filename, contents, note, settings)
        _write_manifest(staging_dir, manifest)
        _write_archive(archive_path, staging_dir)
        manifest["size_bytes"] = archive_path.stat().st_size
        _write_manifest(staging_dir, manifest)
        _write_archive(archive_path, staging_dir)

    _prune_old_backups(root, max(1, settings.backup_keep_count))
    return read_backup_metadata(archive_path, settings)


def _safe_extract(archive_path: Path, target_dir: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError("Archive contains unsafe paths")
            resolved = (target_dir / member_path).resolve()
            if not resolved.is_relative_to(target_dir.resolve()):
                raise RuntimeError("Archive extraction escaped target directory")
            if member.isdir():
                resolved.mkdir(parents=True, exist_ok=True)
                continue
            resolved.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            with extracted, resolved.open("wb") as destination:
                shutil.copyfileobj(extracted, destination)


def _restore_sqlite_dump(dump_path: Path, settings: Settings | None = None) -> None:
    target = sqlite_db_path(settings)
    with sqlite3.connect(dump_path) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup database integrity check failed")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dump_path, target)


def _restore_postgresql_dump(dump_path: Path, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    command, url = _pg_base_command(settings)
    subprocess.run(
        [
            "psql",
            *command,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_pg_env(url),
    )
    subprocess.run(
        [
            "psql",
            *command,
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            str(dump_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_pg_env(url),
    )


def _restore_uploads(restored_upload_dir: Path, settings: Settings | None = None) -> None:
    current_upload_dir = upload_dir(settings)
    current_upload_dir.parent.mkdir(parents=True, exist_ok=True)
    rollback_dir = current_upload_dir.parent / f".uploads-rollback-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    if current_upload_dir.exists():
        current_upload_dir.rename(rollback_dir)
    try:
        shutil.copytree(restored_upload_dir, current_upload_dir, dirs_exist_ok=True)
    except Exception:
        shutil.rmtree(current_upload_dir, ignore_errors=True)
        if rollback_dir.exists():
            rollback_dir.rename(current_upload_dir)
        raise
    else:
        shutil.rmtree(rollback_dir, ignore_errors=True)


def _parse_manifest(extracted_dir: Path) -> dict[str, Any]:
    manifest_path = extracted_dir / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("manifest.json was not found in the backup archive")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _restore_archive_file(
    archive_path: Path,
    *,
    create_pre_restore_backup: bool,
    rollback_archive: Path | None,
    settings: Settings | None = None,
) -> BackupRead:
    settings = settings or get_settings()
    if create_pre_restore_backup:
        rollback_archive = _resolve_backup_file(create_backup("pre-restore backup", settings).filename, settings)

    with tempfile.TemporaryDirectory(prefix="helpdesk-restore-") as temp_dir_name:
        extract_root = Path(temp_dir_name)
        _safe_extract(archive_path, extract_root)
        manifest = _parse_manifest(extract_root)
        dump_files = list((extract_root / "database").glob("*"))
        if len(dump_files) != 1:
            raise RuntimeError("Backup archive must contain exactly one database dump")
        if manifest.get("database_type") != database_type(settings):
            raise RuntimeError("Backup database type does not match the current installation")
        dump_path = dump_files[0]
        uploads_path = extract_root / "uploads"
        try:
            if database_type(settings) == "sqlite":
                _restore_sqlite_dump(dump_path, settings)
            else:
                _restore_postgresql_dump(dump_path, settings)
            _restore_uploads(uploads_path, settings)
        except Exception:
            if rollback_archive and rollback_archive != archive_path:
                try:
                    _restore_archive_file(
                        rollback_archive,
                        create_pre_restore_backup=False,
                        rollback_archive=None,
                        settings=settings,
                    )
                except Exception:
                    pass
            raise

    return read_backup_metadata(archive_path, settings)


def restore_backup(filename: str, settings: Settings | None = None) -> BackupRead:
    settings = settings or get_settings()
    archive_path = _resolve_backup_file(filename, settings)
    if not archive_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup-файл не найден")
    try:
        return _restore_archive_file(
            archive_path,
            create_pre_restore_backup=True,
            rollback_archive=None,
            settings=settings,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def delete_backup(filename: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    archive_path = _resolve_backup_file(filename, settings)
    if not archive_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup-файл не найден")
    archive_path.unlink()


def save_uploaded_backup(upload: UploadFile, settings: Settings | None = None) -> BackupRead:
    settings = settings or get_settings()
    original_name = Path(upload.filename or _backup_filename()).name
    if not original_name.endswith(".tar.gz"):
        original_name = _backup_filename()
    archive_path = _resolve_backup_file(original_name, settings)
    if archive_path.exists():
        stem = original_name.removesuffix(".tar.gz")
        archive_path = _resolve_backup_file(f"{stem}_{datetime.now().strftime('%H%M%S')}.tar.gz", settings)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("wb") as destination:
        shutil.copyfileobj(upload.file, destination)
    try:
        return read_backup_metadata(archive_path, settings)
    except Exception as exc:
        archive_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Некорректный backup-файл: {exc}") from exc


def list_backups(settings: Settings | None = None) -> list[BackupRead]:
    settings = settings or get_settings()
    root = backup_dir(settings)
    root.mkdir(parents=True, exist_ok=True)
    return [
        read_backup_metadata(path, settings)
        for path in sorted(root.glob("*.tar.gz"), key=lambda item: item.stat().st_mtime, reverse=True)
    ]


def read_backup_metadata(path: Path, settings: Settings | None = None) -> BackupRead:
    settings = settings or get_settings()
    with tarfile.open(path, "r:gz") as archive:
        manifest_member = archive.getmember("manifest.json")
        manifest_file = archive.extractfile(manifest_member)
        if manifest_file is None:
            raise RuntimeError("manifest.json was not found in archive")
        manifest = json.loads(manifest_file.read().decode("utf-8"))
    created_at_raw = manifest.get("created_at")
    created_at = None
    if created_at_raw:
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
    return BackupRead(
        filename=path.name,
        created_at=created_at,
        size_bytes=int(manifest.get("size_bytes") or path.stat().st_size),
        database_type=manifest.get("database_type") or database_type(settings),
        app_version=manifest.get("app_version"),
        git_commit=manifest.get("git_commit"),
        runtime_mode=manifest.get("runtime_mode") or runtime_mode(settings),
        contents=list(manifest.get("contents") or []),
        note=manifest.get("note"),
    )
