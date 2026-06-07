import json
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Role, User
from app.permissions import ALL_PERMISSIONS
from app.security import hash_password
from app.websocket import ConnectionManager, authenticate_websocket


class FakeWebSocket:
    def __init__(self, token: str | None = None):
        self.query_params = {"token": token} if token else {}
        self.close_code: int | None = None

    async def close(self, code: int) -> None:
        self.close_code = code


class StaleWebSocket:
    async def send_json(self, message: dict) -> None:
        raise RuntimeError("connection closed")


async def make_client() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def register_and_login(
    client: AsyncClient,
    full_name: str,
    password: str = "secret123",
    remember: bool = False,
) -> tuple[dict[str, str], dict]:
    first_name, last_name = full_name.split(" ", 1)
    registered = await client.post(
        "/api/users/register",
        json={"first_name": first_name, "last_name": last_name, "password": password},
    )
    assert registered.status_code == 201
    login = await client.post(
        "/api/users/login",
        json={
            "first_name": first_name,
            "last_name": last_name,
            "password": password,
            "remember": remember,
        },
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, registered.json()


async def create_admin(client: AsyncClient) -> tuple[dict[str, str], User]:
    async with AsyncSessionLocal() as db:
        admin = User(
            username="system_admin",
            email="system_admin@example.com",
            full_name="Системный Администратор",
            role="admin",
            hashed_password=hash_password("admin123"),
        )
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
    login = await client.post(
        "/api/users/login",
        json={"username": "system_admin", "password": "admin123"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, admin


async def create_ticket(client: AsyncClient, headers: dict[str, str], title: str = "Тестовая заявка") -> dict:
    response = await client.post(
        "/api/tickets/",
        json={
            "title": title,
            "description": "Подробное описание тестовой заявки.",
            "priority": "medium",
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_auth_validation_duplicate_names_and_session_lifetime():
    client = await make_client()
    try:
        short_password = await client.post(
            "/api/users/register",
            json={"first_name": "Короткий", "last_name": "Пароль", "password": "123"},
        )
        assert short_password.status_code == 422

        missing_last_name = await client.post(
            "/api/users/register",
            json={"first_name": "Безфамильный", "password": "secret123"},
        )
        assert missing_last_name.status_code == 422

        headers, registered = await register_and_login(client, "Сергей Иванов")
        assert registered["username"].startswith("user_")
        assert registered["email"] is None

        duplicate = await client.post(
            "/api/users/register",
            json={"first_name": "Сергей", "last_name": "Иванов", "password": "different123"},
        )
        assert duplicate.status_code == 400

        wrong_password = await client.post(
            "/api/users/login",
            json={"first_name": "Сергей", "last_name": "Иванов", "password": "wrong-password"},
        )
        assert wrong_password.status_code == 401

        ambiguous_login = await client.post(
            "/api/users/login",
            json={
                "username": registered["username"],
                "first_name": "Сергей",
                "last_name": "Иванов",
                "password": "secret123",
            },
        )
        assert ambiguous_login.status_code == 422

        regular_login = await client.post(
            "/api/users/login",
            json={
                "first_name": "Сергей",
                "last_name": "Иванов",
                "password": "secret123",
                "remember": False,
            },
        )
        remembered_login = await client.post(
            "/api/users/login",
            json={"username": registered["username"], "password": "secret123", "remember": True},
        )
        settings = get_settings()
        regular_payload = jwt.decode(
            regular_login.json()["access_token"],
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        remembered_payload = jwt.decode(
            remembered_login.json()["access_token"],
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        assert remembered_payload["exp"] - regular_payload["exp"] > 20 * 24 * 60 * 60

        me = await client.get("/api/users/me", headers=headers)
        assert me.status_code == 200
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_inactive_user_and_invalid_tokens_are_rejected():
    client = await make_client()
    try:
        headers, registered = await register_and_login(client, "Отключенный Пользователь")
        invalid = await client.get("/api/users/me", headers={"Authorization": "Bearer invalid-token"})
        assert invalid.status_code == 401

        missing = await client.get("/api/users/me")
        assert missing.status_code == 401

        async with AsyncSessionLocal() as db:
            user = await db.get(User, registered["id"])
            user.is_active = False
            await db.commit()

        inactive = await client.get("/api/users/me", headers=headers)
        assert inactive.status_code == 401

        inactive_login = await client.post(
            "/api/users/login",
            json={"first_name": "Отключенный", "last_name": "Пользователь", "password": "secret123"},
        )
        assert inactive_login.status_code == 403
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_ticket_ownership_update_restrictions_and_foreign_resources():
    client = await make_client()
    try:
        owner_headers, _ = await register_and_login(client, "Автор Заявки")
        stranger_headers, _ = await register_and_login(client, "Чужой Пользователь")
        ticket = await create_ticket(client, owner_headers)

        owner_update = await client.put(
            f"/api/tickets/{ticket['id']}",
            json={
                "title": "Измененная тема",
                "status": "closed",
                "assigned_to": 999,
            },
            headers=owner_headers,
        )
        assert owner_update.status_code == 200
        assert owner_update.json()["title"] == "Измененная тема"
        assert owner_update.json()["status"] == "new"
        assert owner_update.json()["assigned_to"] is None

        for endpoint in [
            f"/api/tickets/{ticket['id']}",
            f"/api/tickets/{ticket['id']}/attachments",
            f"/api/tickets/{ticket['id']}/history",
        ]:
            response = await client.get(endpoint, headers=stranger_headers)
            assert response.status_code == 403

        foreign_status_change = await client.post(
            f"/api/tickets/{ticket['id']}/status",
            json={"status": "cancelled", "comment": "Чужое решение"},
            headers=stranger_headers,
        )
        assert foreign_status_change.status_code == 403

        foreign_upload = await client.post(
            f"/api/tickets/{ticket['id']}/attachments",
            files={"file": ("foreign.txt", b"no access", "text/plain")},
            headers=stranger_headers,
        )
        assert foreign_upload.status_code == 403

        oversized_upload = await client.post(
            f"/api/tickets/{ticket['id']}/attachments",
            files={"file": ("large.bin", b"x" * 1025, "application/octet-stream")},
            headers=owner_headers,
        )
        assert oversized_upload.status_code == 413
        attachments = await client.get(f"/api/tickets/{ticket['id']}/attachments", headers=owner_headers)
        assert attachments.json() == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_websocket_authentication_and_ticket_access():
    client = await make_client()
    try:
        owner_headers, _ = await register_and_login(client, "Владелец Сокета")
        stranger_headers, _ = await register_and_login(client, "Чужой Сокет")
        ticket = await create_ticket(client, owner_headers)
        owner_token = owner_headers["Authorization"].removeprefix("Bearer ")
        stranger_token = stranger_headers["Authorization"].removeprefix("Bearer ")

        anonymous_socket = FakeWebSocket()
        assert await authenticate_websocket(anonymous_socket, "all") is None
        assert anonymous_socket.close_code == 1008

        owner_all_socket = FakeWebSocket(owner_token)
        assert (await authenticate_websocket(owner_all_socket, "all")).full_name == "Владелец Сокета"
        assert owner_all_socket.close_code is None

        owner_ticket_socket = FakeWebSocket(owner_token)
        assert (await authenticate_websocket(owner_ticket_socket, str(ticket["id"]))).id == ticket["created_by"]

        stranger_ticket_socket = FakeWebSocket(stranger_token)
        assert await authenticate_websocket(stranger_ticket_socket, str(ticket["id"])) is None
        assert stranger_ticket_socket.close_code == 1008
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_stale_websocket_is_removed_from_all_channels():
    manager = ConnectionManager()
    socket = StaleWebSocket()
    manager.active_connections["all"].add(socket)
    manager.active_connections["42"].add(socket)
    await manager.broadcast("42", {"type": "test"})
    assert manager.active_connections == {}


@pytest.mark.asyncio
async def test_service_assignment_status_history_and_delete_workflow():
    client = await make_client()
    try:
        owner_headers, _ = await register_and_login(client, "Клиент Сервиса")
        admin_headers, _ = await create_admin(client)
        service_response = await client.post(
            "/api/users/",
            json={
                "username": "service_worker",
                "first_name": "Сервисный",
                "last_name": "Работник",
                "password": "service123",
                "role": "service",
                "is_active": True,
            },
            headers=admin_headers,
        )
        assert service_response.status_code == 201
        service_id = service_response.json()["id"]
        service_login = await client.post(
            "/api/users/login",
            json={"first_name": "Сервисный", "last_name": "Работник", "password": "service123"},
        )
        service_headers = {"Authorization": f"Bearer {service_login.json()['access_token']}"}

        ticket = await create_ticket(client, owner_headers, "Полный жизненный цикл")
        assigned = await client.put(
            f"/api/tickets/{ticket['id']}",
            json={"assigned_to": service_id, "priority": "critical"},
            headers=service_headers,
        )
        assert assigned.status_code == 200
        assert assigned.json()["assigned_to"] == service_id
        assert assigned.json()["status"] == "new"

        in_progress = await client.post(
            f"/api/tickets/{ticket['id']}/status",
            json={"status": "in_progress", "comment": "Принято в работу"},
            headers=service_headers,
        )
        assert in_progress.status_code == 200
        assert in_progress.json()["status"] == "in_progress"

        assigned_list = await client.get("/api/tickets/?scope=assigned", headers=service_headers)
        assert assigned_list.status_code == 200
        assert [item["id"] for item in assigned_list.json()] == [ticket["id"]]

        closed = await client.post(
            f"/api/tickets/{ticket['id']}/status",
            json={"status": "closed", "comment": "Работа выполнена"},
            headers=service_headers,
        )
        assert closed.status_code == 200
        assert closed.json()["closed_at"] is not None

        history = await client.get(f"/api/tickets/{ticket['id']}/history", headers=service_headers)
        fields = {item["field"] for item in history.json() if item["action"] == "updated"}
        assert {"assigned_to", "priority"}.issubset(fields)
        status_events = [item for item in history.json() if item["action"] == "status_changed"]
        assert {item["note"] for item in status_events} == {"Работа выполнена", "Принято в работу"}

        deleted = await client.delete(f"/api/tickets/{ticket['id']}", headers=service_headers)
        assert deleted.status_code == 204
        missing = await client.get(f"/api/tickets/{ticket['id']}", headers=owner_headers)
        assert missing.status_code == 404
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_role_permission_changes_apply_immediately():
    client = await make_client()
    try:
        admin_headers, _ = await create_admin(client)
        role = await client.post(
            "/api/roles/",
            json={"code": "auditor", "name": "Аудитор", "permissions": ["tickets.read_all"]},
            headers=admin_headers,
        )
        assert role.status_code == 201

        auditor = await client.post(
            "/api/users/",
            json={
                "username": "auditor1",
                "first_name": "Первый",
                "last_name": "Аудитор",
                "password": "auditor123",
                "role": "auditor",
                "is_active": True,
            },
            headers=admin_headers,
        )
        assert auditor.status_code == 201
        auditor_login = await client.post(
            "/api/users/login",
            json={"first_name": "Первый", "last_name": "Аудитор", "password": "auditor123"},
        )
        auditor_headers = {"Authorization": f"Bearer {auditor_login.json()['access_token']}"}

        denied_create = await client.post(
            "/api/tickets/",
            json={"title": "Запрещено", "description": "Создавать пока нельзя.", "priority": "low"},
            headers=auditor_headers,
        )
        assert denied_create.status_code == 403

        updated_role = await client.put(
            "/api/roles/auditor",
            json={"name": "Аудитор", "permissions": ["tickets.read_all", "tickets.create"]},
            headers=admin_headers,
        )
        assert updated_role.status_code == 200
        allowed_create = await client.post(
            "/api/tickets/",
            json={"title": "Разрешено", "description": "Право уже применяется.", "priority": "low"},
            headers=auditor_headers,
        )
        assert allowed_create.status_code == 201

        unknown_permission = await client.put(
            "/api/roles/auditor",
            json={"name": "Аудитор", "permissions": ["unknown.permission"]},
            headers=admin_headers,
        )
        assert unknown_permission.status_code == 400
        assert set(ALL_PERMISSIONS) >= set(updated_role.json()["permissions"])
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_reports_filters_pagination_and_bulk_ticket_load():
    client = await make_client()
    try:
        admin_headers, _ = await create_admin(client)
        owner_headers, _ = await register_and_login(client, "Нагрузочный Пользователь")

        for index in range(35):
            response = await client.post(
                "/api/tickets/",
                json={
                    "title": f"Нагрузка {index:02d}",
                    "description": f"Описание нагрузочной заявки номер {index}.",
                    "priority": "high" if index % 2 else "low",
                },
                headers=owner_headers,
            )
            assert response.status_code == 201

        first_page = await client.get(
            "/api/tickets/?scope=mine&limit=20&skip=0&sort_by=title&sort_dir=asc",
            headers=owner_headers,
        )
        second_page = await client.get(
            "/api/tickets/?scope=mine&limit=20&skip=20&sort_by=title&sort_dir=asc",
            headers=owner_headers,
        )
        assert len(first_page.json()) == 20
        assert len(second_page.json()) == 15
        assert first_page.json()[0]["title"] == "Нагрузка 00"

        high_filter = await client.get(
            "/api/tickets/?scope=mine&priority=high&q=Нагрузка",
            headers=owner_headers,
        )
        assert len(high_filter.json()) == 17

        dashboard = await client.get("/api/reports/dashboard", headers=admin_headers)
        assert dashboard.status_code == 200
        assert dashboard.json()["total"] == 35
        assert dashboard.json()["by_priority"]["high"] == 17
        assert len(dashboard.json()["by_day"]) == 7

        export = await client.get("/api/reports/export.csv", headers=admin_headers)
        assert export.status_code == 200
        assert export.content.startswith(b"\xef\xbb\xbf")
        assert export.text.count("\n") >= 35
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_static_assets_health_and_cache_headers():
    client = await make_client()
    try:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        for path in ["/", "/static/js/app.js", "/static/js/api.js", "/static/css/styles.css"]:
            response = await client.get(path)
            assert response.status_code == 200
            assert "no-store" in response.headers["cache-control"]
    finally:
        await client.aclose()
