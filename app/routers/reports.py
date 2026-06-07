from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, has_permission
from app.database import get_db
from app.models import Ticket, User
from app.schemas import DashboardStats, DayCount
from app.services import tickets_to_csv, tickets_to_read

router = APIRouter()


async def scoped(query, user: User, db: AsyncSession):
    if await has_permission(user, "tickets.read_all", db):
        return query
    return query.where(Ticket.created_by == user.id)


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardStats:
    if not await has_permission(current_user, "reports.view", db):
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    total_result = await db.execute(await scoped(select(func.count(Ticket.id)), current_user, db))
    total = int(total_result.scalar_one())

    status_result = await db.execute(
        await scoped(select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status), current_user, db)
    )
    by_status = {status: int(count) for status, count in status_result.all()}

    priority_result = await db.execute(
        await scoped(select(Ticket.priority, func.count(Ticket.id)).group_by(Ticket.priority), current_user, db)
    )
    by_priority = {priority: int(count) for priority, count in priority_result.all()}

    tickets_result = await db.execute(await scoped(select(Ticket), current_user, db))
    overdue = sum(1 for ticket in await tickets_to_read(db, tickets_result.scalars().all()) if ticket.is_overdue)

    start = datetime.now(timezone.utc) - timedelta(days=6)
    day_query = (
        select(func.date(Ticket.created_at), func.count(Ticket.id))
        .where(Ticket.created_at >= start)
        .group_by(func.date(Ticket.created_at))
        .order_by(func.date(Ticket.created_at))
    )
    day_result = await db.execute(await scoped(day_query, current_user, db))
    counts_by_day = {str(day): int(count) for day, count in day_result.all()}

    by_day: list[DayCount] = []
    for offset in range(7):
        day = (start + timedelta(days=offset)).date().isoformat()
        by_day.append(DayCount(day=day, count=counts_by_day.get(day, 0)))

    return DashboardStats(
        total=total,
        by_status=by_status,
        by_priority=by_priority,
        overdue=overdue,
        by_day=by_day,
    )


@router.get("/export.csv")
async def export_tickets_csv(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    if not await has_permission(current_user, "reports.export", db):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    result = await db.execute(await scoped(select(Ticket).order_by(desc(Ticket.created_at)), current_user, db))
    tickets = await tickets_to_read(db, result.scalars().all())
    content = tickets_to_csv(tickets)
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tickets.csv"'},
    )
