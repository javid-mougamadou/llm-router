"""Tests for admin endpoints: login, users, keys, budget."""

import os
import asyncio
import pytest
from fastapi.testclient import TestClient

# Init DB before importing app
from app.db import init_db, close_db
asyncio.get_event_loop().run_until_complete(init_db())

from main import app

MASTER = "sk-test-master"
HEADERS = {"x-api-key": MASTER, "content-type": "application/json"}


@pytest.fixture(autouse=True)
def reset_db():
    """Reset DB before each test."""
    db_path = os.environ["LLM_ROUTER_DB"]
    asyncio.get_event_loop().run_until_complete(close_db())
    if os.path.exists(db_path):
        os.remove(db_path)
    asyncio.get_event_loop().run_until_complete(init_db())
    yield
    asyncio.get_event_loop().run_until_complete(close_db())
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_success(client):
    r = client.post("/admin/login", json={
        "username": "testadmin", "password": "testpass"
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["master_key"] == MASTER


def test_login_failure(client):
    r = client.post("/admin/login", json={
        "username": "wrong", "password": "wrong"
    })
    assert r.status_code == 401


def test_create_user(client):
    r = client.post("/admin/users", headers=HEADERS, json={
        "name": "alice", "monthly_budget": 10.0, "daily_budget": 1.0
    })
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "alice"
    assert data["monthly_budget"] == 10.0
    assert data["daily_budget"] == 1.0
    assert data["api_key"].startswith("sk-")


def test_list_users(client):
    client.post("/admin/users", headers=HEADERS, json={
        "name": "bob", "monthly_budget": 5.0
    })
    r = client.get("/admin/users", headers=HEADERS)
    assert r.status_code == 200
    users = r.json()
    assert len(users) == 1
    assert users[0]["name"] == "bob"
    assert users[0]["daily_budget"] == 0


def test_update_budget(client):
    cr = client.post("/admin/users", headers=HEADERS, json={
        "name": "carol", "monthly_budget": 5.0
    })
    uid = cr.json()["id"]

    r = client.patch(f"/admin/users/{uid}", headers=HEADERS, json={
        "monthly_budget": 20.0, "daily_budget": 2.5
    })
    assert r.status_code == 200

    users = client.get("/admin/users", headers=HEADERS).json()
    carol = [u for u in users if u["name"] == "carol"][0]
    assert carol["monthly_budget"] == 20.0
    assert carol["daily_budget"] == 2.5


def test_toggle_user(client):
    cr = client.post("/admin/users", headers=HEADERS, json={
        "name": "dave", "monthly_budget": 1.0
    })
    uid = cr.json()["id"]

    # Disable
    client.patch(f"/admin/users/{uid}", headers=HEADERS, json={"active": False})
    users = client.get("/admin/users", headers=HEADERS).json()
    dave = [u for u in users if u["name"] == "dave"][0]
    assert dave["active"] == 0

    # Re-enable
    client.patch(f"/admin/users/{uid}", headers=HEADERS, json={"active": True})
    users = client.get("/admin/users", headers=HEADERS).json()
    dave = [u for u in users if u["name"] == "dave"][0]
    assert dave["active"] == 1


def test_create_and_list_keys(client):
    cr = client.post("/admin/users", headers=HEADERS, json={
        "name": "eve", "monthly_budget": 1.0
    })
    uid = cr.json()["id"]

    r = client.get(f"/admin/users/{uid}/keys", headers=HEADERS)
    keys = r.json()
    assert len(keys) == 1
    assert keys[0]["label"] == "default"

    r2 = client.post(f"/admin/users/{uid}/keys", headers=HEADERS, json={
        "label": "ci-key"
    })
    assert r2.json()["label"] == "ci-key"

    keys2 = client.get(f"/admin/users/{uid}/keys", headers=HEADERS).json()
    assert len(keys2) == 2


def test_reset_spend(client):
    cr = client.post("/admin/users", headers=HEADERS, json={
        "name": "frank", "monthly_budget": 10.0
    })
    uid = cr.json()["id"]

    # Manually set spend via DB
    async def set_spend():
        from app.db import get_db
        db = await get_db()
        await db.execute(
            "UPDATE users SET monthly_spend = 5.0, "
            "daily_spend = 1.0 WHERE id = ?",
            (uid,),
        )
        await db.commit()

    asyncio.get_event_loop().run_until_complete(set_spend())

    client.patch(f"/admin/users/{uid}", headers=HEADERS, json={"reset_spend": True})
    users = client.get("/admin/users", headers=HEADERS).json()
    frank = [u for u in users if u["name"] == "frank"][0]
    assert frank["monthly_spend"] == 0

    client.patch(f"/admin/users/{uid}", headers=HEADERS, json={"reset_daily_spend": True})
    users = client.get("/admin/users", headers=HEADERS).json()
    frank = [u for u in users if u["name"] == "frank"][0]
    assert frank["daily_spend"] == 0


def test_admin_requires_auth(client):
    r = client.get("/admin/users")
    assert r.status_code == 403


def test_usage_empty(client):
    r = client.get("/admin/usage", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == []


def test_daily_history_empty(client):
    r = client.get("/admin/daily-history", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == []


def test_daily_history_after_reset(client):
    """Daily spend is archived when a new day triggers reset."""
    cr = client.post("/admin/users", headers=HEADERS, json={
        "name": "hana", "daily_budget": 5.0,
    })
    uid = cr.json()["id"]

    # Simulate yesterday's spend still in the DB
    async def set_yesterday():
        from app.db import get_db
        db = await get_db()
        await db.execute(
            "UPDATE users SET daily_spend = 2.5, "
            "daily_reset_at = '2026-03-31' WHERE id = ?",
            (uid,),
        )
        await db.commit()

    asyncio.get_event_loop().run_until_complete(set_yesterday())

    # Trigger refresh via list_users
    client.get("/admin/users", headers=HEADERS)

    # Check daily history
    r = client.get("/admin/daily-history", headers=HEADERS)
    history = r.json()
    assert len(history) == 1
    assert history[0]["day"] == "2026-03-31"
    assert history[0]["name"] == "hana"
    assert history[0]["spend"] == 2.5
    assert history[0]["budget"] == 5.0


def test_monthly_history_aggregates_daily(client):
    """Monthly history aggregates from daily_budget_history."""
    cr = client.post("/admin/users", headers=HEADERS, json={
        "name": "ivan", "daily_budget": 10.0,
    })
    uid = cr.json()["id"]

    # Insert two daily entries for same month
    async def insert_daily():
        from app.db import get_db
        db = await get_db()
        await db.execute(
            "INSERT INTO daily_budget_history "
            "(user_id, day, budget, spend) "
            "VALUES (?, '2026-03-01', 10, 3.0)",
            (uid,),
        )
        await db.execute(
            "INSERT INTO daily_budget_history "
            "(user_id, day, budget, spend) "
            "VALUES (?, '2026-03-02', 10, 4.5)",
            (uid,),
        )
        await db.commit()

    asyncio.get_event_loop().run_until_complete(insert_daily())

    r = client.get("/admin/monthly-history", headers=HEADERS)
    history = r.json()
    assert len(history) == 1
    assert history[0]["month"] == "2026-03"
    assert history[0]["name"] == "ivan"
    assert history[0]["spend"] == 7.5
