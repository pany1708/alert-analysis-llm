"""Utilities to parse alert emails into the canonical event JSON schema."""
from __future__ import annotations

import json
from typing import Iterable, List

from bs4 import BeautifulSoup

from services.common.models import AlertLabels, AlertMetrics, Event, RawEventMetadata


class EmailParser:
    def __init__(self, default_severity: str = "P3"):
        self.default_severity = default_severity

    def parse(self, raw_body: str, metadata: RawEventMetadata) -> List[Event]:
        candidates = list(self._parse_html_tables(raw_body, metadata))
        if candidates:
            return candidates
        return [
            Event(
                alert=metadata.payload.get("subject", "UnknownAlert"),
                severity=self.default_severity,
                labels=AlertLabels(**metadata.payload.get("labels", {})),
                metrics=AlertMetrics(**metadata.payload.get("metrics", {"times": 1})),
                raw=metadata,
            )
        ]

    def _parse_html_tables(
        self, raw_body: str, metadata: RawEventMetadata
    ) -> Iterable[Event]:  # pragma: no cover - heuristics
        soup = BeautifulSoup(raw_body, "html.parser")
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            rows = table.find_all("tr")
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if not cells:
                    continue
                record = dict(zip(headers, cells))
                labels = {
                    "cluster": record.get("cluster"),
                    "namespace": record.get("namespace"),
                    "workload": record.get("workload"),
                    "component": record.get("component"),
                }
                metrics = {
                    "times": int(record.get("times", 1)),
                    "first_occur": record.get("first_occur"),
                }
                yield Event(
                    alert=record.get("alert", metadata.mail_subject or "UnknownAlert"),
                    severity=record.get("severity", self.default_severity),
                    labels=AlertLabels(**labels),
                    metrics=AlertMetrics(**metrics),
                    raw=metadata,
                )

    def parse_json_attachment(self, payload: str, metadata: RawEventMetadata) -> List[Event]:
        data = json.loads(payload)
        if isinstance(data, list):
            return [self._from_json_blob(item, metadata) for item in data]
        return [self._from_json_blob(data, metadata)]

    def _from_json_blob(self, data: dict, metadata: RawEventMetadata) -> Event:
        return Event(
            alert=data.get("alert", metadata.mail_subject or "UnknownAlert"),
            severity=data.get("severity", self.default_severity),
            labels=AlertLabels(**data.get("labels", {})),
            metrics=AlertMetrics(**data.get("metrics", {"times": 1})),
            raw=metadata,
        )
