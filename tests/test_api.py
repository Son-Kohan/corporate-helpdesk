import pytest
from httpx import ASGITransport, AsyncClient

from app.database import AsyncSessionLocal
from app.main import app
from app.models import User
from app.security import hash_password


async def authorized_client() -> tuple[AsyncClient, dict[str, str]]:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    await client.post(
        "/api/users/register",
        json={
            "first_name": "Иван",
            "last_name": "Петров",
            "password": "secret123",
        },
    )
    response = await client.post(
        "/api/users/login",
        json={"first_name": "Иван", "last_name": "Петров", "password": "secret123"},
    )
    token = response.json()["access_token"]
    return client, {"Authorization": f"Bearer {token}"}


async def admin_client() -> tuple[AsyncClient, dict[str, str]]:
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                username="admin",
                email="admin@example.com",
                full_name="Администратор",
                role="admin",
                hashed_password=hash_password("admin123"),
            )
        )
        await db.commit()

    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    response = await client.post(
        "/api/users/login",
        json={"username": "admin", "password": "admin123"},
    )
    token = response.json()["access_token"]
    return client, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_user_can_create_ticket_and_read_history():
    client, headers = await authorized_client()
    try:
        me_response = await client.get("/api/users/me", headers=headers)
        assert me_response.status_code == 200
        assert me_response.json()["full_name"] == "Иван Петров"
        assert "reports.view" not in me_response.json()["permissions"]

        report_response = await client.get("/api/reports/dashboard", headers=headers)
        assert report_response.status_code == 403

        ticket_response = await client.post(
            "/api/tickets/",
            json={
                "title": "Не работает принтер",
                "description": "Принтер в отделе продаж не печатает документы.",
                "priority": "high",
            },
            headers=headers,
        )
        assert ticket_response.status_code == 201
        ticket_id = ticket_response.json()["id"]

        list_response = await client.get("/api/tickets/", headers=headers)
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1

        history_response = await client.get(f"/api/tickets/{ticket_id}/history", headers=headers)
        assert history_response.status_code == 200
        assert any(item["action"] == "created" for item in history_response.json())

        removed_comments = await client.get(f"/api/tickets/{ticket_id}/comments", headers=headers)
        assert removed_comments.status_code == 404
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_user_cannot_read_foreign_ticket():
    client, headers = await authorized_client()
    try:
        await client.post(
            "/api/users/register",
            json={
                "first_name": "Ольга",
                "last_name": "Соколова",
                "password": "secret123",
            },
        )
        login_response = await client.post(
            "/api/users/login",
            json={"first_name": "Ольга", "last_name": "Соколова", "password": "secret123"},
        )
        olga_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        ticket_response = await client.post(
            "/api/tickets/",
            json={
                "title": "Настроить почту",
                "description": "Нужен доступ к корпоративной почте.",
                "priority": "medium",
            },
            headers=headers,
        )
        ticket_id = ticket_response.json()["id"]

        forbidden = await client.get(f"/api/tickets/{ticket_id}", headers=olga_headers)
        assert forbidden.status_code == 403

        olga_tickets = await client.get("/api/tickets/", headers=olga_headers)
        assert olga_tickets.status_code == 200
        assert olga_tickets.json() == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_attachments_and_export_are_available():
    client, headers = await authorized_client()
    try:
        ticket_response = await client.post(
            "/api/tickets/",
            json={
                "title": "Нужен скриншот ошибки",
                "description": "К заявке прикладывается диагностический файл.",
                "priority": "low",
            },
            headers=headers,
        )
        ticket_id = ticket_response.json()["id"]

        upload_response = await client.post(
            f"/api/tickets/{ticket_id}/attachments",
            files={"file": ("error.txt", b"traceback", "text/plain")},
            headers=headers,
        )
        assert upload_response.status_code == 201
        attachment_id = upload_response.json()["id"]

        list_response = await client.get(f"/api/tickets/{ticket_id}/attachments", headers=headers)
        assert list_response.status_code == 200
        assert list_response.json()[0]["filename"] == "error.txt"

        download_response = await client.get(f"/api/tickets/attachments/{attachment_id}", headers=headers)
        assert download_response.status_code == 200
        assert download_response.content == b"traceback"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_admin_can_create_service_user_and_export_csv():
    client, headers = await admin_client()
    try:
        create_response = await client.post(
            "/api/users/",
            json={
                "username": "service1",
                "first_name": "Сервисный",
                "last_name": "сотрудник",
                "password": "service123",
                "role": "service",
                "is_active": True,
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        assert create_response.json()["role"] == "service"
        assert create_response.json()["email"] is None
        assert create_response.json()["first_name"] == "Сервисный"
        assert create_response.json()["last_name"] == "сотрудник"

        update_response = await client.patch(
            f"/api/users/{create_response.json()['id']}",
            json={
                "username": "service2",
                "first_name": "Иван",
                "last_name": "Сервисный",
                "email": "service@example.com",
            },
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["username"] == "service2"
        assert update_response.json()["full_name"] == "Иван Сервисный"
        assert update_response.json()["email"] == "service@example.com"

        updated_login = await client.post(
            "/api/users/login",
            json={"username": "service2", "password": "service123"},
        )
        assert updated_login.status_code == 200

        export_response = await client.get("/api/reports/export.csv", headers=headers)
        assert export_response.status_code == 200
        assert "ID;Тема;Статус" in export_response.text
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_registration_without_email_supports_cyrillic_credentials():
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        register_response = await client.post(
            "/api/users/register",
            json={
                "first_name": "Иван",
                "last_name": "Кохан",
                "password": "пароль123",
            },
        )
        assert register_response.status_code == 201
        assert register_response.json()["email"] is None

        login_response = await client.post(
            "/api/users/login",
            json={"first_name": "Иван", "last_name": "Кохан", "password": "пароль123"},
        )
        assert login_response.status_code == 200

        generated_username = register_response.json()["username"]
        legacy_login_response = await client.post(
            "/api/users/login",
            json={"username": generated_username, "password": "пароль123"},
        )
        assert legacy_login_response.status_code == 200
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_admin_can_rename_role_and_update_permissions():
    client, headers = await admin_client()
    try:
        permissions_response = await client.get("/api/roles/permissions", headers=headers)
        assert permissions_response.status_code == 200
        permission_codes = {item["code"] for item in permissions_response.json()}
        assert "tickets.create" in permission_codes

        update_response = await client.put(
            "/api/roles/user",
            json={"name": "Clients", "permissions": ["tickets.create", "tickets.read_own"]},
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Clients"
        assert update_response.json()["permissions"] == ["tickets.create", "tickets.read_own"]

        roles_response = await client.get("/api/roles/", headers=headers)
        assert roles_response.status_code == 200
        user_role = next(role for role in roles_response.json() if role["code"] == "user")
        assert user_role["name"] == "Clients"
    finally:
        await client.aclose()
