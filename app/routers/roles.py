import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_permission
from app.audit import add_audit
from app.database import get_db
from app.models import Role, User
from app.permissions import ALL_PERMISSIONS
from app.schemas import PermissionRead, RoleCreate, RoleRead, RoleUpdate
from app.services import normalize_role

router = APIRouter()


def role_to_read(role: Role) -> RoleRead:
    try:
        permissions = json.loads(role.permissions_json or "[]")
    except json.JSONDecodeError:
        permissions = []
    return RoleRead(
        code=role.code,
        name=role.name,
        permissions=permissions,
        is_system=role.is_system,
    )


def validate_permissions(permissions: list[str]) -> list[str]:
    unknown = sorted(set(permissions) - set(ALL_PERMISSIONS))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Неизвестные права: {', '.join(unknown)}")
    return sorted(set(permissions))


@router.get("/permissions", response_model=list[PermissionRead])
async def list_permissions(_: User = Depends(require_permission("roles.manage"))) -> list[PermissionRead]:
    return [PermissionRead(code=code, name=name) for code, name in ALL_PERMISSIONS.items()]


@router.get("/", response_model=list[RoleRead])
async def list_roles(
    _: User = Depends(require_permission("roles.manage")),
    db: AsyncSession = Depends(get_db),
) -> list[RoleRead]:
    result = await db.execute(select(Role).order_by(Role.is_system.desc(), Role.name))
    return [role_to_read(role) for role in result.scalars().all()]


@router.post("/", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(
    role_data: RoleCreate,
    _: User = Depends(require_permission("roles.manage")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    code = normalize_role(role_data.code)
    if await db.get(Role, code):
        raise HTTPException(status_code=400, detail="Роль с таким кодом уже существует")
    role = Role(
        code=code,
        name=role_data.name,
        permissions_json=json.dumps(validate_permissions(role_data.permissions)),
        is_system=False,
    )
    db.add(role)
    await db.flush()
    await add_audit(db, _, "role.created", "role", role.code, {"name": role.name})
    await db.commit()
    await db.refresh(role)
    return role_to_read(role)


@router.put("/{role_code}", response_model=RoleRead)
async def update_role(
    role_code: str,
    role_data: RoleUpdate,
    _: User = Depends(require_permission("roles.manage")),
    db: AsyncSession = Depends(get_db),
) -> RoleRead:
    role = await db.get(Role, normalize_role(role_code))
    if not role:
        raise HTTPException(status_code=404, detail="Роль не найдена")
    role.name = role_data.name
    role.permissions_json = json.dumps(validate_permissions(role_data.permissions))
    await add_audit(db, _, "role.updated", "role", role.code, role_data.model_dump())
    await db.commit()
    await db.refresh(role)
    return role_to_read(role)
