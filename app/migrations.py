from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


SQLITE_COLUMNS = {
    "users": {
        "is_archived": "BOOLEAN NOT NULL DEFAULT 0",
        "must_change_password": "BOOLEAN NOT NULL DEFAULT 0",
        "department_id": "INTEGER REFERENCES departments(id)",
        "archived_at": "DATETIME",
    },
    "tickets": {
        "category_id": "INTEGER REFERENCES categories(id)",
        "cancelled_at": "DATETIME",
        "confirmed_at": "DATETIME",
        "closure_reason": "TEXT",
    },
    "ticket_history": {
        "note": "TEXT",
    },
}


async def migrate_schema(engine: AsyncEngine) -> None:
    if engine.dialect.name != "sqlite":
        return

    async with engine.begin() as connection:
        for table, columns in SQLITE_COLUMNS.items():
            result = await connection.execute(text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result.fetchall()}
            for name, definition in columns.items():
                if name not in existing:
                    await connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
        await connection.execute(text("DROP TABLE IF EXISTS comments"))
        await connection.execute(text("DROP TABLE IF EXISTS checklist_items"))
        await connection.execute(text("DROP TABLE IF EXISTS response_templates"))
        ticket_columns = {
            row[1] for row in (await connection.execute(text("PRAGMA table_info(tickets)"))).fetchall()
        }
        if "time_spent_minutes" in ticket_columns:
            await connection.execute(text("ALTER TABLE tickets DROP COLUMN time_spent_minutes"))
