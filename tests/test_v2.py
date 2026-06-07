import pytest
from httpx import ASGITransport, AsyncClient

from app.database import AsyncSessionLocal
from app.main import app
from app.models import User
from app.security import hash_password


async def client_and_admin() -> tuple[AsyncClient, dict[str, str]]:
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                username="v2admin",
                email="v2admin@example.com",
                full_name="Администратор Версии",
                role="admin",
                hashed_password=hash_password("admin123"),
            )
        )
        await db.commit()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    login = await client.post("/api/users/login", json={"username": "v2admin", "password": "admin123"})
    return client, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def create_regular_user(client: AsyncClient, first_name: str, last_name: str) -> tuple[dict[str, str], dict]:
    created = await client.post(
        "/api/users/register",
        json={"first_name": first_name, "last_name": last_name, "password": "secret123"},
    )
    login = await client.post(
        "/api/users/login",
        json={"first_name": first_name, "last_name": last_name, "password": "secret123"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, created.json()


@pytest.mark.asyncio
async def test_catalogs_auto_assignment_status_decisions_and_notifications():
    client, admin_headers = await client_and_admin()
    try:
        worker = await client.post(
            "/api/users/",
            headers=admin_headers,
            json={
                "username": "worker",
                "first_name": "Сервисный",
                "last_name": "Инженер",
                "password": "worker123",
                "role": "service",
            },
        )
        assert worker.status_code == 201
        category = await client.post(
            "/api/catalogs/categories",
            headers=admin_headers,
            json={"name": "Автоназначение", "default_assignee_id": worker.json()["id"], "sla_hours": 6},
        )
        assert category.status_code == 201

        owner_headers, owner = await create_regular_user(client, "Автор", "Заявки")
        ticket = await client.post(
            "/api/tickets/",
            headers=owner_headers,
            json={
                "title": "Проверка новой версии",
                "description": "Подробное описание проверки новой версии.",
                "priority": "medium",
                "category_id": category.json()["id"],
            },
        )
        assert ticket.status_code == 201
        assert ticket.json()["assigned_to"] == worker.json()["id"]
        assert ticket.json()["sla_hours"] == 6
        ticket_id = ticket.json()["id"]

        missing_comment = await client.post(
            f"/api/tickets/{ticket_id}/status",
            headers=admin_headers,
            json={"status": "resolved"},
        )
        assert missing_comment.status_code == 422

        resolved = await client.post(
            f"/api/tickets/{ticket_id}/status",
            headers=admin_headers,
            json={"status": "resolved", "comment": "Исправлено"},
        )
        assert resolved.json()["status"] == "resolved"
        confirmed = await client.post(
            f"/api/tickets/{ticket_id}/status",
            headers=owner_headers,
            json={"status": "closed", "comment": "Решение подтверждаю"},
        )
        assert confirmed.json()["status"] == "closed"
        assert confirmed.json()["confirmed_at"] is not None

        history = await client.get(f"/api/tickets/{ticket_id}/history", headers=owner_headers)
        status_notes = {item["note"] for item in history.json() if item["action"] == "status_changed"}
        assert status_notes == {"Исправлено", "Решение подтверждаю"}
        for removed_endpoint in ["comments", "checklist", "time", "workflow"]:
            removed = await client.get(f"/api/tickets/{ticket_id}/{removed_endpoint}", headers=admin_headers)
            assert removed.status_code == 404

        notifications = await client.get("/api/notifications/", headers=owner_headers)
        assert notifications.status_code == 200
        assert notifications.json()
        await client.post("/api/notifications/read-all", headers=owner_headers)
        unread = await client.get("/api/notifications/?unread_only=true", headers=owner_headers)
        assert unread.json() == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_bulk_department_audit_archive_and_password_reset():
    client, admin_headers = await client_and_admin()
    try:
        department = await client.post(
            "/api/catalogs/departments",
            headers=admin_headers,
            json={"name": "Продажи"},
        )
        assert department.status_code == 201
        owner_headers, owner = await create_regular_user(client, "Сотрудник", "Продаж")
        await client.patch(
            f"/api/users/{owner['id']}",
            headers=admin_headers,
            json={"department_id": department.json()["id"]},
        )
        ticket_ids = []
        for index in range(2):
            response = await client.post(
                "/api/tickets/",
                headers=owner_headers,
                json={
                    "title": f"Массовая заявка {index}",
                    "description": "Описание для массового обновления.",
                    "priority": "low",
                },
            )
            ticket_ids.append(response.json()["id"])

        bulk = await client.post(
            "/api/tickets/actions/bulk",
            headers=admin_headers,
            json={"ticket_ids": ticket_ids, "priority": "critical"},
        )
        assert bulk.status_code == 200
        assert all(item["priority"] == "critical" for item in bulk.json())

        reset = await client.post(
            f"/api/users/{owner['id']}/reset-password",
            headers=admin_headers,
            json={"temporary_password": "temporary123"},
        )
        assert reset.json()["must_change_password"] is True
        temp_login = await client.post(
            "/api/users/login",
            json={"first_name": "Сотрудник", "last_name": "Продаж", "password": "temporary123"},
        )
        assert temp_login.json()["must_change_password"] is True

        archived = await client.post(
            f"/api/users/{owner['id']}/archive",
            headers=admin_headers,
            json={"archived": True},
        )
        assert archived.json()["is_archived"] is True
        blocked = await client.post(
            "/api/users/login",
            json={"first_name": "Сотрудник", "last_name": "Продаж", "password": "temporary123"},
        )
        assert blocked.status_code == 403

        audit = await client.get("/api/admin/audit", headers=admin_headers)
        assert audit.status_code == 200
        actions = {item["action"] for item in audit.json()}
        assert "tickets.bulk_updated" in actions
        assert "user.password_reset" in actions
        assert "user.archived" in actions

        cannot_delete_related = await client.delete(f"/api/users/{owner['id']}", headers=admin_headers)
        assert cannot_delete_related.status_code == 409

        disposable = await client.post(
            "/api/users/",
            headers=admin_headers,
            json={
                "username": "disposable",
                "first_name": "Временный",
                "last_name": "Пользователь",
                "password": "temporary123",
                "role": "user",
            },
        )
        deleted = await client.delete(f"/api/users/{disposable.json()['id']}", headers=admin_headers)
        assert deleted.status_code == 204
    finally:
        await client.aclose()
