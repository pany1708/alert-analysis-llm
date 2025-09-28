"""Simple TTL cache for deduplication."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple


@dataclass
class CacheItem:
    key: str
    timestamp: float


class DeduplicationCache:
    def __init__(self, ttl_seconds: int, max_size: int):
        self.ttl = ttl_seconds
        self.max_size = max_size
        self.queue: Deque[CacheItem] = deque()
        self.index: Dict[str, float] = {}

    def add(self, key: str) -> bool:
        now = time.time()
        self._evict(now)
        if key in self.index:
            return False
        self.index[key] = now
        self.queue.append(CacheItem(key, now))
        if len(self.queue) > self.max_size:
            old = self.queue.popleft()
            self.index.pop(old.key, None)
        return True

    def _evict(self, now: float) -> None:
        while self.queue and now - self.queue[0].timestamp > self.ttl:
            old = self.queue.popleft()
            self.index.pop(old.key, None)
