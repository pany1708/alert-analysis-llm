"""Email ingest microservice exposing HTTP endpoints for alert normalization."""
from __future__ import annotations

import asyncio
import hmac
import json
import threading
from hashlib import sha256
from typing import Any, Dict, List

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import structlog

from services.common.config import load_config
from services.common.logging import configure_logging
from services.common.metrics import MetricsRegistry
from services.common.models import Event, RawEventMetadata
from services.ingest.email_parser import EmailParser
from services.ingest.imap_worker import IMAPPoller
from services.ingest.msgraph_worker import GraphIngestor

CONFIG = load_config("config/ingest.yaml")
configure_logging(CONFIG.get("logging", {}).get("level", "INFO"), CONFIG.get("logging", {}).get("json", True))
logger = structlog.get_logger(__name__)
metrics = MetricsRegistry(CONFIG.get("observability", {}).get("histogram_buckets", [0.1, 0.5, 1.0]))
metrics.start_exporter(CONFIG.get("observability", {}).get("metrics_port", 9301))

app = FastAPI(title="Email Ingest Service", version="0.1.0")
parser = EmailParser()


async def push_event(event: Event) -> None:
    endpoint = CONFIG["webhooks"]["alertmanager"]["rca_endpoint"]
    logger.info("ingest.forward", endpoint=endpoint, alert=event.alert)
    metrics.processed_events.labels(status="processed").inc()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(endpoint, json=json.loads(event.json()))
        response.raise_for_status()


def start_imap_pollers():  # pragma: no cover - background threads
    for mailbox in CONFIG.get("mailboxes", []):
        if mailbox.get("type") != "imap" or not mailbox.get("enabled", False):
            continue
        poller = IMAPPoller(mailbox, parser)

        def callback(event: Event) -> None:
            asyncio.run(push_event(event))

        thread = threading.Thread(target=poller.poll_forever, args=(callback,), daemon=True)
        thread.start()
        logger.info("imap.poller.started", mailbox=mailbox.get("username"))


@app.on_event("startup")
async def startup_event() -> None:  # pragma: no cover - runtime hook
    logger.info("ingest.startup")
    start_imap_pollers()


@app.post("/events/email")
async def ingest_email(payload: Dict[str, Any]) -> Dict[str, Any]:
    metadata = RawEventMetadata(
        mail_subject=payload.get("subject"),
        mail_id=payload.get("message_id"),
        source=payload.get("source", "api"),
        payload=payload,
    )
    events = parser.parse(payload.get("body", ""), metadata)
    for event in events:
        await push_event(event)
    return {"accepted": len(events)}


@app.post("/webhook/alertmanager")
async def alertmanager_webhook(request: Request, background_tasks: BackgroundTasks):
    secret = CONFIG["webhooks"]["alertmanager"].get("shared_secret")
    if secret:
        signature = request.headers.get("X-Signature")
        body = await request.body()
        expected = hmac.new(secret.encode(), body, sha256).hexdigest()
        if signature != expected:
            raise HTTPException(status_code=401, detail="signature mismatch")
        payload = json.loads(body)
    else:
        payload = await request.json()
    event = Event.parse_obj(payload)
    background_tasks.add_task(push_event, event)
    return {"status": "queued"}


@app.post("/msgraph/webhook")
async def msgraph_webhook(request: Request):
    params = dict(request.query_params)
    if "validationToken" in params:
        logger.info("msgraph.validation")
        return JSONResponse(content=params["validationToken"])
    payload = await request.json()
    ingestor = GraphIngestor(CONFIG["mailboxes"][1], parser)
    events: List[Event] = []
    for notification in payload.get("value", []):
        events.extend(ingestor.fetch_incremental(notification))
    for event in events:
        await push_event(event)
    return {"processed": len(events)}


@app.get("/healthz")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}
