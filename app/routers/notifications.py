from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Notification, User
from app.schemas import NotificationRead

router = APIRouter()


@router.get("/", response_model=list[NotificationRead])
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Notification]:
    query = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    return list((await db.execute(query.order_by(desc(Notification.created_at)).limit(limit))).scalars().all())


@router.patch("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    item = await db.get(Notification, notification_id)
    if not item or item.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    item.is_read = True
    await db.commit()


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    await db.commit()
