"""Edición de reglas y parámetros desde la consola.

Principios:
- Todo cambio se valida ANTES de escribir: se arma una copia de la
  configuración con el cambio aplicado y se la carga completa (sintaxis,
  IDs únicos, parámetros y listas existentes, referencias normativas).
- La escritura es atómica (archivo temporal + reemplazo) y conserva los
  comentarios y el formato de los YAML.
- Las reglas del catálogo base no se eliminan: se desactivan o se pasan a
  modo sombra. Sólo las reglas creadas desde la consola (90_consola.yaml)
  pueden eliminarse.
- Cada cambio queda en la auditoría con usuario, estado anterior y nuevo.
"""

from __future__ import annotations

import copy
import io
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .engine.explain import references
from .engine.rules import RuleSet, RuleSetError
from .lists import ListManager
from .models import Action, Channel, RiskCategory, Severity

CONSOLE_FILE = "90_consola.yaml"
CONSOLE_HEADER = (
    "# Reglas creadas desde la consola de monitoreo.\n"
    "# Se pueden editar acá o desde la consola; los cambios quedan auditados.\n"
)
RULE_FIELD_ORDER = ["id", "name", "description", "channels", "category", "severity", "action", "score",
                    "mode", "enabled", "condition", "reason", "regulatory_refs", "owner"]
_DEFAULTS = {"enabled": True, "mode": "active", "owner": "Prevención de Fraude"}
ID_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}-[A-Z0-9]{1,10}$")


class ConfigError(ValueError):
    pass


