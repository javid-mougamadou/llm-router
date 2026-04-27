"""SQLite database: users, api_keys, usage_log, daily_budget_history."""

import hashlib
import hmac
import os
import aiosqlite
from app.config import DB_PATH

DEFAULT_PASSWORD = "changeme"


def hash_password(pwd: str, salt: bytes | None = None) -> str:
    """Hash password with PBKDF2-SHA256 + random salt.
    Returns 'salt_hex:hash_hex' string."""
    if salt is None:
        salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt, 100_000)
    return salt.hex() + ":" + h.hex()


def verify_password(pwd: str, stored: str) -> bool:
    """Verify password against stored 'salt:hash' string.
    Also accepts legacy bare SHA-256 hashes for migration."""
    if ":" not in stored:
        # Legacy SHA-256 without salt
        return hmac.compare_digest(
            hashlib.sha256(pwd.encode()).hexdigest(), stored
        )
    salt_hex, _ = stored.split(":", 1)
    salt = bytes.fromhex(salt_hex)
    return hmac.compare_digest(hash_password(pwd, salt), stored)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    monthly_budget REAL NOT NULL DEFAULT 0,
    monthly_spend REAL NOT NULL DEFAULT 0,
    monthly_reset_at TEXT DEFAULT '',
    daily_budget REAL NOT NULL DEFAULT 0,
    daily_spend REAL NOT NULL DEFAULT 0,
    daily_reset_at TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    password_hash TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_keys (
    key TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    label TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_budget_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    day TEXT NOT NULL,
    budget REAL NOT NULL DEFAULT 0,
    spend REAL NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, day)
);
"""


_pool: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    """Return the shared connection (WAL mode allows concurrent reads)."""
    global _pool
    if _pool is None:
        _pool = await aiosqlite.connect(DB_PATH)
        _pool.row_factory = aiosqlite.Row
        await _pool.execute("PRAGMA journal_mode=WAL")
        await _pool.execute("PRAGMA foreign_keys=ON")
        await _pool.execute("PRAGMA busy_timeout=5000")
    return _pool


async def close_db():
    """Close the shared connection (call on shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_db():
    db = await get_db()
    await db.executescript(SCHEMA)
    cols = [r[1] for r in await db.execute_fetchall("PRAGMA table_info(users)")]
    # Migrate: rename max_budget -> monthly_budget
    if "max_budget" in cols and "monthly_budget" not in cols:
        await db.execute("ALTER TABLE users RENAME COLUMN max_budget TO monthly_budget")
    if "current_spend" in cols and "monthly_spend" not in cols:
        await db.execute("ALTER TABLE users RENAME COLUMN current_spend TO monthly_spend")
    # Re-read after renames
    cols = [r[1] for r in await db.execute_fetchall("PRAGMA table_info(users)")]
    if "monthly_budget" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN monthly_budget REAL NOT NULL DEFAULT 0")
    if "monthly_spend" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN monthly_spend REAL NOT NULL DEFAULT 0")
    if "monthly_reset_at" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN monthly_reset_at TEXT DEFAULT ''")
    if "daily_budget" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN daily_budget REAL NOT NULL DEFAULT 0")
    if "daily_spend" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN daily_spend REAL NOT NULL DEFAULT 0")
    if "daily_reset_at" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN daily_reset_at TEXT DEFAULT ''")
    if "password_hash" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
    # Set default password for users that don't have one
    default_hash = hash_password(DEFAULT_PASSWORD)
    await db.execute(
        "UPDATE users SET password_hash = ? "
        "WHERE password_hash = '' OR password_hash IS NULL",
        (default_hash,),
    )
    # Drop legacy monthly_budget_history (replaced by daily)
    await db.execute(
        "DROP TABLE IF EXISTS monthly_budget_history"
    )
    await db.commit()
