"""LLM Router — FastAPI entrypoint."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from app.db import init_db, close_db
from app.config import HOST, PORT, WORKERS, UI_REFRESH_INTERVAL, MAX_CONCURRENT
from app.routes.anthropic import router as anthropic_router
from app.routes.openai import router as openai_router
from app.routes.admin import router as admin_router
from app.routes.user import router as user_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

TEMPLATES_DIR = Path(__file__).parent / "app" / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Thread pool for concurrent Bedrock calls
    pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT)
    asyncio.get_running_loop().set_default_executor(pool)
    await init_db()
    logging.info(
        "LLM Router started on %s:%s (workers=%s, max_concurrent=%s)",
        HOST, PORT, WORKERS, MAX_CONCURRENT,
    )
    yield
    await close_db()
    pool.shutdown(wait=False)
    logging.info("LLM Router stopped")


app = FastAPI(
    title="LLM Router", version="0.2.0", lifespan=lifespan,
    docs_url=None, redoc_url=None, openapi_url=None,
)
app.include_router(anthropic_router)
app.include_router(openai_router)
app.include_router(admin_router)
app.include_router(user_router)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    base = str(request.base_url).rstrip("/")
    html = (TEMPLATES_DIR / "home.html").read_text()
    html = html.replace("{{BASE_URL}}", base)
    return HTMLResponse(html)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin-ui", response_class=HTMLResponse)
async def admin_ui():
    html = (TEMPLATES_DIR / "admin.html").read_text()
    html = html.replace("{{REFRESH_INTERVAL}}", str(UI_REFRESH_INTERVAL))
    return HTMLResponse(html)


@app.get("/user-ui", response_class=HTMLResponse)
async def user_dashboard_ui():
    html = (TEMPLATES_DIR / "user.html").read_text()
    html = html.replace("{{REFRESH_INTERVAL}}", str(UI_REFRESH_INTERVAL))
    return HTMLResponse(html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, workers=WORKERS)
