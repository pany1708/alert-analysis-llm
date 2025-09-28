"""Orchestrator service coordinating RCA and remediation policies."""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Dict

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
import structlog

from services.common.config import load_config
from services.common.logging import configure_logging
from services.common.metrics import MetricsRegistry
from services.common.models import Event, PolicyDecision, RCAResponse
from services.orchestrator.cache import DeduplicationCache
from services.orchestrator.policy import PolicyEngine, PolicyRepository

CONFIG = load_config("config/orchestrator.yaml")
configure_logging(CONFIG.get("logging", {}).get("level", "INFO"), CONFIG.get("logging", {}).get("json", True))
logger = structlog.get_logger(__name__)
metrics = MetricsRegistry(CONFIG.get("observability", {}).get("histogram_buckets", [0.1, 0.5, 1.0]))
metrics.start_exporter(CONFIG.get("observability", {}).get("metrics_port", 9303))

app = FastAPI(title="Ops Orchestrator", version="0.1.0")
cache = DeduplicationCache(
    ttl_seconds=CONFIG.get("deduplication", {}).get("window_seconds", 300),
    max_size=CONFIG.get("deduplication", {}).get("cache_size", 1000),
)
policy_repo = PolicyRepository(Path(CONFIG["policy_repository"]["path"]))
policy_engine = PolicyEngine(policy_repo)
pending_approvals: Dict[str, PolicyDecision] = {}


async def call_rca_service(event: Event) -> RCAResponse:
    payload = {
        "model": "qwen-plus",
        "messages": [
            {"role": "system", "content": "你是SRE助手，严格输出JSON: evidence_plan, diagnosis, actions, rollback"},
            {"role": "user", "content": json.dumps(event.dict(), ensure_ascii=False)},
        ],
        "temperature": 0.1,
    }
    base_url = CONFIG["rca_service"]["base_url"].rstrip("/")
    async with httpx.AsyncClient(
        timeout=CONFIG.get("rca_service", {}).get("timeout_seconds", 45)
    ) as client:
        response = await client.post(f"{base_url}/rca", json=payload)
        response.raise_for_status()
        data = response.json()
    return RCAResponse.parse_obj(data)


async def process_event(event: Event) -> PolicyDecision:
    rca = await call_rca_service(event)
    decision = policy_engine.evaluate(event, rca)
    if not decision.approved:
        request_id = str(uuid.uuid4())
        pending_approvals[request_id] = decision
        logger.info("orchestrator.approval_required", request_id=request_id, alert=event.alert)
    else:
        logger.info("orchestrator.approved", alert=event.alert)
    return decision


@app.on_event("startup")
async def startup_event() -> None:  # pragma: no cover - runtime hook
    logger.info("orchestrator.startup")
    asyncio.create_task(_policy_refresh_loop())


async def _policy_refresh_loop():  # pragma: no cover - runtime hook
    interval = CONFIG["policy_repository"].get("refresh_interval_seconds", 120)
    while True:
        await asyncio.sleep(interval)
        policy_engine.refresh()
        logger.info("policy.refreshed")


@app.post("/events")
async def receive_event(event: Event, background_tasks: BackgroundTasks):
    fingerprint = f"{event.alert}:{event.labels.cluster}:{event.metrics.first_occur}"
    if not cache.add(fingerprint):
        metrics.processed_events.labels(status="duplicate").inc()
        return {"status": "duplicate"}
    metrics.processed_events.labels(status="accepted").inc()
    background_tasks.add_task(process_event, event)
    return {"status": "queued"}


@app.post("/approvals/{request_id}")
async def approve(request_id: str):
    decision = pending_approvals.get(request_id)
    if not decision:
        raise HTTPException(status_code=404, detail="request not found")
    decision.approved = True
    logger.info("approval.granted", request_id=request_id)
    return {"status": "approved", "actions": decision.actions_to_execute}


@app.post("/policies/reload")
async def reload_policies():
    policy_engine.refresh()
    return {"status": "reloaded"}


@app.get("/healthz")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}
