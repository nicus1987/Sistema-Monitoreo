"""Orquestador del motor: features -> reglas -> scoring -> decisión -> auditoría -> alertas."""

from __future__ import annotations

import logging
import threading
import time
import zlib
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Callable

import yaml

from .alerts import AlertManager
from .audit import AuditLog
from .engine.rules import RuleSet, evaluate_rules
from .features.extractor import FeatureExtractor
from .features.store import BehaviorStore, InMemoryBehaviorStore
from .lists import ListManager
from .models import Action, Channel, Decision, RuleHit, Transaction

log = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


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
        self.reload()

    # ----------------------------------------------------------- config
    def reload(self) -> dict[str, Any]:
        """Recarga parámetros, listas y reglas de forma atómica. Si algo es
        inválido, se mantiene la configuración anterior (no se degrada)."""
        with self._reload_lock:
            params = yaml.safe_load((self.config_dir / "parameters.yaml").read_text(encoding="utf-8"))
            lists = ListManager.from_directory(self.config_dir / "lists")
            ruleset = RuleSet.load(self.config_dir / "rules", lists)
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

    def _decide(self, channel: Channel, hits: list[RuleHit]) -> tuple[Action, int]:
        score = combine_scores(hits)
        thresholds = self.params["decision_thresholds"][channel.value]
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
