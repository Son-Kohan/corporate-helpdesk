from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.backup_manager import create_backup, repo_dir, runtime_mode
from app.config import Settings, get_settings
from app.schemas import UpdateJobRead, UpdateLogRead, UpdateStatusRead

_STATE_LOCK = threading.Lock()
_REDACTION_PATTERNS = [
    re.compile(r"((?:password|secret|token|key)\s*[=:]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(postgresql(?:\+\w+)?://[^:\s]+:)([^@/\s]+)(@)", re.IGNORECASE),
]


def log_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    configured = (settings.update_log or "").strip()
    if configured:
        target = Path(configured)
        return target if target.is_absolute() else (repo_dir(settings) / target).resolve()
    if os.name == "nt":
        return repo_dir(settings) / "logs" / "update.log"
    if runtime_mode(settings) == "docker":
        return Path("/app/logs/update.log")
    return Path("/opt/helpdesk/logs/update.log")


def state_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    configured = (settings.update_state_file or "").strip()
    if configured:
        target = Path(configured)
        return target if target.is_absolute() else (repo_dir(settings) / target).resolve()
    return log_path(settings).with_name("update-state.json")


def job_path(job_id: str, settings: Settings | None = None) -> Path:
    return state_path(settings).with_name(f"update-job-{job_id}.json")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_state(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "last_check_at": None,
        "last_check_status": "idle",
        "last_check_message": None,
        "remote_commit": None,
        "update_available": None,
        "last_update_at": None,
        "last_update_status": "idle",
        "last_update_message": None,
        "last_job_id": None,
        "update_log_path": str(log_path(settings)),
    }


def _git_command(*args: str, settings: Settings | None = None) -> subprocess.CompletedProcess[str]:
    settings = settings or get_settings()
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo_dir(settings)}", "-C", str(repo_dir(settings)), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(*args: str, settings: Settings | None = None) -> str | None:
    try:
        return _git_command(*args, settings=settings).stdout.strip() or None
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _current_status(settings: Settings | None = None) -> UpdateStatusRead:
    settings = settings or get_settings()
    stored = _read_json(state_path(settings), _default_state(settings))
    return UpdateStatusRead(
        app_version=_read_version(settings),
        current_commit=_git_output("rev-parse", "HEAD", settings=settings),
        current_branch=_git_output("rev-parse", "--abbrev-ref", "HEAD", settings=settings),
        runtime_mode=runtime_mode(settings),
        web_update_enabled=settings.enable_web_update,
        update_available=stored.get("update_available"),
        remote_commit=stored.get("remote_commit"),
        last_check_at=_parse_datetime(stored.get("last_check_at")),
        last_check_status=stored.get("last_check_status") or "idle",
        last_check_message=stored.get("last_check_message"),
        last_update_at=_parse_datetime(stored.get("last_update_at")),
        last_update_status=stored.get("last_update_status") or "idle",
        last_update_message=stored.get("last_update_message"),
        last_job_id=stored.get("last_job_id"),
        update_log_path=stored.get("update_log_path") or str(log_path(settings)),
    )


