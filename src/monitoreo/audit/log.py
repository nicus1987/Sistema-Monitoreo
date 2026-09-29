"""Registro de auditoría inmutable (append-only, encadenado por hash).

Cada decisión se persiste con el hash del registro anterior, de modo que
cualquier alteración posterior rompe la cadena y es detectable con `verify()`.
Cubre requisitos de trazabilidad, integridad y conservación de registros
(Com. "A" 7724 BCRA; conservación de documentación PLA/FT según Ley 25.246 y
resoluciones UIF — plazo mínimo usual de 10 años, configurable en retención).
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class AuditLog:
    def __init__(self, path: str | Path | None = None, keep_in_memory: int = 10000):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._memory: list[dict[str, Any]] = []
        self._keep = keep_in_memory
        self._last_hash = GENESIS
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                for record in self._read_file():
                    self._last_hash = record["hash"]

    def _read_file(self) -> Iterator[dict[str, Any]]:
        assert self.path is not None
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)

    def append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            body = {"type": event_type, "payload": payload, "prev_hash": self._last_hash}
            digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
            record = {**body, "hash": digest}
            if self.path:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(_canonical(record) + "\n")
            self._memory.append(record)
            if len(self._memory) > self._keep:
                self._memory = self._memory[-self._keep:]
            self._last_hash = digest
            return record

    def records(self) -> list[dict[str, Any]]:
        if self.path and self.path.exists():
            return list(self._read_file())
        return list(self._memory)

    def verify(self) -> tuple[bool, int | None]:
        """Devuelve (True, None) si la cadena es íntegra, o (False, índice) del primer registro alterado."""
        prev = GENESIS
        for idx, rec in enumerate(self.records()):
            body = {"type": rec["type"], "payload": rec["payload"], "prev_hash": rec["prev_hash"]}
            if rec["prev_hash"] != prev or hashlib.sha256(_canonical(body).encode()).hexdigest() != rec["hash"]:
                return False, idx
            prev = rec["hash"]
        return True, None