class RuleInput(BaseModel):
    id: str
    name: str = Field(min_length=3, max_length=120)
    description: str = ""
    channels: list[Channel] = Field(min_length=1)
    category: RiskCategory = RiskCategory.FRAUD
    severity: Severity = Severity.MEDIUM
    action: Action = Action.REVIEW
    score: int = Field(ge=0, le=100)
    mode: str = "shadow"
    enabled: bool = True
    condition: str = Field(min_length=1)
    reason: str = ""
    regulatory_refs: list[str] = Field(min_length=1)
    owner: str = "Prevención de Fraude"

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = v.strip().upper()
        if not ID_RE.match(v):
            raise ValueError("El ID debe tener el formato PREFIJO-NÚMERO, por ejemplo USR-001")
        return v

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in ("active", "shadow"):
            raise ValueError("mode debe ser 'active' o 'shadow'")
        return v

    def to_yaml_map(self) -> CommentedMap:
        data = self.model_dump(mode="json")
        data["condition"] = " ".join(data["condition"].split())
        data["reason"] = data["reason"] or data["name"]
        m = CommentedMap()
        for key in RULE_FIELD_ORDER:
            value = data[key]
            if key in ("description",) and not value:
                continue
            m[key] = CommentedSeq(value) if isinstance(value, list) else value
            if key in ("channels", "regulatory_refs"):
                m[key].fa.set_flow_style()
        return m


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _dump(data: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_reference_codes(config_dir: Path) -> dict[str, str]:
    path = config_dir / "referencias_normativas.yaml"
    if not path.exists():
        return {}
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    return dict(data.get("references") or {})


class ConfigEditor:
    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self.rules_dir = self.config_dir / "rules"
        self.params_path = self.config_dir / "parameters.yaml"
        self._lock = threading.Lock()

    # ============================================================ reglas
    def _load_rule_files(self) -> dict[str, Any]:
        docs = {}
        for file in sorted(self.rules_dir.glob("*.yaml")):
            docs[file.name] = _yaml().load(file.read_text(encoding="utf-8")) or CommentedMap()
        return docs

    @staticmethod
    def _find(docs: dict[str, Any], rule_id: str) -> tuple[str, int] | None:
        for name, doc in docs.items():
            for idx, item in enumerate(doc.get("rules") or []):
                if str(item.get("id")) == rule_id:
                    return name, idx
        return None

    def rule_source(self, rule_id: str) -> str | None:
        found = self._find(self._load_rule_files(), rule_id)
        return found[0] if found else None

    def create_rule(self, rule: RuleInput, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            docs = self._load_rule_files()
            if self._find(docs, rule.id):
                raise ConfigError(f"Ya existe una regla con ID {rule.id}")
            doc = docs.setdefault(CONSOLE_FILE, CommentedMap())
            if "rules" not in doc or doc["rules"] is None:
                doc["rules"] = CommentedSeq()
            doc["rules"].append(rule.to_yaml_map())
            self._validate_and_write(docs, {CONSOLE_FILE}, params)
            return {"file": CONSOLE_FILE, "after": rule.model_dump(mode="json")}

    def update_rule(self, rule_id: str, rule: RuleInput, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            docs = self._load_rule_files()
            found = self._find(docs, rule_id)
            if not found:
                raise ConfigError(f"No existe la regla {rule_id}")
            if rule.id != rule_id:
                raise ConfigError("No se puede cambiar el ID de una regla; duplicala con un ID nuevo")
            file, idx = found
            current = docs[file]["rules"][idx]
            before = copy.deepcopy(dict(current))
            new = rule.to_yaml_map()
            # Actualiza en el lugar para conservar orden y comentarios del archivo.
            for key in list(current.keys()):
                if key not in new and key in RULE_FIELD_ORDER:
                    del current[key]
            for key, value in new.items():
                if key not in current and _DEFAULTS.get(key, object()) == value:
                    continue  # no agregar campos implícitos que no estaban en el archivo
                if key == "condition" and " ".join(str(current.get(key, "")).split()) == value:
                    continue  # sin cambios: se conserva el formato multilínea original
                current[key] = value
            self._validate_and_write(docs, {file}, params)
            return {"file": file, "before": _plain(before), "after": rule.model_dump(mode="json")}

    def delete_rule(self, rule_id: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            docs = self._load_rule_files()
            found = self._find(docs, rule_id)
            if not found:
                raise ConfigError(f"No existe la regla {rule_id}")
            file, idx = found
            if file != CONSOLE_FILE:
                raise ConfigError("Las reglas del catálogo base no se eliminan: desactivala o pasala a modo sombra")
            before = _plain(dict(docs[file]["rules"][idx]))
            del docs[file]["rules"][idx]
            self._validate_and_write(docs, {file}, params)
            return {"file": file, "before": before}

    def validate_rule(self, rule: RuleInput, params: dict[str, Any], existing_id: str | None = None) -> None:
        """Valida una regla borrador contra la configuración completa sin escribir."""
        docs = self._load_rule_files()
        if existing_id:
            found = self._find(docs, existing_id)
            if found:
                del docs[found[0]]["rules"][found[1]]
        elif self._find(docs, rule.id):
            raise ConfigError(f"Ya existe una regla con ID {rule.id}")
        doc = docs.setdefault(CONSOLE_FILE, CommentedMap())
        if not doc.get("rules"):
            doc["rules"] = CommentedSeq()
        doc["rules"].append(rule.to_yaml_map())
        self._check(docs, params)

    def _check(self, docs: dict[str, Any], params: dict[str, Any]) -> RuleSet:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_rules = Path(tmp) / "rules"
            tmp_rules.mkdir()
            for name, doc in docs.items():
                if doc.get("rules") is None and name == CONSOLE_FILE:
                    continue
                text = _dump(doc)
                if name == CONSOLE_FILE and not text.startswith("#"):
                    text = CONSOLE_HEADER + text
                (tmp_rules / name).write_text(text, encoding="utf-8")
            lists = ListManager.from_directory(self.config_dir / "lists")
            try:
                ruleset = RuleSet.load(tmp_rules, lists)
            except RuleSetError as exc:
                raise ConfigError(str(exc)) from exc
        known_refs = load_reference_codes(self.config_dir)
        known_lists = set(lists.summary())
        for rule in ruleset.rules:
            refs = references(rule.condition.source)
            missing = [p for p in refs["params"] if p not in params]
            if missing:
                raise ConfigError(f"{rule.id}: parámetro inexistente {', '.join('p.' + m for m in missing)}")
            bad_lists = [x for x in refs["lists"] if x not in known_lists]
            if bad_lists:
                raise ConfigError(f"{rule.id}: lista inexistente {', '.join(bad_lists)}")
            if known_refs:
                bad_refs = [r for r in rule.regulatory_refs if r not in known_refs]
                if bad_refs:
                    raise ConfigError(f"{rule.id}: referencia normativa desconocida {', '.join(bad_refs)}")
        return ruleset

    def _validate_and_write(self, docs: dict[str, Any], changed: set[str], params: dict[str, Any]) -> None:
        self._check(docs, params)
        for name in changed:
            path = self.rules_dir / name
            doc = docs[name]
            if name == CONSOLE_FILE and not doc.get("rules"):
                if path.exists():
                    path.unlink()
                continue
            text = _dump(doc)
            if name == CONSOLE_FILE and not text.startswith("#"):
                text = CONSOLE_HEADER + text
            _atomic_write(path, text)

    # ======================================================== parámetros
    def describe_params(self) -> list[dict[str, Any]]:
        """Lista plana de parámetros editables con sección y descripción
        tomadas de los comentarios del archivo."""
        text = self.params_path.read_text(encoding="utf-8")
        data = _yaml().load(text)
        section, sections, comments = "General", {}, {}
        for line in text.splitlines():
            m = re.match(r"^#\s*-+\s*(.+?)\s*-{3,}\s*$", line)
            if m:
                section = m.group(1)
                continue
            m = re.match(r"^(\w+):", line)
            if m:
                sections[m.group(1)] = section
                c = re.search(r"#\s*(.+)$", line)
                if c:
                    comments[m.group(1)] = c.group(1).strip()
        out = []
        for key, value in data.items():
            sec = sections.get(key, "General")
            if isinstance(value, dict):
                for sub, sub_value in value.items():
                    if isinstance(sub_value, dict):
                        for leaf, leaf_value in sub_value.items():
                            desc = _NESTED_DESC.get((key, leaf), comments.get(key, ""))
                            desc = desc.format(channel=_CHANNEL_ES.get(sub, sub))
                            out.append(_param(f"{key}.{sub}.{leaf}", leaf_value, sec, desc))
                    else:
                        out.append(_param(f"{key}.{sub}", sub_value, sec, comments.get(key, "")))
            else:
                out.append(_param(key, value, sec, comments.get(key, "")))
        return out

    def update_params(self, changes: dict[str, Any], lists_dir: Path | None = None) -> dict[str, Any]:
        with self._lock:
            text = self.params_path.read_text(encoding="utf-8")
            data = _yaml().load(text)
            before: dict[str, Any] = {}
            for path, raw in changes.items():
                parent, leaf = _resolve(data, path)
                old = parent[leaf]
                parent[leaf] = _coerce(path, old, raw)
                before[path] = _plain(old)
            _validate_params(_plain(data))
            new_params = _plain(data)
            # Las reglas deben seguir cargando con los parámetros nuevos
            self._check(self._load_rule_files(), new_params)
            _atomic_write(self.params_path, _dump(data))
            return {"before": before, "after": {k: _plain(_resolve(data, k)[0][_resolve(data, k)[1]]) for k in changes}}

    def preview_params(self, changes: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        data = copy.deepcopy(params)
        for path, raw in changes.items():
            parent, leaf = _resolve(data, path)
            parent[leaf] = _coerce(path, parent[leaf], raw)
        _validate_params(data)
        return data


# ------------------------------------------------------------ helpers
_CHANNEL_ES = {"ACQUIRING": "Adquirencia", "CASH_IN": "Cash-in", "CASH_OUT": "Cash-out"}
_NESTED_DESC = {
    ("decision_thresholds", "review"): "{channel}: score combinado a partir del cual la operación va a revisión",
    ("decision_thresholds", "decline"): "{channel}: score combinado a partir del cual la operación se rechaza",
    ("fallback", "approve_below_ars"): "{channel}: si el motor falla, se aprueban las operaciones por debajo de este monto",
    ("fallback", "otherwise"): "{channel}: si el motor falla, acción para el resto (APPROVE, REVIEW o DECLINE)",
}


def _param(name: str, value: Any, section: str, comment: str) -> dict[str, Any]:
    kind = "lista" if isinstance(value, list) else "texto" if isinstance(value, str) else \
        "sí/no" if isinstance(value, bool) else "número"
    return {"name": name, "value": _plain(value), "section": section, "description": comment, "type": kind}


def _resolve(data: Any, path: str) -> tuple[Any, str]:
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"Parámetro inexistente: {path}")
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        raise ConfigError(f"Parámetro inexistente: {path}")
    return node, parts[-1]


def _coerce(path: str, old: Any, raw: Any) -> Any:
    try:
        if isinstance(old, bool):
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("true", "1", "si", "sí", "yes")
        if isinstance(old, int) and not isinstance(old, bool):
            value = float(str(raw).replace(",", "."))
            return int(value) if value.is_integer() else value
        if isinstance(old, float):
            return float(str(raw).replace(",", "."))
        if isinstance(old, list):
            items = raw if isinstance(raw, list) else [x.strip() for x in str(raw).split(",") if x.strip()]
            proto = old[0] if old else ""
            return CommentedSeq([_coerce(path, proto, x) for x in items]) if old else CommentedSeq(items)
        return str(raw).strip()
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Valor inválido para {path}: {raw!r}") from exc


def _validate_params(p: dict[str, Any]) -> None:
    for key, value in p.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value < 0:
            raise ConfigError(f"{key} no puede ser negativo")
    for channel, th in (p.get("decision_thresholds") or {}).items():
        if not (0 <= th["review"] <= 100 and 0 <= th["decline"] <= 100):
            raise ConfigError(f"Umbrales de {channel} deben estar entre 0 y 100")
        if th["review"] > th["decline"]:
            raise ConfigError(f"En {channel} el umbral de revisión no puede superar al de rechazo")
    for channel, fb in (p.get("fallback") or {}).items():
        if fb.get("otherwise") not in ("APPROVE", "REVIEW", "DECLINE"):
            raise ConfigError(f"fallback.{channel}.otherwise debe ser APPROVE, REVIEW o DECLINE")
    nh = p.get("night_hours")
    if nh is not None and (len(nh) != 2 or not all(0 <= h <= 24 for h in nh)):
        raise ConfigError("night_hours debe tener dos horas entre 0 y 24, ej. 0, 6")
    for key in ("passthrough_ratio", "structuring_band_pct", "merchant_decline_ratio_max", "merchant_foreign_ratio_max"):
        if key in p and not 0 <= p[key] <= 1:
            raise ConfigError(f"{key} es una proporción: debe estar entre 0 y 1")


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, str):
        return str(value)
    return value

