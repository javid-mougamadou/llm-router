"""Auth: API key validation, budget enforcement, usage logging."""

import hmac
from datetime import date
from fastapi import Request, HTTPException
from app.db import get_db
from app.config import MASTER_KEY, compute_cost


def _current_month() -> str:
    """Return current month as 'YYYY-MM'."""
    return date.today().strftime("%Y-%m")


async def resolve_user(request: Request) -> dict:
    """Extract API key from request, validate it, check budget."""
    api_key = (
        request.headers.get("x-api-key")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    )
    if not api_key:
        raise HTTPException(401, "Missing API key")

    if hmac.compare_digest(api_key, MASTER_KEY):
        return {
            "id": 0, "name": "admin",
            "monthly_budget": 0, "monthly_spend": 0,
            "daily_budget": 0, "daily_spend": 0,
        }

    db = await get_db()
    row = await db.execute_fetchall(
        """SELECT u.id, u.name, u.monthly_budget, u.monthly_spend,
                  u.monthly_reset_at, u.daily_budget, u.daily_spend,
                  u.daily_reset_at
           FROM api_keys k JOIN users u ON k.user_id = u.id
           WHERE k.key = ? AND k.active = 1 AND u.active = 1""",
        (api_key,),
    )
    if not row:
        raise HTTPException(401, "Invalid API key")

    user = dict(row[0])

    # Auto-reset monthly spend on new month
    month = _current_month()
    if user.get("monthly_reset_at") != month:
        old_spend = user["monthly_spend"]
        old_budget = user["monthly_budget"]
        old_month = user.get("monthly_reset_at") or ""
        if old_month and old_spend > 0:
            await db.execute(
                "INSERT OR IGNORE INTO monthly_budget_history "
                "(user_id, month, budget, spend) VALUES (?,?,?,?)",
                (user["id"], old_month, old_budget, old_spend),
            )
        await db.execute(
            "UPDATE users SET monthly_spend = 0, "
            "monthly_reset_at = ? WHERE id = ?",
            (month, user["id"]),
        )
        await db.commit()
        user["monthly_spend"] = 0
        user["monthly_reset_at"] = month

    # Auto-reset daily spend at midnight UTC
    today = date.today().isoformat()
    if user.get("daily_reset_at") != today:
        await db.execute(
            "UPDATE users SET daily_spend = 0, "
            "daily_reset_at = ? WHERE id = ?",
            (today, user["id"]),
        )
        await db.commit()
        user["daily_spend"] = 0
        user["daily_reset_at"] = today

    # Check monthly budget
    if user["monthly_budget"] > 0 and user["monthly_spend"] >= user["monthly_budget"]:
        raise HTTPException(
            429,
            f"Monthly budget exceeded: "
            f"${user['monthly_spend']:.4f} / "
            f"${user['monthly_budget']:.2f}",
        )
    # Check daily budget
    if user["daily_budget"] > 0 and user["daily_spend"] >= user["daily_budget"]:
        raise HTTPException(
            429,
            f"Daily budget exceeded: "
            f"${user['daily_spend']:.4f} / "
            f"${user['daily_budget']:.2f}",
        )

    return user


async def log_usage(
    user_id: int, model: str, input_tokens: int, output_tokens: int
):
    """Log usage and update spends for user."""
    if user_id == 0:
        return
    cost = compute_cost(model, input_tokens, output_tokens)
    db = await get_db()
    await db.execute(
        "INSERT INTO usage_log "
        "(user_id, model, input_tokens, output_tokens, cost) "
        "VALUES (?,?,?,?,?)",
        (user_id, model, input_tokens, output_tokens, cost),
    )
    await db.execute(
        "UPDATE users SET monthly_spend = monthly_spend + ?, "
        "daily_spend = daily_spend + ? WHERE id = ?",
        (cost, cost, user_id),
    )
    await db.commit()
