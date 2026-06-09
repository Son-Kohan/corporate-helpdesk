import csv
import io
from asyncio import to_thread

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit
from app.auth import require_permission
from app.backup_manager import (
    backup_file_path,
    create_backup,
    delete_backup,
    list_backups,
    restore_backup,
    save_uploaded_backup,
)
from app.database import get_db
from app.models import AuditLog, User
from app.schemas import (
    AuditLogRead,
    BackupCreate,
    BackupRead,
    OperationResult,
    UpdateJobRead,
    UpdateLogRead,
    UpdateStatusRead,
)
from app.services import public_email
from app.update_manager import check_updates, get_job, get_status, read_update_log, run_update

router = APIRouter()


@router.get("/audit", response_model=list[AuditLogRead])
async def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("audit.read")),
) -> list[AuditLogRead]:
    rows = (
        await db.execute(
            select(AuditLog, User)
            .join(User, AuditLog.user_id == User.id, isouter=True)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
    ).all()
    return [
        AuditLogRead.model_validate(item).model_copy(
            update={"user_name": user.full_name or user.username if user else None}
        )
        for item, user in rows
    ]


@router.get("/users.csv")
async def export_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("reports.export")),
) -> Response:
    users = (await db.execute(select(User).order_by(User.username))).scalars().all()
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(["ID", "Логин", "ФИО", "Email", "Роль", "Активен", "Архив"])
    for user in users:
        writer.writerow(
            [
                user.id,
                user.username,
                user.full_name or "",
                public_email(user.email) or "",
                user.role,
                "да" if user.is_active else "нет",
                "да" if user.is_archived else "нет",
            ]
        )
    return Response(
        content=stream.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="users.csv"'},
    )


@router.get("/backups", response_model=list[BackupRead])
async def admin_backups(_: User = Depends(require_permission("manage_backups"))) -> list[BackupRead]:
    return await to_thread(list_backups)


@router.post("/backups", response_model=BackupRead, status_code=status.HTTP_201_CREATED)
async def admin_create_backup(
    payload: BackupCreate | None = None,
    current_user: User = Depends(require_permission("manage_backups")),
    db: AsyncSession = Depends(get_db),
) -> BackupRead:
    note = payload.note if payload and payload.note else "manual backup"
    backup = await to_thread(create_backup, note)
    await add_audit(db, current_user, "backup.created", "backup", backup.filename)
    await db.commit()
    return backup


@router.get("/backups/{filename}/download")
async def admin_download_backup(
    filename: str,
    current_user: User = Depends(require_permission("manage_backups")),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    file_path = await to_thread(backup_file_path, filename)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup-файл не найден")
    await add_audit(db, current_user, "backup.downloaded", "backup", filename)
    await db.commit()
    return FileResponse(file_path, media_type="application/gzip", filename=file_path.name)


@router.delete("/backups/{filename}", response_model=OperationResult)
async def admin_delete_backup(
    filename: str,
    current_user: User = Depends(require_permission("manage_backups")),
    db: AsyncSession = Depends(get_db),
) -> OperationResult:
    await to_thread(delete_backup, filename)
    await add_audit(db, current_user, "backup.deleted", "backup", filename)
    await db.commit()
    return OperationResult(message="Резервная копия удалена")


@router.post("/backups/{filename}/restore", response_model=BackupRead)
async def admin_restore_backup(
    filename: str,
    current_user: User = Depends(require_permission("manage_backups")),
    db: AsyncSession = Depends(get_db),
) -> BackupRead:
    restored = await to_thread(restore_backup, filename)
    await add_audit(db, current_user, "backup.restored", "backup", filename)
    await db.commit()
    return restored


@router.post("/backups/upload", response_model=BackupRead, status_code=status.HTTP_201_CREATED)
async def admin_upload_backup(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("manage_backups")),
    db: AsyncSession = Depends(get_db),
) -> BackupRead:
    uploaded = await to_thread(save_uploaded_backup, file)
    await add_audit(db, current_user, "backup.uploaded", "backup", uploaded.filename)
    await db.commit()
    return uploaded


@router.get("/update/status", response_model=UpdateStatusRead)
async def admin_update_status(_: User = Depends(require_permission("manage_updates"))) -> UpdateStatusRead:
    return await to_thread(get_status)


@router.post("/update/check", response_model=UpdateStatusRead)
async def admin_update_check(
    current_user: User = Depends(require_permission("manage_updates")),
    db: AsyncSession = Depends(get_db),
) -> UpdateStatusRead:
    status_data = await to_thread(check_updates)
    await add_audit(db, current_user, "update.checked", "system", details={"available": status_data.update_available})
    await db.commit()
    return status_data


@router.post("/update/run", response_model=UpdateJobRead)
async def admin_update_run(
    current_user: User = Depends(require_permission("manage_updates")),
    db: AsyncSession = Depends(get_db),
) -> UpdateJobRead:
    job = await to_thread(run_update)
    await add_audit(db, current_user, "update.started", "system", entity_id=job.job_id)
    await db.commit()
    return job


@router.get("/update/jobs/{job_id}", response_model=UpdateJobRead)
async def admin_update_job(job_id: str, _: User = Depends(require_permission("manage_updates"))) -> UpdateJobRead:
    return await to_thread(get_job, job_id)


@router.get("/update/logs", response_model=UpdateLogRead)
async def admin_update_logs(
    lines: int = Query(default=80, ge=1, le=500),
    _: User = Depends(require_permission("manage_updates")),
) -> UpdateLogRead:
    return await to_thread(read_update_log, lines)