def _read_version(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    version_file = repo_dir(settings) / "VERSION"
    if version_file.exists():
        version = version_file.read_text(encoding="utf-8").strip()
        if version:
            return version
    return settings.app_version


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_status(settings: Settings | None = None) -> UpdateStatusRead:
    return _current_status(settings)


def check_updates(settings: Settings | None = None) -> UpdateStatusRead:
    settings = settings or get_settings()
    payload = _default_state(settings) | _read_json(state_path(settings), _default_state(settings))
    branch = _git_output("rev-parse", "--abbrev-ref", "HEAD", settings=settings)
    current_commit = _git_output("rev-parse", "HEAD", settings=settings)
    if not branch or not current_commit:
        payload.update(
            {
                "last_check_at": datetime.now(timezone.utc).isoformat(),
                "last_check_status": "failed",
                "last_check_message": "Git repository is unavailable",
                "update_available": None,
                "remote_commit": None,
            }
        )
        _write_json(state_path(settings), payload)
        return _current_status(settings)
    try:
        _git_command("fetch", "--quiet", "origin", settings=settings)
        remote_commit = _git_output("rev-parse", f"origin/{branch}", settings=settings)
        payload.update(
            {
                "last_check_at": datetime.now(timezone.utc).isoformat(),
                "last_check_status": "success",
                "last_check_message": "Update check completed",
                "remote_commit": remote_commit,
                "update_available": bool(remote_commit and remote_commit != current_commit),
            }
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
        payload.update(
            {
                "last_check_at": datetime.now(timezone.utc).isoformat(),
                "last_check_status": "failed",
                "last_check_message": detail or "git fetch failed",
                "update_available": None,
            }
        )
    _write_json(state_path(settings), payload)
    return _current_status(settings)


def _update_command(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    if settings.web_update_command:
        command_path = Path(settings.web_update_command)
        return ["bash", str(command_path)]
    script_name = "update-docker.sh" if runtime_mode(settings) == "docker" else "update-raspberry-pi.sh"
    return ["bash", str((repo_dir(settings) / "deploy" / script_name).resolve())]


def _append_log(text: str, settings: Settings | None = None) -> None:
    target = log_path(settings)
    _ensure_parent(target)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _write_job(job_id: str, payload: dict[str, Any], settings: Settings | None = None) -> None:
    _write_json(job_path(job_id, settings), payload)


def _run_update_job(job_id: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    started_at = datetime.now(timezone.utc).isoformat()
    with _STATE_LOCK:
        state_payload = _default_state(settings) | _read_json(state_path(settings), _default_state(settings))
        state_payload.update(
            {
                "last_job_id": job_id,
                "last_update_status": "running",
                "last_update_at": started_at,
                "last_update_message": "Update started",
            }
        )
        _write_json(state_path(settings), state_payload)
        _write_job(
            job_id,
            {
                "job_id": job_id,
                "status": "running",
                "started_at": started_at,
                "finished_at": None,
                "message": "Update started",
                "exit_code": None,
            },
            settings,
        )

    command = _update_command(settings)
    _append_log(f"[{started_at}] Update job {job_id} started\n", settings)
    try:
        backup = create_backup("pre-update backup", settings)
        _append_log(f"[{started_at}] Pre-update backup created: {backup.filename}\n", settings)
        with log_path(settings).open("a", encoding="utf-8") as handle:
            process = subprocess.run(
                command,
                cwd=repo_dir(settings),
                check=False,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        finished_at = datetime.now(timezone.utc).isoformat()
        succeeded = process.returncode == 0
        message = "Update completed successfully" if succeeded else "Update command failed"
        with _STATE_LOCK:
            state_payload = _default_state(settings) | _read_json(state_path(settings), _default_state(settings))
            state_payload.update(
                {
                    "last_job_id": job_id,
                    "last_update_status": "success" if succeeded else "failed",
                    "last_update_at": finished_at,
                    "last_update_message": message,
                }
            )
            _write_json(state_path(settings), state_payload)
            _write_job(
                job_id,
                {
                    "job_id": job_id,
                    "status": "success" if succeeded else "failed",
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "message": message,
                    "exit_code": process.returncode,
                },
                settings,
            )
        _append_log(f"[{finished_at}] Update job {job_id} finished with exit code {process.returncode}\n", settings)
    except Exception as exc:
        finished_at = datetime.now(timezone.utc).isoformat()
        with _STATE_LOCK:
            state_payload = _default_state(settings) | _read_json(state_path(settings), _default_state(settings))
            state_payload.update(
                {
                    "last_job_id": job_id,
                    "last_update_status": "failed",
                    "last_update_at": finished_at,
                    "last_update_message": str(exc),
                }
            )
            _write_json(state_path(settings), state_payload)
            _write_job(
                job_id,
                {
                    "job_id": job_id,
                    "status": "failed",
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "message": str(exc),
                    "exit_code": None,
                },
                settings,
            )
        _append_log(f"[{finished_at}] Update job {job_id} failed: {exc}\n", settings)


def run_update(settings: Settings | None = None) -> UpdateJobRead:
    settings = settings or get_settings()
    if not settings.enable_web_update:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Web update is disabled. Enable HELPDESK_ENABLE_WEB_UPDATE to allow it.",
        )

    current = _current_status(settings)
    if current.last_update_status == "running" and current.last_job_id:
        return get_job(current.last_job_id, settings)

    job_id = uuid.uuid4().hex
    thread = threading.Thread(target=_run_update_job, args=(job_id, settings), daemon=True)
    thread.start()
    return UpdateJobRead(job_id=job_id, status="queued", message="Update job queued")


def get_job(job_id: str, settings: Settings | None = None) -> UpdateJobRead:
    settings = settings or get_settings()
    payload = _read_json(job_path(job_id, settings), {})
    if not payload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Update job not found")
    return UpdateJobRead(
        job_id=payload["job_id"],
        status=payload["status"],
        started_at=_parse_datetime(payload.get("started_at")),
        finished_at=_parse_datetime(payload.get("finished_at")),
        message=payload.get("message"),
        exit_code=payload.get("exit_code"),
    )


def read_update_log(lines: int = 80, settings: Settings | None = None) -> UpdateLogRead:
    settings = settings or get_settings()
    target = log_path(settings)
    if not target.exists():
        return UpdateLogRead(lines=[])
    content = target.read_text(encoding="utf-8", errors="ignore").splitlines()
    tail = content[-max(1, lines):]
    sanitized = []
    for line in tail:
        safe_line = line
        for pattern in _REDACTION_PATTERNS:
            safe_line = pattern.sub(r"\1***\3" if pattern.groups == 3 else r"\1***", safe_line)
        sanitized.append(safe_line)
    return UpdateLogRead(lines=sanitized)
