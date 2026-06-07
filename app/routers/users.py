from datetime import datetime, timedelta, timezone
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_permission
from app.audit import add_audit
from app.config import get_settings
from app.database import get_db
from app.models import Department, Role, Ticket, User
from app.schemas import (
    PasswordChange,
    PasswordReset,
    Token,
    UserAdminCreate,
    UserCreate,
    UserLogin,
    UserProfileUpdate,
    UserRead,
    UserArchive,
    UserUpdate,
)
from app.security import create_access_token, hash_password, verify_password
from app.services import email_for_storage, normalize_role, user_to_read

router = APIRouter()
login_attempts: dict[str, list[float]] = {}


def check_login_rate(identifier: str) -> None:
    settings = get_settings()
    now = monotonic()
    attempts = [value for value in login_attempts.get(identifier, []) if now - value < settings.login_lock_seconds]
    login_attempts[identifier] = attempts
    if len(attempts) >= settings.login_attempt_limit:
        raise HTTPException(status_code=429, detail="Слишком много попыток входа. Повторите позже")


def record_failed_login(identifier: str) -> None:
    login_attempts.setdefault(identifier, []).append(monotonic())


async def ensure_role_exists(db: AsyncSession, role_code: str) -> str:
    normalized = normalize_role(role_code)
    if not await db.get(Role, normalized):
        raise HTTPException(status_code=400, detail="Роль не найдена")
    return normalized


async def ensure_unique_user(
    db: AsyncSession,
    username: str,
    email: object | None,
    exclude_user_id: int | None = None,
) -> None:
    conditions = [User.username == username]
    if email:
        conditions.append(User.email == str(email))
    query = select(User).where(or_(*conditions))
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    if (await db.execute(query)).scalars().first():
        raise HTTPException(status_code=400, detail="Пользователь с таким логином или email уже есть")


def normalize_full_name(full_name: str) -> str:
    return " ".join(full_name.split())


def join_full_name(first_name: str, last_name: str) -> str:
    return normalize_full_name(f"{first_name} {last_name}")


async def ensure_unique_full_name(
    db: AsyncSession,
    full_name: str,
    exclude_user_id: int | None = None,
) -> str:
    normalized = normalize_full_name(full_name)
    query = select(User).where(User.full_name == normalized)
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    if (await db.execute(query)).scalars().first():
        raise HTTPException(status_code=400, detail="Пользователь с таким именем и фамилией уже есть")
    return normalized


async def generate_username(db: AsyncSession) -> str:
    from uuid import uuid4

    while True:
        username = f"user_{uuid4().hex[:12]}"
        if not await db.scalar(select(User.id).where(User.username == username)):
            return username


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)) -> UserRead:
    full_name = await ensure_unique_full_name(
        db,
        join_full_name(user_data.first_name, user_data.last_name),
    )
    username = await generate_username(db)

    user = User(
        username=username,
        email=email_for_storage(username),
        full_name=full_name,
        role="user",
        hashed_password=hash_password(user_data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return await user_to_read(db, user)


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_db)) -> Token:
    if credentials.username:
        identifier = credentials.username.strip()
        result = await db.execute(select(User).where(User.username == identifier))
    else:
        identifier = join_full_name(credentials.first_name or "", credentials.last_name or "")
        result = await db.execute(select(User).where(User.full_name == identifier))
    check_login_rate(identifier)
    user = result.scalars().first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        record_failed_login(identifier)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")
    if not user.is_active or user.is_archived:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Учетная запись отключена")
    login_attempts.pop(identifier, None)
    expires = timedelta(days=30) if credentials.remember else None
    return Token(
        access_token=create_access_token(user.username, expires),
        must_change_password=user.must_change_password,
    )


@router.get("/me", response_model=UserRead)
async def read_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    return await user_to_read(db, current_user)


