from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db, SessionLocal
from app.routers.api import admin_router, router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings = get_settings()
    if settings.seed_on_startup:
        try:
            from seed import seed_database

            seed_database(SessionLocal())
        except Exception as exc:
            print(f"Seed skipped: {exc}")
    yield


app = FastAPI(title=get_settings().app_name, version="1.0.0", lifespan=lifespan)
# Keep the original /api URLs working while making the documented /api/v1
# contract the primary path for new clients and deployments.
app.include_router(router, prefix="/api")
app.include_router(router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/admin")
app.include_router(admin_router, prefix="/api/v1/admin")

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def user_app():
    return FileResponse(static_dir / "index.html")


@app.get("/admin")
def admin_app():
    return FileResponse(static_dir / "admin.html")
