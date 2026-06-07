import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_permission
from app.database import get_db
from app.models import AuditLog, User
from app.schemas import AuditLogRead
from app.services import public_email

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
