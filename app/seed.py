import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Category, Department, Role, SystemSetting, User
from app.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_NAMES, DEFAULT_ROLE_PERMISSIONS
from app.security import hash_password


async def ensure_default_roles(db: AsyncSession) -> None:
    for code, permissions in DEFAULT_ROLE_PERMISSIONS.items():
        role = await db.get(Role, code)
        if role:
            if not role.name:
                role.name = DEFAULT_ROLE_NAMES[code]
            if not role.permissions_json:
                role.permissions_json = json.dumps(permissions)
            elif code == "user":
                try:
                    current_permissions = set(json.loads(role.permissions_json))
                except json.JSONDecodeError:
                    current_permissions = set()
                legacy_permissions = set(permissions) | {"reports.view"}
                if current_permissions == legacy_permissions:
                    role.permissions_json = json.dumps(permissions)
            elif code in {"service", "admin"}:
                try:
                    current_permissions = set(json.loads(role.permissions_json))
                except json.JSONDecodeError:
                    current_permissions = set()
                role.permissions_json = json.dumps(sorted((current_permissions | set(permissions)) & set(ALL_PERMISSIONS)))
            continue
        db.add(
            Role(
                code=code,
                name=DEFAULT_ROLE_NAMES[code],
                permissions_json=json.dumps(permissions),
                is_system=True,
            )
        )

    roles = (await db.execute(select(Role))).scalars().all()
    valid_permissions = set(ALL_PERMISSIONS)
    for role in roles:
        try:
            current_permissions = set(json.loads(role.permissions_json))
        except json.JSONDecodeError:
            current_permissions = set()
        cleaned_permissions = current_permissions & valid_permissions
        if cleaned_permissions != current_permissions:
            role.permissions_json = json.dumps(sorted(cleaned_permissions))

    await db.execute(update(User).where(User.role == "operator").values(role="service"))
    await db.commit()


async def ensure_default_catalogs(db: AsyncSession) -> None:
    if not await db.scalar(select(Department.id).limit(1)):
        db.add_all(
            [
                Department(name="Общий отдел"),
                Department(name="Сервисная служба"),
            ]
        )
    if not await db.scalar(select(Category.id).limit(1)):
        db.add_all(
            [
                Category(name="Оборудование", sla_hours=48),
                Category(name="Программное обеспечение", sla_hours=72),
                Category(name="Доступы и учетные записи", sla_hours=24),
                Category(name="Сеть и связь", sla_hours=12),
            ]
        )
    for key, value in {
        "sla.critical": "4",
        "sla.high": "24",
        "sla.medium": "72",
        "sla.low": "120",
    }.items():
        if not await db.get(SystemSetting, key):
            db.add(SystemSetting(key=key, value=value))
    await db.commit()


async def ensure_default_admin(db: AsyncSession) -> None:
    settings = get_settings()
    result = await db.execute(select(User).where(User.username == settings.default_admin_username))
    if result.scalar_one_or_none():
        return

    admin = User(
        username=settings.default_admin_username,
        email=settings.default_admin_email,
        full_name="Администратор",
        role="admin",
        hashed_password=hash_password(settings.default_admin_password),
    )
    db.add(admin)
    await db.commit()
