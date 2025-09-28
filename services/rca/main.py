"""RCA microservice that proxies requests to Qwen."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI
import structlog

from services.common.config import load_config
from services.common.logging import configure_logging
from services.common.metrics import MetricsRegistry
from services.common.models import Event, RCAResponse
from services.rca.client import QwenClient

CONFIG = load_config("config/rca.yaml")
configure_logging(CONFIG.get("logging", {}).get("level", "INFO"), CONFIG.get("logging", {}).get("json", True))
logger = structlog.get_logger(__name__)
metrics = MetricsRegistry(CONFIG.get("observability", {}).get("histogram_buckets", [0.1, 0.5, 1.0]))
metrics.start_exporter(CONFIG.get("observability", {}).get("metrics_port", 9302))

app = FastAPI(title="Qwen RCA Service", version="0.1.0")
client = QwenClient(CONFIG["qwen"])


@app.post("/rca")
async def rca_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    user_message = next(
        (msg for msg in payload.get("messages", []) if msg.get("role") == "user"),
        None,
    )
    if not user_message:
        return {"error": "missing user message"}
    event_data = user_message.get("content")
    if isinstance(event_data, str):
        event_dict = Event.parse_raw(event_data).dict()
    else:
        event_dict = event_data
    event = Event.parse_obj(event_dict)
    metrics.processed_events.labels(status="accepted").inc()
    response = await client.rca(event)
    return response.dict()


@app.get("/healthz")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}
