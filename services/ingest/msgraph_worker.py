"""Microsoft Graph subscription utilities."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

import httpx
import structlog

from services.common.models import Event, RawEventMetadata
from services.ingest.email_parser import EmailParser

logger = structlog.get_logger(__name__)


class GraphIngestor:
    def __init__(self, config: Dict[str, Any], parser: EmailParser):
        self.config = config
        self.parser = parser
        self.client = httpx.Client(timeout=30)

    def fetch_incremental(self, subscription_payload: Dict[str, Any]) -> List[Event]:
        resource_id = subscription_payload.get("resourceData", {}).get("id")
        if not resource_id:
            logger.warning("graph.payload.missing_id", payload=subscription_payload)
            return []
        token = self._acquire_token()
        url = f"https://graph.microsoft.com/v1.0/users/{self.config['user_id']}/messages/{resource_id}"
        response = self.client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        message = response.json()
        metadata = RawEventMetadata(
            mail_subject=message.get("subject"),
            mail_id=message.get("id"),
            source="msgraph",
            payload={"subject": message.get("subject")},
        )
        body = message.get("body", {}).get("content", "")
        return self.parser.parse(body, metadata)

    def _acquire_token(self) -> str:  # pragma: no cover - external call
        tenant = self.config["tenant_id"]
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        data = {
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
        response = self.client.post(token_url, data=data)
        response.raise_for_status()
        return response.json()["access_token"]

    def handle_validation(self, token: str) -> Dict[str, Any]:
        logger.info("graph.validation", token=token)
        return {"validationToken": token}
