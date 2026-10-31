"""Push-notification endpoints for YouTube (PubSubHubbub) and Instagram webhooks."""
import json
import xml.etree.ElementTree as ET

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.ingestion.instagram import verify_signature
from app.ingestion.youtube import parse_push_notification

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/youtube", response_class=PlainTextResponse)
def youtube_verify(challenge: str = Query(alias="hub.challenge")) -> str:
    """Answer the hub's subscription verification request."""
    return challenge


@router.post("/youtube")
async def youtube_push(request: Request, tasks: BackgroundTasks) -> dict:
    """Receive an upload notification and trigger a sync of the channel."""
    ingestion = request.app.state.ingestion
    try:
        channels = {ch for ch, _ in parse_push_notification(await request.body())}
    except ET.ParseError as exc:
        raise HTTPException(400, "invalid YouTube webhook XML") from exc
    for ch in channels:
        tasks.add_task(ingestion.sync_external, "youtube", ch)
    return {"channels": sorted(channels)}


@router.get("/instagram", response_class=PlainTextResponse)
def instagram_verify(mode: str = Query(alias="hub.mode"), token: str = Query(alias="hub.verify_token"), challenge: str = Query(alias="hub.challenge")) -> str:
    """Answer Meta's webhook verification handshake."""
    if mode != "subscribe" or token != get_settings().instagram_verify_token:
        raise HTTPException(403, "verification failed")
    return challenge


@router.post("/instagram")
async def instagram_push(request: Request, tasks: BackgroundTasks) -> dict:
    """Receive a signed Instagram webhook and trigger a sync of the affected accounts."""
    body = await request.body()
    if not verify_signature(body, request.headers.get("X-Hub-Signature-256"), get_settings().instagram_app_secret):
        raise HTTPException(403, "bad signature")
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "invalid Instagram webhook JSON") from exc
    entries = payload.get("entry", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        raise HTTPException(400, "invalid Instagram webhook entry list")
    accounts = {
        str(entry["id"])
        for entry in entries
        if isinstance(entry, dict) and entry.get("id") is not None
    }
    for acc in accounts:
        tasks.add_task(request.app.state.ingestion.sync_external, "instagram", acc)
    return {"accounts": sorted(accounts)}
