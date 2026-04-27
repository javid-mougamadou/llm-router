"""Tests for auth: API key validation, budget enforcement."""

import os
import asyncio
import pytest
from datetime import date
from fastapi.testclient import TestClient

from app.db import init_db, close_db
from main import app

MASTER = "sk-test-master"
HEADERS = {"x-api-key": MASTER, "content-type": "application/json"}


@pytest.fixture(autouse=True)
def reset_db():
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


def _create_user(client, name="authuser", monthly_budget=1.0, daily_budget=0.5):
    r = client.post("/admin/users", headers=HEADERS, json={
        "name": name, "monthly_budget": monthly_budget, "daily_budget": daily_budget
    })
    data = r.json()
    return data["id"], data["api_key"]


def test_invalid_key_rejected(client):
    r = client.get("/v1/models", headers={"x-api-key": "sk-invalid"})
    assert r.status_code == 401


def test_missing_key_rejected(client):
    r = client.get("/v1/models")
    assert r.status_code == 401


def test_valid_key_works(client):
    _, api_key = _create_user(client)
    r = client.get("/v1/models", headers={"x-api-key": api_key})
    assert r.status_code == 200


def test_disabled_user_rejected(client):
    uid, api_key = _create_user(client)
    client.patch(f"/admin/users/{uid}", headers=HEADERS, json={"active": False})
    r = client.get("/v1/models", headers={"x-api-key": api_key})
    assert r.status_code == 401


def test_monthly_budget_enforcement(client):
    uid, api_key = _create_user(client)

    async def set_spend():
        from app.db import get_db
        from app.auth import _current_month
        db = await get_db()
        await db.execute(
            "UPDATE users SET monthly_spend = 1.5, "
            "monthly_reset_at = ? WHERE id = ?",
            (_current_month(), uid),
        )
        await db.commit()

    asyncio.get_event_loop().run_until_complete(set_spend())

    r = client.get("/v1/models", headers={"x-api-key": api_key})
    assert r.status_code == 429
    assert "Monthly budget exceeded" in r.text


def test_daily_budget_enforcement(client):
    uid, api_key = _create_user(client)

    async def set_daily():
        from app.db import get_db
        today = date.today().isoformat()
        db = await get_db()
        await db.execute(
            "UPDATE users SET daily_spend = 0.60, "
            "daily_reset_at = ? WHERE id = ?",
            (today, uid),
        )
        await db.commit()

    asyncio.get_event_loop().run_until_complete(set_daily())

    r = client.get("/v1/models", headers={"x-api-key": api_key})
    assert r.status_code == 429
    assert "Daily budget exceeded" in r.text


def test_master_key_bypasses_budget(client):
    r = client.get("/v1/models", headers={"x-api-key": MASTER})
    assert r.status_code == 200
