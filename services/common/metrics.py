"""Prometheus metrics utilities."""
from __future__ import annotations

from typing import Iterable

from prometheus_client import Counter, Histogram, start_http_server


class MetricsRegistry:
    def __init__(self, buckets: Iterable[float]):
        self.processing_latency = Histogram(
            "service_processing_latency_seconds",
            "Latency for processing RCA pipeline stages",
            buckets=tuple(buckets),
        )
        self.processed_events = Counter(
            "service_processed_events_total",
            "Number of events processed by the service",
            ["status"],
        )

    def start_exporter(self, port: int) -> None:
        start_http_server(port)
