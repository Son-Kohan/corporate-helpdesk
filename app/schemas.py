from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

Role = str
TicketStatus = Literal["new", "in_progress", "waiting", "resolved", "closed", "cancelled"]
TicketPriority = Literal["low", "medium", "high", "critical"]


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class UserLogin(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=50)
    first_name: str | None = Field(default=None, min_length=1, max_length=60)
    last_name: str | None = Field(default=None, min_length=1, max_length=60)
    password: str = Field(min_length=4, max_length=72)
    remember: bool = False

    @model_validator(mode="after")
    def validate_identifier(self) -> "UserLogin":
        has_username = bool(self.username and self.username.strip())
        has_full_name = bool(
            self.first_name
            and self.first_name.strip()
            and self.last_name
            and self.last_name.strip()
        )
        if has_username == has_full_name:
            raise ValueError("Укажите либо логин, либо имя и фамилию")
        return self


class UserCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=4, max_length=72)

    @model_validator(mode="after")
    def validate_names(self) -> "UserCreate":
        if not self.first_name.strip() or not self.last_name.strip():
            raise ValueError("Имя и фамилия не могут быть пустыми")
        return self


class UserAdminCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=4, max_length=72)
    email: EmailStr | None = None
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    role: Role = "user"
    is_active: bool = True
    department_id: int | None = None

    @model_validator(mode="after")
    def validate_names(self) -> "UserAdminCreate":
        if not self.first_name.strip() or not self.last_name.strip():
            raise ValueError("Имя и фамилия не могут быть пустыми")
        return self


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=50)
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=60)
    last_name: str | None = Field(default=None, min_length=1, max_length=60)
    role: Role | None = None
    is_active: bool | None = None
    department_id: int | None = None
    password: str | None = Field(default=None, min_length=4, max_length=72)

    @model_validator(mode="after")
    def validate_names(self) -> "UserUpdate":
        if (self.first_name is None) != (self.last_name is None):
            raise ValueError("Имя и фамилию необходимо передавать вместе")
        if self.first_name is not None and (
            not self.first_name.strip() or not self.last_name or not self.last_name.strip()
        ):
            raise ValueError("Имя и фамилия не могут быть пустыми")
        return self


class UserProfileUpdate(BaseModel):
    email: EmailStr | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=60)
    last_name: str | None = Field(default=None, min_length=1, max_length=60)

    @model_validator(mode="after")
    def validate_names(self) -> "UserProfileUpdate":
        if (self.first_name is None) != (self.last_name is None):
            raise ValueError("Имя и фамилию необходимо передавать вместе")
        if self.first_name is not None and (
            not self.first_name.strip() or not self.last_name or not self.last_name.strip()
        ):
            raise ValueError("Имя и фамилия не могут быть пустыми")
        return self


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=4, max_length=72)
    new_password: str = Field(min_length=4, max_length=72)


class UserRead(BaseModel):
    id: int
    username: str
    email: str | None
    full_name: str | None
    first_name: str | None = None
    last_name: str | None = None
    role: Role
    is_active: bool
    is_archived: bool = False
    must_change_password: bool = False
    department_id: int | None = None
    department_name: str | None = None
    created_at: datetime
    role_name: str | None = None
    permissions: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class PermissionRead(BaseModel):
    code: str
    name: str


class RoleRead(BaseModel):
    code: str
    name: str
    permissions: list[str]
    is_system: bool


class RoleUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    permissions: list[str] = []


class RoleCreate(RoleUpdate):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")


class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5)
    priority: TicketPriority = "medium"
    category_id: int | None = None


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=5)
    priority: TicketPriority | None = None
    assigned_to: int | None = None
    category_id: int | None = None


class TicketRead(BaseModel):
    id: int
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    created_by: int
    assigned_to: int | None
    created_at: datetime
    updated_at: datetime | None
    closed_at: datetime | None
    creator_name: str | None = None
    assignee_name: str | None = None
    due_at: datetime | None = None
    sla_hours: int | None = None
    is_overdue: bool = False
    attachments_count: int = 0
    category_id: int | None = None
    category_name: str | None = None
    closure_reason: str | None = None
    cancelled_at: datetime | None = None
    confirmed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AttachmentRead(BaseModel):
    id: int
    ticket_id: int
    filename: str
    content_type: str | None
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TicketHistoryRead(BaseModel):
    id: int
    ticket_id: int
    user_id: int | None
    user_name: str | None = None
    action: str
    field: str | None
    old_value: str | None
    new_value: str | None
    note: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DayCount(BaseModel):
    day: str
    count: int


class DashboardStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    overdue: int = 0
    by_day: list[DayCount]


class DepartmentBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    manager_id: int | None = None
    is_active: bool = True


class DepartmentRead(DepartmentBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class CategoryBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    default_assignee_id: int | None = None
    sla_hours: int | None = Field(default=None, ge=1, le=8760)
    is_active: bool = True


class CategoryRead(CategoryBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class NotificationRead(BaseModel):
    id: int
    ticket_id: int | None
    title: str
    message: str
    is_read: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AuditLogRead(BaseModel):
    id: int
    user_id: int | None
    user_name: str | None = None
    action: str
    entity_type: str
    entity_id: str | None
    details: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TicketStatusChange(BaseModel):
    status: TicketStatus
    comment: str = Field(min_length=1, max_length=2000)


class BulkTicketUpdate(BaseModel):
    ticket_ids: list[int] = Field(min_length=1, max_length=300)
    priority: TicketPriority | None = None
    assigned_to: int | None = None
    category_id: int | None = None


class BackupRead(BaseModel):
    filename: str
    created_at: datetime | None = None
    size_bytes: int
    database_type: str
    app_version: str | None = None
    git_commit: str | None = None
    runtime_mode: str | None = None
    contents: list[str] = []
    note: str | None = None


class OperationResult(BaseModel):
    message: str


class UpdateStatusRead(BaseModel):
    app_version: str
    current_commit: str | None = None
    current_branch: str | None = None
    runtime_mode: str
    web_update_enabled: bool
    update_available: bool | None = None
    remote_commit: str | None = None
    last_check_at: datetime | None = None
    last_check_status: Literal["idle", "success", "failed"] = "idle"
    last_check_message: str | None = None
    last_update_at: datetime | None = None
    last_update_status: Literal["idle", "running", "success", "failed"] = "idle"
    last_update_message: str | None = None
    last_job_id: str | None = None
    update_log_path: str | None = None


class UpdateJobRead(BaseModel):
    job_id: str
    status: Literal["queued", "running", "success", "failed"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str | None = None
    exit_code: int | None = None


class UpdateLogRead(BaseModel):
    lines: list[str]


class SettingUpdate(BaseModel):
    settings: dict[str, str]


class PasswordReset(BaseModel):
    temporary_password: str = Field(min_length=4, max_length=72)


class UserArchive(BaseModel):
    archived: bool = True
