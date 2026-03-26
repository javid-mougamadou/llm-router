"""Admin endpoints: manage users, API keys, usage, monthly history, login."""

import hmac
import secrets
import boto3
from fastapi import APIRouter, Request, HTTPException
from app.db import get_db, hash_password, DEFAULT_PASSWORD
from app.config import (
    MASTER_KEY, ADMIN_USER, ADMIN_PASSWORD, AWS_REGION, AWS_PROFILE,
)

router = APIRouter(prefix="/admin")


def _require_admin(request: Request):
    key = (
        request.headers.get("x-api-key")
        or request.headers.get("authorization", "")
        .removeprefix("Bearer ").strip()
    )
    if not key or not hmac.compare_digest(key, MASTER_KEY):
        raise HTTPException(403, "Admin access required")


# -- Login --

@router.post("/login")
async def login(request: Request):
    body = await request.json()
    user = body.get("username", "")
    pwd = body.get("password", "")
    if hmac.compare_digest(user, ADMIN_USER) and hmac.compare_digest(pwd, ADMIN_PASSWORD):
        return {"ok": True, "master_key": MASTER_KEY}
    raise HTTPException(401, "Invalid credentials")


# -- AWS credentials check --

@router.get("/aws-status")
async def aws_status(request: Request):
    _require_admin(request)
    try:
        session = boto3.Session(
            profile_name=AWS_PROFILE, region_name=AWS_REGION,
        )
        sts = session.client("sts", region_name=AWS_REGION)
        identity = sts.get_caller_identity()
        return {
            "ok": True,
            "account": identity.get("Account", ""),
            "arn": identity.get("Arn", ""),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# -- Users --

@router.get("/users")
async def list_users(request: Request):
    _require_admin(request)
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, name, monthly_budget, monthly_spend, "
        "monthly_reset_at, daily_budget, daily_spend, "
        "daily_reset_at, active, created_at FROM users"
    )
    return [dict(r) for r in rows]


@router.post("/users")
async def create_user(request: Request):
    _require_admin(request)
    body = await request.json()
    name = body.get("name")
    monthly_budget = body.get("monthly_budget", 0)
    daily_budget = body.get("daily_budget", 0)
    if not name:
        raise HTTPException(400, "name is required")

    api_key = f"sk-{secrets.token_hex(16)}"
    pwd_hash = hash_password(DEFAULT_PASSWORD)
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO users (name, monthly_budget, daily_budget, password_hash) "
        "VALUES (?, ?, ?, ?)",
        (name, monthly_budget, daily_budget, pwd_hash),
    )
    user_id = cursor.lastrowid
    await db.execute(
        "INSERT INTO api_keys (key, user_id, label) "
        "VALUES (?, ?, ?)",
        (api_key, user_id, "default"),
    )
    await db.commit()

    return {
        "id": user_id, "name": name,
        "monthly_budget": monthly_budget,
        "daily_budget": daily_budget, "api_key": api_key,
    }


@router.patch("/users/{user_id}")
async def update_user(user_id: int, request: Request):
    _require_admin(request)
    body = await request.json()
    db = await get_db()
    sets, vals = [], []
    if "monthly_budget" in body:
        sets.append("monthly_budget = ?")
        vals.append(body["monthly_budget"])
    if "max_budget" in body and "monthly_budget" not in body:
        sets.append("monthly_budget = ?")
        vals.append(body["max_budget"])
    if "daily_budget" in body:
        sets.append("daily_budget = ?")
        vals.append(body["daily_budget"])
    if "active" in body:
        sets.append("active = ?")
        vals.append(1 if body["active"] else 0)
    if body.get("reset_spend"):
        sets.append("monthly_spend = 0")
    if body.get("reset_daily_spend"):
        sets.append("daily_spend = 0")
    if not sets:
        raise HTTPException(400, "Nothing to update")
    vals.append(user_id)
    await db.execute(
        f"UPDATE users SET {', '.join(sets)} WHERE id = ?", vals,
    )
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    _require_admin(request)
    db = await get_db()
    await db.execute(
        "DELETE FROM monthly_budget_history WHERE user_id = ?", (user_id,),
    )
    await db.execute("DELETE FROM usage_log WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    await db.commit()
    return {"ok": True}


# -- API Keys --

@router.get("/users/{user_id}/keys")
async def list_keys(user_id: int, request: Request):
    _require_admin(request)
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT key, label, active, created_at "
        "FROM api_keys WHERE user_id = ?",
        (user_id,),
    )
    return [dict(r) for r in rows]


@router.post("/users/{user_id}/keys")
async def create_key(user_id: int, request: Request):
    _require_admin(request)
    body = await request.json()
    label = body.get("label", "")
    api_key = f"sk-{secrets.token_hex(16)}"
    db = await get_db()
    await db.execute(
        "INSERT INTO api_keys (key, user_id, label) VALUES (?, ?, ?)",
        (api_key, user_id, label),
    )
    await db.commit()
    return {"key": api_key, "label": label}


@router.patch("/keys/{key_id}")
async def toggle_key(key_id: str, request: Request):
    _require_admin(request)
    body = await request.json()
    active = 1 if body.get("active") else 0
    db = await get_db()
    cursor = await db.execute(
        "UPDATE api_keys SET active = ? WHERE key = ?", (active, key_id),
    )
    if cursor.rowcount == 0:
        raise HTTPException(404, "Key not found")
    await db.commit()
    return {"ok": True}


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str, request: Request):
    _require_admin(request)
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM api_keys WHERE key = ?", (key_id,),
    )
    if cursor.rowcount == 0:
        raise HTTPException(404, "Key not found")
    await db.commit()
    return {"ok": True}


# -- Usage --

@router.get("/usage")
async def usage_summary(request: Request):
    _require_admin(request)
    db = await get_db()
    rows = await db.execute_fetchall("""
        SELECT u.name, l.model,
               SUM(l.input_tokens) as total_input,
               SUM(l.output_tokens) as total_output,
               SUM(l.cost) as total_cost,
               COUNT(*) as requests
        FROM usage_log l JOIN users u ON l.user_id = u.id
        GROUP BY u.name, l.model
        ORDER BY total_cost DESC
    """)
    return [dict(r) for r in rows]


# -- Monthly Budget History --

@router.get("/monthly-history")
async def monthly_history(request: Request):
    _require_admin(request)
    db = await get_db()
    rows = await db.execute_fetchall("""
        SELECT h.month, u.name, h.budget, h.spend
        FROM monthly_budget_history h
        JOIN users u ON h.user_id = u.id
        ORDER BY h.month DESC, u.name
    """)
    return [dict(r) for r in rows]
