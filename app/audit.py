import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


async def add_audit(
    db: AsyncSession,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: object | None = None,
    details: object | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=None if entity_id is None else str(entity_id),
            details=None
            if details is None
            else json.dumps(details, ensure_ascii=False, default=str),
        )
    )
