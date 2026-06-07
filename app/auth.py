import json

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Role, User
from app.permissions import DEFAULT_ROLE_PERMISSIONS
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось проверить учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        username = decode_access_token(token)
    except ValueError as exc:
        raise credentials_error from exc

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not user.is_active or user.is_archived:
        raise credentials_error
    return user


def require_roles(*roles: str):
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return current_user

    return dependency


async def get_user_permissions(user: User, db: AsyncSession) -> set[str]:
    role_code = "service" if user.role == "operator" else user.role
    role = await db.get(Role, role_code)
    if role:
        try:
            return set(json.loads(role.permissions_json or "[]"))
        except json.JSONDecodeError:
            return set()
    return set(DEFAULT_ROLE_PERMISSIONS.get(role_code, []))


async def has_permission(user: User, permission: str, db: AsyncSession) -> bool:
    return permission in await get_user_permissions(user, db)


def require_permission(permission: str):
    async def dependency(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not await has_permission(current_user, permission, db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
        return current_user

    return dependency


async def is_staff(user: User, db: AsyncSession) -> bool:
    permissions = await get_user_permissions(user, db)
    return "tickets.read_all" in permissions or "tickets.update_all" in permissions
