from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI

from app.web.routes import router as web_router
from app.runs.storage import init_db
from app.opencode import get_client, close_default


log = logging.getLogger("ai_senate.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Health check the opencode server (single entry point for all agents)
    try:
        client = get_client()
        healthy = await client.health()
        if healthy:
            log.info("opencode server reachable at %s", client.base_url)
        else:
            log.warning(
                "opencode server NOT reachable at %s — agent calls will fail until it is up",
                client.base_url,
            )
    except Exception as e:
        log.warning("opencode health check raised: %s", e)

    try:
        yield
    finally:
        await close_default()


app = FastAPI(
    title="AI Senate",
    description="Deterministic AI consensus specification coordinator, powered by opencode.",
    lifespan=lifespan,
)

app.include_router(web_router)
