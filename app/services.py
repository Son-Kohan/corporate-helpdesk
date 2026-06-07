import csv
import io
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Attachment,
    Category,
    Department,
    Notification,
    Role,
    SystemSetting,
    Ticket,
    TicketHistory,
    User,
)
from app.permissions import DEFAULT_ROLE_NAMES, DEFAULT_ROLE_PERMISSIONS
from app.schemas import TicketRead, UserRead

SLA_HOURS = {
    "critical": 4,
    "high": 24,
    "medium": 72,
    "low": 120,
}

INTERNAL_EMAIL_SUFFIX = "@helpdesk.invalid"


def normalize_role(role: str) -> str:
    return "service" if role == "operator" else role


def email_for_storage(username: str, email: object | None = None) -> str:
    return str(email) if email else f"{username}{INTERNAL_EMAIL_SUFFIX}"


def public_email(email: str | None) -> str | None:
    if not email or email.endswith(INTERNAL_EMAIL_SUFFIX):
        return None
    return email


async def user_to_read(db: AsyncSession, user: User) -> UserRead:
    role_code = normalize_role(user.role)
    role = await db.get(Role, role_code)
    permissions: list[str] = []
    role_name = None
    if role:
        role_name = role.name
        try:
            import json

            permissions = list(json.loads(role.permissions_json or "[]"))
        except json.JSONDecodeError:
            permissions = []
    else:
        role_name = DEFAULT_ROLE_NAMES.get(role_code)
        permissions = DEFAULT_ROLE_PERMISSIONS.get(role_code, [])
    name_parts = (user.full_name or "").split(maxsplit=1)
    first_name = name_parts[0] if name_parts else None
    last_name = name_parts[1] if len(name_parts) > 1 else None
    department = await db.get(Department, user.department_id) if user.department_id else None
    return UserRead.model_validate(user).model_copy(
        update={
            "email": public_email(user.email),
            "first_name": first_name,
            "last_name": last_name,
            "department_name": department.name if department else None,
            "role": role_code,
            "role_name": role_name,
            "permissions": permissions,
        }
    )


async def sla_hours_for_ticket(db: AsyncSession, ticket: Ticket) -> int:
    if ticket.category_id:
        category = await db.get(Category, ticket.category_id)
        if category and category.sla_hours:
            return category.sla_hours
    setting = await db.get(SystemSetting, f"sla.{ticket.priority}")
    if setting:
        try:
            return int(setting.value)
        except ValueError:
            pass
    return SLA_HOURS.get(ticket.priority, 72)


def sla_due_at(ticket: Ticket, sla_hours: int | None = None) -> datetime | None:
    created_at = ticket.created_at
    if not created_at:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at + timedelta(hours=sla_hours or SLA_HOURS.get(ticket.priority, 72))


def is_ticket_overdue(ticket: Ticket, sla_hours: int | None = None) -> bool:
    if ticket.status == "closed":
        return False
    due_at = sla_due_at(ticket, sla_hours)
    if not due_at:
        return False
    return datetime.now(timezone.utc) > due_at


async def ticket_to_read(db: AsyncSession, ticket: Ticket) -> TicketRead:
    users_result = await db.execute(
        select(User).where(User.id.in_([value for value in [ticket.created_by, ticket.assigned_to] if value]))
    )
    users = {user.id: user for user in users_result.scalars().all()}

    attachments_count = int(
        (await db.execute(select(func.count(Attachment.id)).where(Attachment.ticket_id == ticket.id))).scalar_one()
    )
    sla_hours = await sla_hours_for_ticket(db, ticket)
    due_at = sla_due_at(ticket, sla_hours)
    category = await db.get(Category, ticket.category_id) if ticket.category_id else None
    return TicketRead.model_validate(ticket).model_copy(
        update={
            "creator_name": _display_user(users.get(ticket.created_by)),
            "assignee_name": _display_user(users.get(ticket.assigned_to)) if ticket.assigned_to else None,
            "due_at": due_at,
            "sla_hours": sla_hours,
            "is_overdue": is_ticket_overdue(ticket, sla_hours),
            "attachments_count": attachments_count,
            "category_name": category.name if category else None,
        }
    )


async def tickets_to_read(db: AsyncSession, tickets: Iterable[Ticket]) -> list[TicketRead]:
    return [await ticket_to_read(db, ticket) for ticket in tickets]


async def add_history(
    db: AsyncSession,
    ticket_id: int,
    user: User | None,
    action: str,
    field: str | None = None,
    old_value: object | None = None,
    new_value: object | None = None,
    note: str | None = None,
) -> None:
    db.add(
        TicketHistory(
            ticket_id=ticket_id,
            user_id=user.id if user else None,
            action=action,
            field=field,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
            note=note,
        )
    )


async def notify_users(db: AsyncSession, ticket: Ticket, subject: str, message: str) -> None:
    recipients: list[str] = []
    recipient_users: list[User] = []
    creator = await db.get(User, ticket.created_by)
    assignee = await db.get(User, ticket.assigned_to) if ticket.assigned_to else None
    for user in [creator, assignee]:
        if user and public_email(user.email) and user.email not in recipients:
            recipients.append(user.email)
        if user and user.id not in [item.id for item in recipient_users]:
            recipient_users.append(user)

    for user in recipient_users:
        db.add(
            Notification(
                user_id=user.id,
                ticket_id=ticket.id,
                title=subject,
                message=message,
            )
        )
    await db.commit()

    settings = get_settings()
    log_path = Path(settings.notification_log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.open("a", encoding="utf-8").write(
        f"{datetime.now().isoformat(timespec='seconds')} | {', '.join(recipients) or '-'} | {subject} | {message}\n"
    )

    if not settings.smtp_host or not recipients:
        return

    msg = MIMEText(message, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.notification_from
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


def tickets_to_csv(tickets: Iterable[TicketRead]) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(
        [
            "ID",
            "Тема",
            "Статус",
            "Приоритет",
            "Автор",
            "Исполнитель",
            "Создана",
            "SLA до",
            "Просрочена",
            "Вложения",
        ]
    )
    for ticket in tickets:
        writer.writerow(
            [
                ticket.id,
                ticket.title,
                ticket.status,
                ticket.priority,
                ticket.creator_name or "",
                ticket.assignee_name or "",
                ticket.created_at.isoformat() if ticket.created_at else "",
                ticket.due_at.isoformat() if ticket.due_at else "",
                "да" if ticket.is_overdue else "нет",
                ticket.attachments_count,
            ]
        )
    return stream.getvalue()


def _display_user(user: User | None) -> str | None:
    if not user:
        return None
    return user.full_name or user.username
