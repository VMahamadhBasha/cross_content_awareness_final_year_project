"""FastAPI application entrypoint wiring the pipeline, event processor, scheduler and API."""
import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes, webhooks
from app.api.ws import ConnectionHub
from app.config import get_settings
from app.db import init_db
from app.events.processor import EventProcessor
from app.ingestion.service import IngestionService
from app.pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sdsp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise storage, models, background processing and polling."""
    settings = get_settings()
    init_db()
    pipeline = Pipeline()
    hub = ConnectionHub()
    app.state.pipeline, app.state.hub = pipeline, hub
    app.state.ingestion = IngestionService(pipeline)
    forecast_status = pipeline.forecasts.status()
    if not forecast_status["ready"]:
        log.warning("forecaster unavailable: %s", forecast_status["message"])
    processor_task = asyncio.create_task(EventProcessor(pipeline, hub.broadcast).run())
    scheduler = BackgroundScheduler()
    if app.state.ingestion.enabled:
        scheduler.add_job(app.state.ingestion.sync_all, "interval", minutes=settings.poll_interval_minutes, id="poll-platforms")
        scheduler.start()
    yield
    pipeline.bus.close()
    if scheduler.running:
        scheduler.shutdown(wait=False)
    processor_task.cancel()


app = FastAPI(title="Cross-Platform Social Media Decision Support", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")], allow_methods=["*"], allow_headers=["*"])
app.include_router(routes.router)
app.include_router(webhooks.router)


@app.websocket("/ws/alerts")
async def alerts_socket(ws: WebSocket) -> None:
    """Stream live recommendation alerts to the dashboard."""
    hub: ConnectionHub = ws.app.state.hub
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(ws)