@router.patch("/me", response_model=UserRead)
async def update_me(
    user_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    update_data = user_data.model_dump(exclude_unset=True)
    if "email" in update_data:
        email = update_data["email"]
        if email and str(email) != current_user.email:
            result = await db.execute(select(User).where(User.email == str(email), User.id != current_user.id))
            if result.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email уже используется")
        current_user.email = email_for_storage(current_user.username, email)
    first_name = update_data.get("first_name")
    last_name = update_data.get("last_name")
    if first_name is not None and last_name is not None:
        current_user.full_name = await ensure_unique_full_name(
            db,
            join_full_name(first_name, last_name),
            current_user.id,
        )

    await add_audit(
        db,
        current_user,
        "profile.updated",
        "user",
        current_user.id,
        user_data.model_dump(exclude_unset=True),
    )
    await db.commit()
    await db.refresh(current_user)
    return await user_to_read(db, current_user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")
    current_user.hashed_password = hash_password(payload.new_password)
    current_user.must_change_password = False
    await add_audit(db, current_user, "password.changed", "user", current_user.id)
    await db.commit()


@router.get("/", response_model=list[UserRead])
async def list_users(
    _: User = Depends(require_permission("users.read")),
    db: AsyncSession = Depends(get_db),
) -> list[UserRead]:
    result = await db.execute(select(User).order_by(User.username))
    return [await user_to_read(db, user) for user in result.scalars().all()]


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user_by_admin(
    user_data: UserAdminCreate,
    _: User = Depends(require_permission("users.create")),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    await ensure_unique_user(db, user_data.username, user_data.email)
    if user_data.department_id and not await db.get(Department, user_data.department_id):
        raise HTTPException(status_code=400, detail="Отдел не найден")
    full_name = await ensure_unique_full_name(
        db,
        join_full_name(user_data.first_name, user_data.last_name),
    )

    user = User(
        username=user_data.username,
        email=email_for_storage(user_data.username, user_data.email),
        full_name=full_name,
        role=await ensure_role_exists(db, user_data.role),
        is_active=user_data.is_active,
        department_id=user_data.department_id,
        hashed_password=hash_password(user_data.password),
    )
    db.add(user)
    await db.flush()
    await add_audit(db, _, "user.created", "user", user.id, {"username": user.username, "role": user.role})
    await db.commit()
    await db.refresh(user)
    return await user_to_read(db, user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    _: User = Depends(require_permission("users.update")),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    update_data = user_data.model_dump(exclude_unset=True)
    password = update_data.pop("password", None)
    first_name = update_data.pop("first_name", None)
    last_name = update_data.pop("last_name", None)
    username = update_data.pop("username", None)

    if username and username != user.username:
        await ensure_unique_user(db, username, None, user.id)
        old_username = user.username
        user.username = username
        if user.email == email_for_storage(old_username):
            user.email = email_for_storage(username)

    if first_name is not None and last_name is not None:
        user.full_name = await ensure_unique_full_name(
            db,
            join_full_name(first_name, last_name),
            user.id,
        )

    for field, value in update_data.items():
        if field == "role" and value:
            value = await ensure_role_exists(db, value)
        if field == "email":
            if value and str(value) != user.email:
                result = await db.execute(select(User).where(User.email == str(value), User.id != user.id))
                if result.scalar_one_or_none():
                    raise HTTPException(status_code=400, detail="Email уже используется")
            value = email_for_storage(user.username, value)
        if field == "department_id" and value and not await db.get(Department, value):
            raise HTTPException(status_code=400, detail="Отдел не найден")
        setattr(user, field, value)
    if password:
        user.hashed_password = hash_password(password)
        user.must_change_password = False

    audit_details = user_data.model_dump(exclude_unset=True, exclude={"password"})
    await add_audit(db, _, "user.updated", "user", user.id, audit_details)
    await db.commit()
    await db.refresh(user)
    return await user_to_read(db, user)


@router.post("/{user_id}/archive", response_model=UserRead)
async def archive_user(
    user_id: int,
    payload: UserArchive,
    current_user: User = Depends(require_permission("users.archive")),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.id == current_user.id and payload.archived:
        raise HTTPException(status_code=400, detail="Нельзя архивировать собственную учетную запись")
    user.is_archived = payload.archived
    user.is_active = not payload.archived
    user.archived_at = datetime.now(timezone.utc) if payload.archived else None
    await add_audit(db, current_user, "user.archived" if payload.archived else "user.restored", "user", user.id)
    await db.commit()
    await db.refresh(user)
    return await user_to_read(db, user)


@router.post("/{user_id}/reset-password", response_model=UserRead)
async def reset_user_password(
    user_id: int,
    payload: PasswordReset,
    current_user: User = Depends(require_permission("users.reset_password")),
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.hashed_password = hash_password(payload.temporary_password)
    user.must_change_password = True
    await add_audit(db, current_user, "user.password_reset", "user", user.id)
    await db.commit()
    await db.refresh(user)
    return await user_to_read(db, user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_permission("users.delete")),
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить собственную учетную запись")
    has_tickets = await db.scalar(
        select(Ticket.id).where(or_(Ticket.created_by == user.id, Ticket.assigned_to == user.id)).limit(1)
    )
    if has_tickets:
        raise HTTPException(status_code=409, detail="У пользователя есть связанные данные. Используйте архивирование")
    await add_audit(db, current_user, "user.deleted", "user", user.id, {"username": user.username})
    await db.delete(user)
    await db.commit()
