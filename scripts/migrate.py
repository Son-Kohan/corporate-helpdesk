#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import AsyncSessionLocal, init_db
from app.seed import ensure_default_admin, ensure_default_catalogs, ensure_default_roles


async def migrate() -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        await ensure_default_roles(db)
        await ensure_default_admin(db)
        await ensure_default_catalogs(db)
    print("Database schema is up to date.")


if __name__ == "__main__":
    asyncio.run(migrate())
