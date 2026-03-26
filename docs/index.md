---
layout: default
title: LLM Router
description: Lightweight FastAPI proxy that routes Anthropic and OpenAI API requests to AWS Bedrock
keywords:
  - LLM Router
  - LLM Proxy
  - AWS Bedrock
  - Anthropic API
  - OpenAI API
  - FastAPI
  - Budget management
---

# LLM Router

> **Experimental** — This repository is a proof-of-concept intended for testing and validation purposes only. It is not designed for production workloads.

Lightweight FastAPI proxy that routes Anthropic and OpenAI API requests to AWS Bedrock. Includes per-user budget management, API key authentication, usage tracking, and web dashboards.

## Table of Contents

- [Genesis](#genesis)
- [Features](#features)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Models](#models-default)
- [Environment Variables](#environment-variables)
- [API Endpoints](#api-endpoints)
- [Security Notes](#security-notes)

## Genesis

This project is heavily inspired by [LiteLLM](https://github.com/BerriAI/litellm). It was designed to have minimal dependencies and cover a subset of LiteLLM's features without requiring Prisma for database management. It serves as a way to validate user management and request routing with API tokens. For a more complete setup with a larger number of users, using LiteLLM directly is recommended.

## Features

- **Dual API compatibility** — `/v1/messages` (Anthropic) + `/v1/chat/completions` (OpenAI)
- **Streaming support** — SSE streaming for both API formats
- **Budget management** — Per-user monthly and daily budgets with automatic spend tracking and auto-reset
- **API key auth** — Generate multiple keys per user, enable/disable or revoke anytime
- **Usage logging** — Token counts and cost per request, per user, per model
- **Monthly history** — Automatic archival of monthly spend when a new month starts
- **Admin UI** — Web dashboard at `/admin-ui` to manage users, keys, budgets, and usage
- **User UI** — Self-service dashboard at `/user-ui` for users to view their budget, usage, and change password
- **Dark / Light mode** — Theme toggle with localStorage persistence across sessions
- **JWT authentication** — User dashboard sessions use signed HMAC-SHA256 tokens (24h TTL)
- **Secure passwords** — PBKDF2-SHA256 with random salt (100k iterations)
- **SQLite with WAL** — Single shared connection, WAL mode for concurrent reads

## Quick Start

```bash
# Copy example files
cp Dockerfile.example Dockerfile
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env

# Build and run
docker compose up dev

# Access dashboards
open http://localhost:4000/admin-ui   # admin (default: admin/admin)
open http://localhost:4000/user-ui    # user  (default password: changeme)

# Health check
curl http://localhost:4000/health
```

## Project Structure

```
llm-router/
  src/
    main.py                  # FastAPI entrypoint, lifespan, UI routes
    app/
      config.py              # Environment variables and model definitions
      db.py                  # SQLite schema, connection pool, password hashing
      auth.py                # API key validation, budget enforcement, usage logging
      bedrock.py             # AWS Bedrock Converse API client (sync + streaming)
      jwt_utils.py           # Minimal HMAC-SHA256 JWT (no external dependency)
      routes/
        anthropic.py         # /v1/messages endpoint
        openai.py            # /v1/chat/completions + /v1/models
        admin.py             # Admin CRUD endpoints
        user.py              # User dashboard endpoints
      templates/
        admin.html           # Admin web UI (basecoat theme)
        user.html            # User web UI (basecoat theme)
  Dockerfile.example           # Dockerfile template (public registries)
  docker-compose.example.yml   # Docker Compose template
  .env.example                 # Environment variables template
  requirements.txt
  example.sh                   # curl usage examples
```

## Models (default)

| Alias | Bedrock ID | Input $/1M | Output $/1M |
|---|---|---|---|
| `claude-opus` | `eu.anthropic.claude-opus-4-6-v1` | $15.00 | $75.00 |
| `claude-opus-4-6` | `eu.anthropic.claude-opus-4-6-v1` | $15.00 | $75.00 |
| `claude-sonnet-4-6` | `eu.anthropic.claude-sonnet-4-6` | $3.00 | $15.00 |
| `claude-sonnet-4-5-20250929` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` | $3.00 | $15.00 |
| `claude-haiku-4-5-20251001` | `eu.anthropic.claude-haiku-4-5-20251001-v1:0` | $0.80 | $4.00 |

Override models via `LLM_ROUTER_MODELS` env var (JSON).

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_ROUTER_HOST` | `0.0.0.0` | Listen address |
| `LLM_ROUTER_PORT` | `4000` | Listen port |
| `LLM_ROUTER_WORKERS` | `1` | Uvicorn workers |
| `MAX_CONCURRENT` | `20` | Thread pool size for Bedrock calls |
| `MASTER_KEY` | `sk-admin-secret` | Admin API key (also used as JWT secret) |
| `ADMIN_USER` | `admin` | Admin UI username |
| `ADMIN_PASSWORD` | `admin` | Admin UI password |
| `UI_REFRESH_INTERVAL` | `30` | Dashboard auto-refresh interval (seconds) |
| `AWS_REGION` | `eu-west-3` | AWS Bedrock region |
| `AWS_PROFILE` | `default` | AWS credentials profile |
| `LLM_ROUTER_DB` | `/data/llm_router.db` | SQLite database path |
| `LLM_ROUTER_MODELS` | *(built-in)* | JSON override for model definitions |

## API Endpoints

### Proxy (requires user API key)

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/messages` | Anthropic Messages API |
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions API |
| `GET` | `/v1/models` | List available models |

### Admin (requires `MASTER_KEY`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/login` | Admin login (returns master key) |
| `GET` | `/admin/aws-status` | Check AWS credentials |
| `GET` | `/admin/users` | List all users |
| `POST` | `/admin/users` | Create user (returns API key) |
| `PATCH` | `/admin/users/{id}` | Update budget, active, reset spend |
| `DELETE` | `/admin/users/{id}` | Delete user and all related data |
| `GET` | `/admin/users/{id}/keys` | List user's API keys |
| `POST` | `/admin/users/{id}/keys` | Create additional API key |
| `PATCH` | `/admin/keys/{key}` | Enable/disable a key |
| `DELETE` | `/admin/keys/{key}` | Delete a key permanently |
| `GET` | `/admin/usage` | Usage summary by user and model |
| `GET` | `/admin/monthly-history` | Monthly budget history |

### User (requires JWT from `/user/login`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/user/login` | User login (returns JWT token) |
| `POST` | `/user/change-password` | Change password |
| `GET` | `/user/me` | Current user profile and budgets |
| `GET` | `/user/keys` | User's API keys |
| `GET` | `/user/usage/daily` | Today's usage by model |
| `GET` | `/user/usage/monthly` | This month's usage by model |
| `GET` | `/user/history` | Monthly budget history |

### Other

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/admin-ui` | Admin web dashboard |
| `GET` | `/user-ui` | User web dashboard |

## Security Notes

- **Passwords** are hashed with PBKDF2-SHA256 (100k iterations, 16-byte random salt).
- **User sessions** use HMAC-SHA256 signed JWT tokens with 24h expiry. The `MASTER_KEY` is used as the signing secret.
- **Admin access** uses the `MASTER_KEY` directly (no JWT) — keep it secret.
- Default user password is `changeme` — users should change it via the dashboard.

## License

MIT
