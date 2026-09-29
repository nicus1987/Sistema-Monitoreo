"""Orquestador del motor: features -> reglas -> scoring -> decisión -> auditoría -> alertas."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import zlib
from datetime import datetime, timezone
from collections import OrderedDict, defaultdict, deque
from pathlib import Path
from typing import Any, Callable

import yaml

from .alerts import AlertManager
from .audit import AuditLog
from .config_editor import ConfigEditor, RuleInput
from .engine.rules import Rule, RuleSet, build_functions, evaluate_rules
from .features.extractor import FeatureExtractor
from .features.store import BehaviorStore, InMemoryBehaviorStore
from .lists import ListManager
from .models import Action, Channel, Decision, RuleHit, Transaction

log = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path(os.getenv("MONITOREO_CONFIG_DIR") or Path(__file__).resolve().parents[2] / "config")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def combine_scores(hits: list[RuleHit]) -> int:
    """Combinación probabilística (noisy-OR): varias señales débiles suman,
    pero el score nunca supera 100 y una señal fuerte domina."""
    remaining = 1.0
    for h in hits:
        remaining *= 1 - h.score / 100
    return round((1 - remaining) * 100)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[str, float] = defaultdict(float)
        self.latencies: list[float] = []

    def inc(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self.counters[name] += value

    def observe_latency(self, ms: float) -> None:
        with self._lock:
            self.latencies.append(ms)
            if len(self.latencies) > 10000:
                self.latencies = self.latencies[-10000:]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            lat = sorted(self.latencies)
            counters = dict(self.counters)

        def pct(p: float) -> float:
            return round(lat[min(int(len(lat) * p), len(lat) - 1)], 3) if lat else 0.0

        return {"counters": counters, "latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "p99": pct(0.99)}}

    def prometheus(self) -> str:
        snap = self.snapshot()
        lines = []
        for name, value in sorted(snap["counters"].items()):
            metric, _, labels = name.partition("|")
            label_txt = "{" + labels + "}" if labels else ""
            lines.append(f"monitoreo_{metric}{label_txt} {value}")
        for q, v in snap["latency_ms"].items():
            lines.append(f'monitoreo_latency_ms{{quantile="{q}"}} {v}')
        return "\n".join(lines) + "\n"


class MonitoringService:
    def __init__(
        self,
        config_dir: str | Path = DEFAULT_CONFIG_DIR,
        store: BehaviorStore | None = None,
        audit_path: str | Path | None = None,
        recent_buffer: int = 5000,
    ):
        self.config_dir = Path(config_dir)
        self.store = store or InMemoryBehaviorStore()
        self.audit = AuditLog(audit_path)
        self.alerts = AlertManager()
        self.metrics = Metrics()
        self._listeners: list[Callable[[Decision], None]] = []
        self._locks = [threading.Lock() for _ in range(256)]
        self._reload_lock = threading.Lock()
        self._idempotency: OrderedDict[str, Decision] = OrderedDict()
        self._idem_lock = threading.Lock()
        # Evaluaciones recientes para probar reglas y parámetros antes de activarlos
        self._recent: deque[dict[str, Any]] = deque(maxlen=recent_buffer)
        self.editor = ConfigEditor(self.config_dir)
        self.reload()

    # ----------------------------------------------------------- config
    def reload(self) -> dict[str, Any]:
        """Recarga parámetros, listas y reglas de forma atómica. Si algo es
        inválido, se mantiene la configuración anterior (no se degrada)."""
        with self._reload_lock:
            params_raw = (self.config_dir / "parameters.yaml").read_bytes()
            params = yaml.safe_load(params_raw)
            lists = ListManager.from_directory(self.config_dir / "lists")
            ruleset = RuleSet.load(self.config_dir / "rules", lists)
            # La versión identifica la configuración completa (reglas + parámetros + listas):
            # cada decisión queda asociada a la configuración exacta que la produjo.
            ruleset.version = hashlib.sha256(
                ruleset.version.encode() + params_raw + lists.version.encode()).hexdigest()[:12]
            self.params, self.lists, self.ruleset = params, lists, ruleset
            self.extractor = FeatureExtractor(self.store, params)
        info = {"ruleset_version": ruleset.version, "rules": len(ruleset.rules), "lists": lists.summary()}
        self.audit.append("CONFIG_RELOAD", info)
        log.info("Configuración cargada: %s", info)
        return info

    def subscribe(self, listener: Callable[[Decision], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    # --------------------------------------------------------- evaluate
    def evaluate(self, txn: Transaction) -> Decision:
        cached = self._cached(txn.transaction_id)
        if cached is not None:
            self.metrics.inc("idempotent_replays_total")
            return cached

        start = time.perf_counter()
        entity = txn.primary_entity or txn.transaction_id
        lock = self._locks[zlib.crc32(entity.encode()) % len(self._locks)]
        with lock:
            cached = self._cached(txn.transaction_id)  # re-chequeo: reintentos concurrentes
            if cached is not None:
                return cached
            decision = self._evaluate_locked(txn, start)
        self._remember(decision)

        self.metrics.inc(f"decisions_total|channel=\"{txn.channel.value}\",action=\"{decision.action.value}\"")
        for h in decision.hits:
            self.metrics.inc(f"rule_hits_total|rule=\"{h.rule_id}\"")
        for h in decision.shadow_hits:
            self.metrics.inc(f"shadow_rule_hits_total|rule=\"{h.rule_id}\"")
        self.metrics.observe_latency(decision.latency_ms)
        budget = self.params.get("latency_budget_ms", 100)
        if decision.latency_ms > budget:
            self.metrics.inc("latency_budget_exceeded_total")
            log.warning("Evaluación de %s excedió presupuesto: %.1fms", txn.transaction_id, decision.latency_ms)

        for listener in list(self._listeners):
            try:
                listener(decision)
            except Exception:  # noqa: BLE001
                log.exception("Listener falló")
        return decision

    def _evaluate_locked(self, txn: Transaction, start: float) -> Decision:
        ruleset, params = self.ruleset, self.params
        features: dict[str, Any] = {}
        try:
            features = self.extractor.extract(txn)
            context = {"txn": txn.model_dump(mode="json"), "feat": features, "p": params}
            result = evaluate_rules(ruleset, txn.channel, context)
            if result.errors:
                self.metrics.inc("rule_errors_total", len(result.errors))
                features["_rule_errors"] = result.errors
            action, score = self._decide(txn.channel, result.hits)
            self._recent.append({"transaction_id": txn.transaction_id, "channel": txn.channel,
                                 "amount_ars": txn.amount_ars, "txn": context["txn"], "feat": dict(features),
                                 "action": action, "score": score, "hits": result.hits})
            decision = Decision(
                transaction_id=txn.transaction_id,
                channel=txn.channel,
                action=action,
                risk_score=score,
                reason_codes=[h.rule_id for h in result.hits],
                hits=result.hits,
                shadow_hits=result.shadow_hits,
                features=features,
                ruleset_version=ruleset.version,
            )
        except Exception as exc:  # noqa: BLE001 - política de contingencia
            log.exception("Fallo del motor evaluando %s; se aplica fallback", txn.transaction_id)
            self.metrics.inc("engine_failures_total")
            decision = self._fallback(txn, ruleset.version, str(exc))

        decision.amount_ars = txn.amount_ars
        decision.latency_ms = round((time.perf_counter() - start) * 1000, 3)
        try:
            self.extractor.record(txn, decision.action, features)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo registrar historia de %s", txn.transaction_id)

        alert = self.alerts.create_from_decision(decision, txn.customer.customer_id if txn.customer else None)
        if alert:
            decision.alert_id = alert.alert_id
        self.audit.append("DECISION", {
            "transaction": txn.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
        })
        return decision

    def _decide(self, channel: Channel, hits: list[RuleHit],
                params: dict[str, Any] | None = None) -> tuple[Action, int]:
        score = combine_scores(hits)
        thresholds = (params or self.params)["decision_thresholds"][channel.value]
        action = max((h.action for h in hits), key=lambda a: a.weight, default=Action.APPROVE)
        if score >= thresholds["decline"]:
            by_score = Action.DECLINE
        elif score >= thresholds["review"]:
            by_score = Action.REVIEW
        else:
            by_score = Action.APPROVE
        return max(action, by_score, key=lambda a: a.weight), score

    def _fallback(self, txn: Transaction, version: str, error: str) -> Decision:
        """Contingencia ante falla del motor (plan de continuidad): se aprueba
        hasta un monto bajo y se retiene/revisa el resto, según canal."""
        policy = self.params.get("fallback", {}).get(txn.channel.value, {})
        limit = policy.get("approve_below_ars", 0)
        action = Action.APPROVE if (txn.amount_ars or 0) < limit else Action(policy.get("otherwise", "REVIEW"))
        return Decision(
            transaction_id=txn.transaction_id,
            channel=txn.channel,
            action=action,
            risk_score=0,
            reason_codes=["ENGINE_FALLBACK"],
            hits=[],
            features={"_error": error},
            ruleset_version=version,
            fallback=True,
        )

    # ------------------------------------------------------- idempotency
    def _cached(self, txn_id: str) -> Decision | None:
        with self._idem_lock:
            return self._idempotency.get(txn_id)

    def _remember(self, decision: Decision) -> None:
        with self._idem_lock:
            self._idempotency[decision.transaction_id] = decision
            while len(self._idempotency) > 100_000:
                self._idempotency.popitem(last=False)

    # ================================================ gestión de reglas
    def compile_draft(self, rule: RuleInput) -> Rule:
        """Compila una regla borrador (sin guardarla) para probarla."""
        item = rule.model_dump(mode="json")
        item["reason"] = item["reason"] or item["name"]
        return RuleSet._parse(item, build_functions(self.lists), "borrador")

    def _hit(self, rule: Rule, context: dict[str, Any]) -> RuleHit | None:
        try:
            if not rule.condition.evaluate(context):
                return None
        except Exception:  # noqa: BLE001
            return None
        return RuleHit(rule_id=rule.id, name=rule.name, category=rule.category, severity=rule.severity,
                       action=rule.action, score=rule.score, mode=rule.mode,
                       reason=rule.render_reason(context), regulatory_refs=rule.regulatory_refs)

    def backtest_rule(self, rule: Rule, replace_id: str | None = None, samples: int = 25) -> dict[str, Any]:
        """Aplica la regla sobre las evaluaciones recientes y mide cuántas
        dispararía y cómo cambiarían las decisiones si estuviera ACTIVA."""
        records = [r for r in list(self._recent) if r["channel"] in rule.channels]
        before = {a.value: 0 for a in Action}
        after = {a.value: 0 for a in Action}
        by_channel: dict[str, dict[str, int]] = {}
        matches, changed, sample_rows = 0, 0, []
        for r in records:
            ctx = {"txn": r["txn"], "feat": r["feat"], "p": self.params}
            hit = self._hit(rule, ctx)
            base = [h for h in r["hits"] if h.rule_id != (replace_id or rule.id)]
            base_action, base_score = self._decide(r["channel"], base)
            new_hits = base + ([hit.model_copy(update={"mode": "active"})] if hit else [])
            new_action, new_score = self._decide(r["channel"], new_hits)
            ch = by_channel.setdefault(r["channel"].value, {"evaluated": 0, "matched": 0})
            ch["evaluated"] += 1
            before[base_action.value] += 1
            after[new_action.value] += 1
            if hit:
                matches += 1
                ch["matched"] += 1
                if new_action != base_action:
                    changed += 1
                if len(sample_rows) < samples:
                    sample_rows.append({
                        "transaction_id": r["transaction_id"], "channel": r["channel"].value,
                        "amount_ars": r["amount_ars"], "reason": hit.reason,
                        "before": base_action.value, "after": new_action.value,
                        "score_before": base_score, "score_after": new_score,
                        "other_rules": [h.rule_id for h in base],
                    })
        return {
            "evaluated": len(records), "matched": matches,
            "match_rate": round(100 * matches / len(records), 2) if records else 0.0,
            "changed": changed, "by_channel": by_channel,
            "decisions_before": before, "decisions_after": after, "samples": sample_rows,
            "buffer_size": len(self._recent),
        }

    def test_transaction(self, rule: Rule, txn: Transaction) -> dict[str, Any]:
        """Evalúa la regla contra una transacción puntual, con la historia real
        del cliente/tarjeta pero SIN registrarla ni generar alertas."""
        features = self.extractor.extract(txn)
        ctx = {"txn": txn.model_dump(mode="json"), "feat": features, "p": self.params}
        applies = txn.channel in rule.channels
        hit = self._hit(rule, ctx) if applies else None
        current = evaluate_rules(self.ruleset, txn.channel, ctx)
        base = [h for h in current.hits if h.rule_id != rule.id]
        base_action, base_score = self._decide(txn.channel, base)
        new_action, new_score = self._decide(txn.channel, base + ([hit] if hit else []))
        return {
            "applies_to_channel": applies, "matched": hit is not None,
            "reason": hit.reason if hit else None,
            "decision_without_rule": {"action": base_action.value, "score": base_score, "rules": [h.rule_id for h in base]},
            "decision_with_rule": {"action": new_action.value, "score": new_score},
            "features": features,
        }

    def preview_params(self, changes: dict[str, Any], samples: int = 25) -> dict[str, Any]:
        """Re-evalúa las operaciones recientes con parámetros modificados y
        compara contra los parámetros actuales."""
        from .features.catalog import FEATURE_PARAMS

        new_params = self.editor.preview_params(changes, self.params)
        rules = [r for r in self.ruleset.rules if r.enabled and r.mode == "active"]
        before = {a.value: 0 for a in Action}
        after = {a.value: 0 for a in Action}
        changed, rows = 0, []
        hit_delta: dict[str, int] = {}
        records = list(self._recent)
        for r in records:
            results = []
            for params in (self.params, new_params):
                ctx = {"txn": r["txn"], "feat": r["feat"], "p": params}
                hits = [h for rule in rules if r["channel"] in rule.channels for h in [self._hit(rule, ctx)] if h]
                results.append((hits, *self._decide(r["channel"], hits, params)))
            (h0, a0, s0), (h1, a1, s1) = results
            before[a0.value] += 1
            after[a1.value] += 1
            ids0, ids1 = {h.rule_id for h in h0}, {h.rule_id for h in h1}
            for rid in ids1 - ids0:
                hit_delta[rid] = hit_delta.get(rid, 0) + 1
            for rid in ids0 - ids1:
                hit_delta[rid] = hit_delta.get(rid, 0) - 1
            if a0 != a1:
                changed += 1
                if len(rows) < samples:
                    rows.append({"transaction_id": r["transaction_id"], "channel": r["channel"].value,
                                 "amount_ars": r["amount_ars"], "before": a0.value, "after": a1.value,
                                 "score_before": s0, "score_after": s1,
                                 "rules_added": sorted(ids1 - ids0), "rules_removed": sorted(ids0 - ids1)})
        return {
            "evaluated": len(records), "changed": changed,
            "decisions_before": before, "decisions_after": after,
            "rule_hit_delta": dict(sorted(hit_delta.items(), key=lambda kv: -abs(kv[1]))),
            "samples": rows,
            "approximate": sorted(set(changes) & FEATURE_PARAMS | {c for c in changes if c.split(".")[0] in FEATURE_PARAMS}),
        }

    def create_rule(self, rule: RuleInput, user: str) -> dict[str, Any]:
        result = self.editor.create_rule(rule, self.params)
        info = self.reload()
        self.audit.append("RULE_CREATED", {"at": _now(), "user": user, "rule_id": rule.id, **result, **info})
        return {**result, **info}

    def update_rule(self, rule_id: str, rule: RuleInput, user: str) -> dict[str, Any]:
        result = self.editor.update_rule(rule_id, rule, self.params)
        info = self.reload()
        self.audit.append("RULE_UPDATED", {"at": _now(), "user": user, "rule_id": rule_id, **result, **info})
        return {**result, **info}

    def delete_rule(self, rule_id: str, user: str) -> dict[str, Any]:
        result = self.editor.delete_rule(rule_id, self.params)
        info = self.reload()
        self.audit.append("RULE_DELETED", {"at": _now(), "user": user, "rule_id": rule_id, **result, **info})
        return {**result, **info}

    def update_params(self, changes: dict[str, Any], user: str) -> dict[str, Any]:
        result = self.editor.update_params(changes)
        info = self.reload()
        self.audit.append("PARAMS_UPDATED", {"at": _now(), "user": user, **result, **info})
        return {**result, **info}

    def change_history(self, limit: int = 100) -> list[dict[str, Any]]:
        kinds = {"RULE_CREATED", "RULE_UPDATED", "RULE_DELETED", "PARAMS_UPDATED"}
        items = [r["payload"] | {"type": r["type"]} for r in self.audit.records() if r["type"] in kinds]
        return list(reversed(items))[:limit]
