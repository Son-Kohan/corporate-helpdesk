import os
import shutil
from pathlib import Path

import pytest

os.environ["HELPDESK_DATABASE_URL"] = "sqlite+aiosqlite:///./test_helpdesk.db"
os.environ["HELPDESK_SECRET_KEY"] = "test-secret"
os.environ["HELPDESK_UPLOAD_DIR"] = "./test_uploads"
os.environ["HELPDESK_MAX_ATTACHMENT_BYTES"] = "1024"
os.environ["HELPDESK_NOTIFICATION_LOG"] = "./test_logs/notifications.log"

from app.database import AsyncSessionLocal, Base, engine
from app.seed import ensure_default_catalogs, ensure_default_roles


@pytest.fixture(autouse=True)
async def reset_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        await ensure_default_roles(db)
        await ensure_default_catalogs(db)
    yield

    for path in [Path("test_uploads"), Path("test_logs")]:
        if path.resolve().is_relative_to(Path.cwd().resolve()) and path.exists():
            shutil.rmtree(path)
