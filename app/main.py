from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.web.routes import router as web_router
from app.runs.storage import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register default proxy API key if not set
    import os
    if "AGY_PROXY_API_KEY" not in os.environ:
        os.environ["AGY_PROXY_API_KEY"] = "sk-cliproxy-local"
    # Initialize SQLite database on startup
    init_db()
    yield

app = FastAPI(
    title="AI Senate MVP",
    description="Deterministic AI consensus specification coordinator",
    lifespan=lifespan
)

app.include_router(web_router)
