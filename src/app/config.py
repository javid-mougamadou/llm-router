"""Configuration: models, pricing, env settings."""

import os
import json

# -- Server --
HOST = os.environ.get("LLM_ROUTER_HOST", "0.0.0.0")
PORT = int(os.environ.get("LLM_ROUTER_PORT", "4000"))
WORKERS = int(os.environ.get("LLM_ROUTER_WORKERS", "1"))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "20"))  # thread pool for Bedrock calls

# -- Auth --
MASTER_KEY = os.environ.get("MASTER_KEY", "sk-admin-secret")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

# -- UI --
UI_REFRESH_INTERVAL = int(os.environ.get("UI_REFRESH_INTERVAL", "30"))  # seconds

# -- AWS --
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-3")
AWS_PROFILE = os.environ.get("AWS_PROFILE", "default")

# -- Database --
# SQLite by default. To switch to Postgres later, set DATABASE_URL:
#   DATABASE_URL=postgresql://user:pass@host:5432/llm_router
# and replace aiosqlite with asyncpg in db.py
DB_PATH = os.environ.get("LLM_ROUTER_DB", "/data/llm_router.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# -- Model definitions --
_DEFAULT_MODELS = {
    "claude-opus": {
        "bedrock_id": "arn:aws:bedrock:eu-west-3:430945566659"
                      ":inference-profile/eu.anthropic.claude-opus-4-6-v1",
        "input_price": 15.0,
        "output_price": 75.0,
    },
    "claude-opus-4-6": {
        "bedrock_id": "arn:aws:bedrock:eu-west-3:430945566659"
                      ":inference-profile/eu.anthropic.claude-opus-4-6-v1",
        "input_price": 15.0,
        "output_price": 75.0,
    },
    "claude-sonnet-4-6": {
        "bedrock_id": "arn:aws:bedrock:eu-west-3:430945566659"
                      ":inference-profile/eu.anthropic.claude-sonnet-4-6",
        "input_price": 3.0,
        "output_price": 15.0,
    },
    "claude-sonnet-4-5-20250929": {
        "bedrock_id": "arn:aws:bedrock:eu-west-3:430945566659"
                      ":inference-profile/eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "input_price": 3.0,
        "output_price": 15.0,
    },
    "claude-haiku-4-5-20251001": {
        "bedrock_id": "arn:aws:bedrock:eu-west-3:430945566659"
                      ":inference-profile/eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        "input_price": 0.80,
        "output_price": 4.0,
    },
}

_env_models = os.environ.get("LLM_ROUTER_MODELS")
MODELS: dict = json.loads(_env_models) if _env_models else _DEFAULT_MODELS


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    m = MODELS.get(model)
    if not m:
        return 0.0
    return (
        input_tokens * m["input_price"] / 1_000_000
        + output_tokens * m["output_price"] / 1_000_000
    )
