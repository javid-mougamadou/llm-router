"""User endpoints: login, dashboard data (consumption, keys, usage)."""

from datetime import date
from fastapi import APIRouter, Request, HTTPException
from app.db import get_db, hash_password, verify_password
from app.jwt_utils import create_token, verify_token
from app.auth import refresh_user_budgets

router = APIRouter(prefix="/user")


def _current_month() -> str:
    return date.today().strftime("%Y-%m")


async def _require_user(request: Request) -> dict:
    """Validate JWT from x-user-token or Authorization header."""
    token = (
        request.headers.get("x-user-token")
        or request.headers.get("authorization", "")
        .removeprefix("Bearer ").strip()
    )
    if not token:
        raise HTTPException(401, "Not authenticated")
    payload = verify_token(token)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    user_id = payload.get("sub")
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, name, monthly_budget, monthly_spend, "
        "monthly_reset_at, daily_budget, daily_spend, "
        "daily_reset_at, active "
        "FROM users WHERE id = ? AND active = 1",
        (user_id,),
    )
    if not rows:
        raise HTTPException(401, "Invalid session")
    user = dict(rows[0])
    user = await refresh_user_budgets(user)
    return user


# -- User Login --

@router.post("/login")
async def user_login(request: Request):
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")
    if not username or not password:
        raise HTTPException(400, "username and password required")
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, name, password_hash FROM users "
        "WHERE name = ? AND active = 1",
        (username,),
    )
    if not rows:
        raise HTTPException(401, "Invalid credentials")
    user = dict(rows[0])
    if not verify_password(password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid credentials")
    token = create_token(user["id"], user["name"])
    return {
        "ok": True,
        "token": token,
        "user_id": user["id"],
        "name": user["name"],
    }


# -- Change Password --

@router.post("/change-password")
async def change_password(request: Request):
    user = await _require_user(request)
    body = await request.json()
    current = body.get("current_password", "")
    new_pwd = body.get("new_password", "")
    if not current or not new_pwd:
        raise HTTPException(400, "Both fields required")
    if len(new_pwd) < 4:
        raise HTTPException(400, "Password too short (min 4)")
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT password_hash FROM users WHERE id = ?",
        (user["id"],),
    )
    if not rows or not verify_password(current, dict(rows[0]).get("password_hash", "")):
        raise HTTPException(403, "Current password is wrong")
    new_hash = hash_password(new_pwd)
    await db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (new_hash, user["id"]),
    )
    await db.commit()
    return {"ok": True}


# -- User Profile --

@router.get("/me")
async def get_me(request: Request):
    user = await _require_user(request)
    return user


# -- User API Keys --

@router.get("/keys")
async def my_keys(request: Request):
    user = await _require_user(request)
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT key, label, active, created_at "
        "FROM api_keys WHERE user_id = ?",
        (user["id"],),
    )
    return [dict(r) for r in rows]


# -- User Usage (daily) --

@router.get("/usage/daily")
async def my_daily_usage(request: Request):
    user = await _require_user(request)
    today = date.today().isoformat()
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT model, COUNT(*) as requests, "
        "SUM(input_tokens) as input_tokens, "
        "SUM(output_tokens) as output_tokens, "
        "SUM(cost) as cost "
        "FROM usage_log "
        "WHERE user_id = ? AND date(created_at) = ? "
        "GROUP BY model ORDER BY cost DESC",
        (user["id"], today),
    )
    return [dict(r) for r in rows]


# -- User Usage (monthly) --

@router.get("/usage/monthly")
async def my_monthly_usage(request: Request):
    user = await _require_user(request)
    month = _current_month()
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT model, COUNT(*) as requests, "
        "SUM(input_tokens) as input_tokens, "
        "SUM(output_tokens) as output_tokens, "
        "SUM(cost) as cost "
        "FROM usage_log "
        "WHERE user_id = ? AND strftime('%%Y-%%m', created_at) = ? "
        "GROUP BY model ORDER BY cost DESC",
        (user["id"], month),
    )
    return [dict(r) for r in rows]


# -- User Monthly History (aggregated from daily) --

@router.get("/history")
async def my_history(request: Request):
    user = await _require_user(request)
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT strftime('%Y-%m', day) as month, "
        "SUM(spend) as spend "
        "FROM daily_budget_history "
        "WHERE user_id = ? "
        "GROUP BY month ORDER BY month DESC",
        (user["id"],),
    )
    return [dict(r) for r in rows]


# -- User Daily History --

@router.get("/daily-history")
async def my_daily_history(request: Request):
    user = await _require_user(request)
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT day, budget, spend "
        "FROM daily_budget_history "
        "WHERE user_id = ? ORDER BY day DESC",
        (user["id"],),
    )
    return [dict(r) for r in rows]
