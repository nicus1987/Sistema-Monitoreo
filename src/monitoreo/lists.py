"""Listas de control: sanciones, PEP, jurisdicciones de riesgo, listas negras internas.

Fuentes típicas a sincronizar (fuera del alcance de este repo, via job batch):
- RePET (Registro Público de Personas y Entidades vinculadas a actos de
  Terrorismo y su Financiamiento) y listas del Consejo de Seguridad de la ONU.
- Nómina de Personas Expuestas Políticamente (Res. UIF sobre PEP vigente).
- Jurisdicciones de alto riesgo / monitoreo intensificado del GAFI.
- Listas negras internas (cuentas mula confirmadas, dispositivos, BINs comprometidos).

Los valores se normalizan (mayúsculas, sin guiones/espacios) para que un CUIT
"20-12345678-9" y "20123456789" coincidan.
"""

from __future__ import annotations

import threading
from pathlib import Path

import yaml


def normalize(value: object) -> str:
    return str(value).strip().upper().replace("-", "").replace(" ", "").replace(".", "")


class ListManager:
    def __init__(self, lists: dict[str, list[str]] | None = None):
        self._lock = threading.RLock()
        self._lists: dict[str, frozenset[str]] = {}
        self._version = "empty"
        if lists:
            self.replace(lists, version="inline")

    @classmethod
    def from_directory(cls, path: str | Path) -> "ListManager":
        mgr = cls()
        mgr.load_directory(path)
        return mgr

    def load_directory(self, path: str | Path) -> None:
        data: dict[str, list[str]] = {}
        versions: list[str] = []
        for file in sorted(Path(path).glob("*.yaml")):
            content = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
            versions.append(f"{file.stem}:{content.get('version', 'n/a')}")
            for name, values in (content.get("lists") or {}).items():
                data.setdefault(name, []).extend(values or [])
        self.replace(data, version=";".join(versions) or "empty")

    def replace(self, lists: dict[str, list[str]], version: str) -> None:
        compiled = {name: frozenset(normalize(v) for v in values) for name, values in lists.items()}
        with self._lock:
            self._lists = compiled
            self._version = version

    def contains(self, list_name: str, value: object) -> bool:
        if value is None:
            return False
        with self._lock:
            members = self._lists.get(list_name)
        if members is None:
            return False
        return normalize(value) in members

    def prefix_match(self, list_name: str, value: object) -> bool:
        """Útil para BINs (rangos) o MCC agrupados."""
        if value is None:
            return False
        norm = normalize(value)
        with self._lock:
            members = self._lists.get(list_name, frozenset())
        return any(norm.startswith(m) for m in members)

    @property
    def version(self) -> str:
        return self._version

    def summary(self) -> dict[str, int]:
        with self._lock:
            return {k: len(v) for k, v in self._lists.items()}
