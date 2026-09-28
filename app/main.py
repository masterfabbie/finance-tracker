from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth import ensure_admin
from app.db import SessionLocal
from app.routers import (
    accounts,
    auth,
    budgets,
    categories,
    export,
    imports,
    recurring,
    rules,
    stats,
    transactions,
    users,
)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with SessionLocal() as db:
        ensure_admin(db)
    yield


app = FastAPI(title="Finance Tracker", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

for r in (auth, users, accounts, categories, transactions, imports, rules, budgets, recurring, stats, export):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if not request.url.path.startswith("/api/docs"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'",
        )
    return response


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
