from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import asc, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, has_permission
from app.audit import add_audit
from app.config import get_settings
from app.database import get_db
from app.models import Attachment, Category, Department, Ticket, TicketHistory, User
from app.schemas import (
    AttachmentRead,
    BulkTicketUpdate,
    TicketCreate,
    TicketHistoryRead,
    TicketPriority,
    TicketRead,
    TicketStatusChange,
    TicketStatus,
    TicketUpdate,
)
from app.services import add_history, notify_users, ticket_to_read, tickets_to_read
from app.websocket import manager

router = APIRouter()

SORT_COLUMNS = {
    "created_at": Ticket.created_at,
    "updated_at": Ticket.updated_at,
    "status": Ticket.status,
    "priority": Ticket.priority,
    "title": Ticket.title,
}


async def ensure_ticket_access(ticket: Ticket, user: User, db: AsyncSession) -> None:
    if await has_permission(user, "tickets.read_all", db):
        return
    if ticket.created_by == user.id and await has_permission(user, "tickets.read_own", db):
        return
    if ticket.assigned_to == user.id and await has_permission(user, "tickets.read_assigned", db):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к заявке")


@router.post("/", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    ticket_data: TicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketRead:
    if not await has_permission(current_user, "tickets.create", db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    ticket = Ticket(
        title=ticket_data.title,
        description=ticket_data.description,
        priority=ticket_data.priority,
        category_id=ticket_data.category_id,
        created_by=current_user.id,
    )
    if ticket_data.category_id:
        category = await db.get(Category, ticket_data.category_id)
        if not category or not category.is_active:
            raise HTTPException(status_code=400, detail="Категория не найдена или отключена")
        ticket.assigned_to = category.default_assignee_id
    db.add(ticket)
    await db.flush()
    await add_history(db, ticket.id, current_user, "created")
    await add_audit(db, current_user, "ticket.created", "ticket", ticket.id)
    await db.commit()
    await db.refresh(ticket)
    await notify_users(
        db,
        ticket,
        f"Создана заявка #{ticket.id}",
        f"{current_user.full_name or current_user.username} создал заявку: {ticket.title}",
    )
    await manager.broadcast("all", {"type": "ticket_created", "ticket_id": ticket.id})
    return await ticket_to_read(db, ticket)


@router.get("/", response_model=list[TicketRead])
async def list_tickets(
    scope: str = Query(default="all", pattern="^(all|mine|assigned|department)$"),
    status_filter: TicketStatus | None = Query(default=None, alias="status"),
    priority: TicketPriority | None = None,
    assigned_to: int | None = None,
    category_id: int | None = None,
    q: str | None = Query(default=None, max_length=100),
    sort_by: str = Query(default="created_at", pattern="^(created_at|updated_at|status|priority|title)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TicketRead]:
    query = select(Ticket)
    can_read_all = await has_permission(current_user, "tickets.read_all", db)
    can_read_own = await has_permission(current_user, "tickets.read_own", db)
    can_read_assigned = await has_permission(current_user, "tickets.read_assigned", db)
    can_read_department = await has_permission(current_user, "tickets.read_department", db)

    if scope == "all" and can_read_all:
        pass
    elif scope == "assigned" and can_read_assigned:
        query = query.where(Ticket.assigned_to == current_user.id)
    elif scope == "department" and can_read_department and current_user.department_id:
        department = await db.get(Department, current_user.department_id)
        if not department or department.manager_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет доступа к заявкам отдела")
        query = query.join(User, Ticket.created_by == User.id).where(User.department_id == current_user.department_id)
    elif can_read_own:
        query = query.where(Ticket.created_by == current_user.id)
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    if status_filter:
        query = query.where(Ticket.status == status_filter)
    if priority:
        query = query.where(Ticket.priority == priority)
    if assigned_to:
        query = query.where(Ticket.assigned_to == assigned_to)
    if category_id:
        query = query.where(Ticket.category_id == category_id)
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(Ticket.title.ilike(pattern), Ticket.description.ilike(pattern)))

    sort_column = SORT_COLUMNS[sort_by]
    order = asc(sort_column) if sort_dir == "asc" else desc(sort_column)
    result = await db.execute(query.order_by(order).offset(skip).limit(limit))
    return await tickets_to_read(db, result.scalars().all())


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    attachment = await db.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Вложение не найдено")
    ticket = await db.get(Ticket, attachment.ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    await ensure_ticket_access(ticket, current_user, db)
    path = Path(attachment.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден на диске")
    return FileResponse(path, filename=attachment.filename, media_type=attachment.content_type)


@router.get("/{ticket_id}", response_model=TicketRead)
async def read_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketRead:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    await ensure_ticket_access(ticket, current_user, db)
    return await ticket_to_read(db, ticket)


@router.put("/{ticket_id}", response_model=TicketRead)
async def update_ticket(
    ticket_id: int,
    ticket_data: TicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketRead:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    await ensure_ticket_access(ticket, current_user, db)

    update_data = ticket_data.model_dump(exclude_unset=True)
    can_update_all = await has_permission(current_user, "tickets.update_all", db)
    can_update_own = await has_permission(current_user, "tickets.update_own", db)
    if not can_update_all and not (can_update_own and ticket.created_by == current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    if not can_update_all:
        update_data.pop("assigned_to", None)
    if "assigned_to" in update_data and not await has_permission(current_user, "tickets.assign", db):
        update_data.pop("assigned_to", None)
    if "category_id" in update_data and update_data["category_id"]:
        category = await db.get(Category, update_data["category_id"])
        if not category or not category.is_active:
            raise HTTPException(status_code=400, detail="Категория не найдена или отключена")

    old_values = {
        "title": ticket.title,
        "description": ticket.description,
        "priority": ticket.priority,
        "assigned_to": ticket.assigned_to,
        "category_id": ticket.category_id,
    }
    for field, value in update_data.items():
        setattr(ticket, field, value)

    for field, old_value in old_values.items():
        if field in update_data and old_value != getattr(ticket, field):
            await add_history(db, ticket.id, current_user, "updated", field, old_value, getattr(ticket, field))
    await add_audit(db, current_user, "ticket.updated", "ticket", ticket.id, update_data)

    await db.commit()
    await db.refresh(ticket)
    await notify_users(
        db,
        ticket,
        f"Обновлена заявка #{ticket.id}",
        f"{current_user.full_name or current_user.username} обновил заявку: {ticket.title}",
    )
    await manager.broadcast(str(ticket.id), {"type": "ticket_updated", "ticket_id": ticket.id})
    return await ticket_to_read(db, ticket)


@router.delete("/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if not await has_permission(current_user, "tickets.delete", db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Удалять заявки может сервисный сотрудник")

    await add_audit(db, current_user, "ticket.deleted", "ticket", ticket.id, {"title": ticket.title})
    await db.delete(ticket)
    await db.commit()
    await manager.broadcast("all", {"type": "ticket_deleted", "ticket_id": ticket_id})


@router.post("/actions/bulk", response_model=list[TicketRead])
async def bulk_update_tickets(
    payload: BulkTicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TicketRead]:
    if not await has_permission(current_user, "tickets.bulk", db):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    tickets = list(
        (await db.execute(select(Ticket).where(Ticket.id.in_(payload.ticket_ids)))).scalars().all()
    )
    changes = payload.model_dump(exclude_unset=True, exclude={"ticket_ids"})
    if "assigned_to" in changes and not await has_permission(current_user, "tickets.assign", db):
        changes.pop("assigned_to", None)
    for ticket in tickets:
        for field, value in changes.items():
            old_value = getattr(ticket, field)
            if old_value != value:
                setattr(ticket, field, value)
                await add_history(db, ticket.id, current_user, "updated", field, old_value, value)
    await add_audit(db, current_user, "tickets.bulk_updated", "ticket", details={"ids": payload.ticket_ids, **changes})
    await db.commit()
    for ticket in tickets:
        await db.refresh(ticket)
    await manager.broadcast("all", {"type": "tickets_bulk_updated", "ticket_ids": payload.ticket_ids})
    return await tickets_to_read(db, tickets)


@router.post("/{ticket_id}/status", response_model=TicketRead)
async def change_ticket_status(
    ticket_id: int,
    payload: TicketStatusChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketRead:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    await ensure_ticket_access(ticket, current_user, db)
    can_manage = await has_permission(current_user, "tickets.workflow", db)
    is_owner = ticket.created_by == current_user.id
    old_status = ticket.status
    new_status = payload.status

    owner_transition_allowed = (
        (new_status == "cancelled" and old_status not in {"closed", "cancelled"})
        or (new_status == "closed" and old_status == "resolved")
        or (new_status == "in_progress" and old_status in {"resolved", "closed", "cancelled"})
    )
    if not can_manage and not (is_owner and owner_transition_allowed):
        raise HTTPException(status_code=403, detail="Недостаточно прав для изменения статуса")
    if new_status == old_status:
        raise HTTPException(status_code=400, detail="Недопустимый переход состояния")

    now = datetime.now(timezone.utc)
    ticket.status = new_status
    if new_status == "closed":
        ticket.closed_at = now
        ticket.confirmed_at = now if is_owner else ticket.confirmed_at
    else:
        ticket.closed_at = None
    if new_status == "cancelled":
        ticket.cancelled_at = now
    else:
        ticket.cancelled_at = None
    if new_status in {"resolved", "closed", "cancelled"}:
        ticket.closure_reason = payload.comment
    else:
        ticket.closure_reason = None

    await add_history(
        db,
        ticket.id,
        current_user,
        "status_changed",
        "status",
        old_status,
        new_status,
        note=payload.comment,
    )
    await add_audit(
        db,
        current_user,
        "ticket.status_changed",
        "ticket",
        ticket.id,
        {"old_status": old_status, "new_status": new_status, "comment": payload.comment},
    )
    await db.commit()
    await db.refresh(ticket)
    await notify_users(
        db,
        ticket,
        f"Статус заявки #{ticket.id} изменен",
        f"Новый статус: {ticket.status}. Комментарий: {payload.comment}",
    )
    await manager.broadcast(str(ticket.id), {"type": "ticket_status_changed", "ticket_id": ticket.id})
    return await ticket_to_read(db, ticket)


@router.get("/{ticket_id}/attachments", response_model=list[AttachmentRead])
async def list_attachments(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Attachment]:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    await ensure_ticket_access(ticket, current_user, db)
    result = await db.execute(
        select(Attachment).where(Attachment.ticket_id == ticket_id).order_by(desc(Attachment.uploaded_at))
    )
    return list(result.scalars().all())


@router.post("/{ticket_id}/attachments", response_model=AttachmentRead, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    ticket_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Attachment:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    await ensure_ticket_access(ticket, current_user, db)
    if not await has_permission(current_user, "attachments.manage", db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    settings = get_settings()
    upload_dir = Path(settings.upload_dir) / str(ticket_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "attachment").name
    stored_path = upload_dir / f"{uuid4().hex}_{safe_name}"

    size = 0
    try:
        with stored_path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_attachment_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Файл превышает допустимый размер {settings.max_attachment_bytes // (1024 * 1024)} МБ",
                    )
                target.write(chunk)
    except Exception:
        if stored_path.exists():
            stored_path.unlink()
        raise

    attachment = Attachment(
        ticket_id=ticket_id,
        filename=safe_name,
        stored_path=str(stored_path),
        content_type=file.content_type,
    )
    db.add(attachment)
    await db.flush()
    await add_history(db, ticket_id, current_user, "attachment_added", "filename", None, safe_name)
    await db.commit()
    await db.refresh(attachment)
    await notify_users(
        db,
        ticket,
        f"Добавлено вложение к заявке #{ticket.id}",
        f"{current_user.full_name or current_user.username} добавил файл: {safe_name}",
    )
    await manager.broadcast(str(ticket_id), {"type": "attachment_created", "ticket_id": ticket_id})
    return attachment


@router.delete("/{ticket_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    ticket_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ticket = await db.get(Ticket, ticket_id)
    attachment = await db.get(Attachment, attachment_id)
    if not ticket or not attachment or attachment.ticket_id != ticket_id:
        raise HTTPException(status_code=404, detail="Вложение не найдено")
    await ensure_ticket_access(ticket, current_user, db)
    if not await has_permission(current_user, "attachments.manage", db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")

    path = Path(attachment.stored_path)
    await add_history(db, ticket_id, current_user, "attachment_deleted", "filename", attachment.filename, None)
    await db.delete(attachment)
    await db.commit()
    if path.exists():
        path.unlink()
    await manager.broadcast(str(ticket_id), {"type": "attachment_deleted", "ticket_id": ticket_id})


@router.get("/{ticket_id}/history", response_model=list[TicketHistoryRead])
async def list_history(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TicketHistoryRead]:
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    await ensure_ticket_access(ticket, current_user, db)
    result = await db.execute(
        select(TicketHistory, User)
        .join(User, TicketHistory.user_id == User.id, isouter=True)
        .where(TicketHistory.ticket_id == ticket_id)
        .order_by(desc(TicketHistory.created_at))
    )
    return [
        TicketHistoryRead.model_validate(item).model_copy(
            update={"user_name": user.full_name or user.username if user else None}
        )
        for item, user in result.all()
    ]
