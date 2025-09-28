"""Client for interacting with Qwen RCA model."""
from __future__ import annotations

import json
import os
from typing import Any, Dict

import httpx
import structlog

from services.common.models import Event, RCAResponse

logger = structlog.get_logger(__name__)


class QwenClient:
    def __init__(self, config: Dict[str, Any]):
        self.base_url = config["base_url"].rstrip("/")
        self.model = config.get("model", "qwen-plus")
        self.temperature = config.get("temperature", 0.1)
        self.timeout = config.get("request_timeout_seconds", 30)
        api_key_env = config.get("api_key_env", "QWEN_API_KEY")
        self.api_key = os.getenv(api_key_env)

    async def rca(self, event: Event) -> RCAResponse:
        if not self.api_key:
            logger.warning("qwen.api_key.missing")
            return self._offline_rca(event)
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": "你是SRE助手，严格输出JSON: evidence_plan, diagnosis, actions, rollback",
                },
                {"role": "user", "content": json.dumps(event.dict(), ensure_ascii=False)},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post("/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("qwen.parse_failed", content=content)
            parsed = {
                "evidence_plan": [],
                "diagnosis": "Unable to parse model output",
                "actions": [],
                "rollback": [],
            }
        return RCAResponse(**parsed, raw_response=data)

    def _offline_rca(self, event: Event) -> RCAResponse:
        notes = {
            "PrometheusRemoteWriteBehind": "Check remote write lag and agent health",
            "JenkinsMasterRestarted": "Ensure Jenkins agents reconnect",
        }
        return RCAResponse(
            evidence_plan=[{"step": "Check dashboards", "alert": event.alert}],
            diagnosis=notes.get(event.alert, "Manual investigation required"),
            actions=[{"type": "noop", "reason": "offline-mode"}],
            rollback=[],
            raw_response={},
        )
