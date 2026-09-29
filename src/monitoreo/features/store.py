"""Almacén de comportamiento con ventanas deslizantes (velocidad / perfilado).

Implementación en memoria, thread-safe y acotada en memoria. La interfaz
`BehaviorStore` permite reemplazarla por un backend distribuido (Redis
sorted sets / streams, Aerospike, etc.) cuando se despliegan múltiples réplicas
del motor: las reglas no dependen del backend.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable

MAX_WINDOW_SECONDS = 90 * 24 * 3600  # 90 días: perfilado histórico
MAX_EVENTS_PER_KEY = 5000


@dataclass(slots=True)
class Event:
    ts: float
    amount: float
    approved: bool
    attrs: dict[str, Any] = field(default_factory=dict)


class BehaviorStore(ABC):
    @abstractmethod
    def add(self, key: str, event: Event) -> None: ...

    @abstractmethod
    def events(self, key: str, since: float, until: float | None = None) -> list[Event]: ...

    @abstractmethod
    def last(self, key: str, predicate=None) -> Event | None: ...

    @abstractmethod
    def seen(self, key: str) -> bool: ...

    @abstractmethod
    def mark(self, key: str) -> None: ...


class InMemoryBehaviorStore(BehaviorStore):
    def __init__(self, max_events_per_key: int = MAX_EVENTS_PER_KEY):
        self._data: dict[str, deque[Event]] = defaultdict(lambda: deque(maxlen=max_events_per_key))
        self._marks: set[str] = set()
        self._lock = threading.RLock()

    def add(self, key: str, event: Event) -> None:
        with self._lock:
            dq = self._data[key]
            dq.append(event)
            horizon = event.ts - MAX_WINDOW_SECONDS
            while dq and dq[0].ts < horizon:
                dq.popleft()

    def events(self, key: str, since: float, until: float | None = None) -> list[Event]:
        with self._lock:
            dq = self._data.get(key)
            if not dq:
                return []
            return [e for e in dq if e.ts >= since and (until is None or e.ts <= until)]

    def last(self, key: str, predicate=None) -> Event | None:
        with self._lock:
            dq = self._data.get(key)
            if not dq:
                return None
            for e in reversed(dq):
                if predicate is None or predicate(e):
                    return e
            return None

    def seen(self, key: str) -> bool:
        with self._lock:
            return key in self._marks

    def mark(self, key: str) -> None:
        with self._lock:
            self._marks.add(key)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._marks.clear()


def agg(events: Iterable[Event], approved_only: bool = True) -> tuple[int, float]:
    count, total = 0, 0.0
    for e in events:
        if approved_only and not e.approved:
            continue
        count += 1
        total += e.amount
    return count, total


def distinct(events: Iterable[Event], attr: str) -> int:
    return len({e.attrs.get(attr) for e in events if e.attrs.get(attr) is not None})
