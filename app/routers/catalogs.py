from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import add_audit
from app.auth import get_current_user, require_permission
from app.database import get_db
from app.models import Category, Department, SystemSetting, User
from app.schemas import (
    CategoryBase,
    CategoryRead,
    DepartmentBase,
    DepartmentRead,
    SettingUpdate,
)

router = APIRouter()


@router.get("/departments", response_model=list[DepartmentRead])
async def list_departments(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Department]:
    return list((await db.execute(select(Department).order_by(Department.name))).scalars().all())


@router.post("/departments", response_model=DepartmentRead, status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("catalogs.manage")),
) -> Department:
    department = Department(**payload.model_dump())
    db.add(department)
    await db.flush()
    await add_audit(db, current_user, "department.created", "department", department.id, payload.model_dump())
    await db.commit()
    await db.refresh(department)
    return department


@router.put("/departments/{department_id}", response_model=DepartmentRead)
async def update_department(
    department_id: int,
    payload: DepartmentBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("catalogs.manage")),
) -> Department:
    department = await db.get(Department, department_id)
    if not department:
        raise HTTPException(status_code=404, detail="Отдел не найден")
    for key, value in payload.model_dump().items():
        setattr(department, key, value)
    await add_audit(db, current_user, "department.updated", "department", department.id, payload.model_dump())
    await db.commit()
    await db.refresh(department)
    return department


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Category]:
    return list((await db.execute(select(Category).order_by(Category.name))).scalars().all())


@router.post("/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("catalogs.manage")),
) -> Category:
    category = Category(**payload.model_dump())
    db.add(category)
    await db.flush()
    await add_audit(db, current_user, "category.created", "category", category.id, payload.model_dump())
    await db.commit()
    await db.refresh(category)
    return category


@router.put("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: int,
    payload: CategoryBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("catalogs.manage")),
) -> Category:
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    for key, value in payload.model_dump().items():
        setattr(category, key, value)
    await add_audit(db, current_user, "category.updated", "category", category.id, payload.model_dump())
    await db.commit()
    await db.refresh(category)
    return category


@router.get("/settings", response_model=dict[str, str])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission("catalogs.manage")),
) -> dict[str, str]:
    values = (await db.execute(select(SystemSetting))).scalars().all()
    return {item.key: item.value for item in values}


@router.put("/settings", response_model=dict[str, str])
async def update_settings(
    payload: SettingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("catalogs.manage")),
) -> dict[str, str]:
    allowed = {"sla.critical", "sla.high", "sla.medium", "sla.low"}
    if set(payload.settings) - allowed:
        raise HTTPException(status_code=400, detail="Переданы неизвестные настройки")
    for key, value in payload.settings.items():
        try:
            if int(value) < 1:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="SLA должно быть положительным числом часов") from exc
        setting = await db.get(SystemSetting, key)
        if setting:
            setting.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    await add_audit(db, current_user, "settings.updated", "system_settings", details=payload.settings)
    await db.commit()
    return payload.settings
