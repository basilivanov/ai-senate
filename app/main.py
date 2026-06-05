import os
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.web.api import router as api_router
from app.runs.storage import init_db
from app.opencode import get_client, close_default


log = logging.getLogger("ai_senate.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        client = get_client()
        healthy = await client.health()
        log.info("opencode server %sreachable at %s",
                 "" if healthy else "NOT ", client.base_url)
    except Exception as e:
        log.warning("opencode health check raised: %s", e)
    try:
        yield
    finally:
        await close_default()


PROJECT_ROOT = os.environ.get(
    "AI_SENATE_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "web", "static")


app = FastAPI(
    title="AI Senate",
    description="Deterministic AI consensus specification coordinator, powered by opencode.",
    lifespan=lifespan,
)


@app.exception_handler(StarletteHTTPException)
async def http_exc_handler(request, exc):
    if exc.status_code == 404 and not request.url.path.startswith("/api"):
        index = os.path.join(STATIC_DIR, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


app.include_router(api_router)

# Serve built SPA if present
if os.path.isdir(STATIC_DIR) and os.path.isfile(os.path.join(STATIC_DIR, "index.html")):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/")
    @app.get("/{full_path:path}")
    async def spa(full_path: str = ""):
        if full_path.startswith("api") or full_path.startswith("assets"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
else:
    @app.get("/")
    async def fallback():
        return JSONResponse({
            "status": "ai-senate backend running",
            "frontend": "not built — run `cd frontend && npm run build`",
            "api_docs": "/docs",
        })
