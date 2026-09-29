"""Carga, validación y evaluación de reglas declarativas (YAML).

Cada regla es versionada (hash del contenido del ruleset) para trazabilidad:
toda decisión registra qué versión de reglas la produjo, requisito de
auditoría y de gestión de cambios (Com. "A" 7724 BCRA).
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from ..lists import ListManager
from ..models import Action, Channel, RiskCategory, RuleHit, Severity
from .expression import CompiledExpression, ExpressionError

log = logging.getLogger(__name__)

ROOTS = {"txn", "feat", "p"}


def format_number(v: float) -> str:
    """Formato argentino: 4.000.000 / 4.000.000,50 / 4,99."""
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(v):,}".replace(",", ".")
_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def build_functions(lists: ListManager) -> dict[str, Callable[..., Any]]:
    def _num(fn):
        def wrapper(*args):
            if any(a is None for a in args):
                return None
            return fn(*args)
        return wrapper

    return {
        "in_list": lambda name, value: lists.contains(name, value),
        "prefix_in_list": lambda name, value: lists.prefix_match(name, value),
        "abs": _num(abs),
        "min": _num(min),
        "max": _num(max),
        "round": _num(round),
        "len": lambda v: len(v) if v is not None else 0,
        "coalesce": lambda *args: next((a for a in args if a is not None), None),
        "startswith": lambda s, prefix: isinstance(s, str) and s.startswith(prefix),
        "upper": lambda s: s.upper() if isinstance(s, str) else s,
        "between": lambda x, lo, hi: x is not None and lo is not None and hi is not None and lo <= x <= hi,
    }


@dataclass
class Rule:
    id: str
    name: str
    description: str
    channels: list[Channel]
    category: RiskCategory
    severity: Severity
    action: Action
    score: int
    condition: CompiledExpression
    reason_template: str
    mode: str = "active"  # active | shadow (champion/challenger, sin impacto)
    enabled: bool = True
    regulatory_refs: list[str] = field(default_factory=list)
    reason_parts: list[tuple[str, CompiledExpression]] = field(default_factory=list)
    owner: str = "Prevención de Fraude"
    source: str = ""

    def applies_to(self, channel: Channel) -> bool:
        return self.enabled and channel in self.channels

    def render_reason(self, context: dict[str, Any]) -> str:
        text = self.reason_template
        for placeholder, expr in self.reason_parts:
            try:
                value = expr.evaluate(context)
            except Exception:  # noqa: BLE001
                value = "?"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = format_number(value)
            text = text.replace("{" + placeholder + "}", str(value))
        return text


class RuleSetError(ValueError):
    pass


class RuleSet:
    def __init__(self, rules: list[Rule], version: str):
        self.rules = rules
        self.version = version
        self._by_channel = {c: [r for r in rules if r.applies_to(c)] for c in Channel}

    def for_channel(self, channel: Channel) -> list[Rule]:
        return self._by_channel[channel]

    @classmethod
    def load(cls, path: str | Path, lists: ListManager) -> "RuleSet":
        functions = build_functions(lists)
        files = sorted(Path(path).glob("*.yaml"))
        if not files:
            raise RuleSetError(f"No se encontraron reglas en {path}")
        digest = hashlib.sha256()
        rules: list[Rule] = []
        seen: set[str] = set()
        for file in files:
            raw = file.read_bytes()
            digest.update(raw)
            doc = yaml.safe_load(raw) or {}
            for item in doc.get("rules", []):
                rule = cls._parse(item, functions, file.name)
                if rule.id in seen:
                    raise RuleSetError(f"ID de regla duplicado: {rule.id}")
                seen.add(rule.id)
                rules.append(rule)
        return cls(rules, version=digest.hexdigest()[:12])

    @staticmethod
    def _parse(item: dict[str, Any], functions: dict[str, Callable[..., Any]], source: str) -> Rule:
        try:
            rid = item["id"]
            condition = CompiledExpression(item["condition"], functions, ROOTS)
            reason = item.get("reason", item["name"])
            parts = [(ph, CompiledExpression(ph, functions, ROOTS)) for ph in _PLACEHOLDER.findall(reason)]
            action = Action(item.get("action", "REVIEW"))
            score = int(item.get("score", 0))
            if not 0 <= score <= 100:
                raise RuleSetError(f"{rid}: score debe estar entre 0 y 100")
            mode = item.get("mode", "active")
            if mode not in ("active", "shadow"):
                raise RuleSetError(f"{rid}: mode inválido '{mode}'")
            return Rule(
                id=rid,
                name=item["name"],
                description=item.get("description", ""),
                channels=[Channel(c) for c in item["channels"]],
                category=RiskCategory(item.get("category", "FRAUD")),
                severity=Severity(item.get("severity", "MEDIUM")),
                action=action,
                score=score,
                condition=condition,
                reason_template=reason,
                reason_parts=parts,
                mode=mode,
                enabled=bool(item.get("enabled", True)),
                regulatory_refs=list(item.get("regulatory_refs", [])),
                owner=item.get("owner", "Prevención de Fraude"),
                source=source,
            )
        except KeyError as exc:
            raise RuleSetError(f"{source}: falta el campo obligatorio {exc} en regla {item.get('id', '?')}") from exc
        except (ExpressionError, ValueError) as exc:
            raise RuleSetError(f"{source}: regla {item.get('id', '?')}: {exc}") from exc


@dataclass
class EvaluationResult:
    hits: list[RuleHit]
    shadow_hits: list[RuleHit]
    errors: list[str]


def evaluate_rules(ruleset: RuleSet, channel: Channel, context: dict[str, Any]) -> EvaluationResult:
    hits: list[RuleHit] = []
    shadow: list[RuleHit] = []
    errors: list[str] = []
    for rule in ruleset.for_channel(channel):
        try:
            matched = bool(rule.condition.evaluate(context))
        except Exception as exc:  # noqa: BLE001 - una regla rota no debe tumbar la evaluación
            log.exception("Error evaluando regla %s", rule.id)
            errors.append(f"{rule.id}: {exc}")
            continue
        if not matched:
            continue
        hit = RuleHit(
            rule_id=rule.id,
            name=rule.name,
            category=rule.category,
            severity=rule.severity,
            action=rule.action,
            score=rule.score,
            mode=rule.mode,
            reason=rule.render_reason(context),
            regulatory_refs=rule.regulatory_refs,
        )
        (hits if rule.mode == "active" else shadow).append(hit)
    return EvaluationResult(hits=hits, shadow_hits=shadow, errors=errors)
