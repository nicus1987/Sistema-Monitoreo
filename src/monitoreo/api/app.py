"""API REST de evaluación en tiempo real, gestión de alertas y observabilidad."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..alerts import AlertStatus, TransitionError
from ..config_editor import ConfigError, RuleInput, load_reference_codes
from ..engine.explain import Explainer, references
from ..engine.expression import ExpressionError
from ..engine.rules import RuleSetError
from ..features.catalog import FEATURE_PARAMS, catalog
from ..models import Decision, Transaction
from ..service import MonitoringService

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


def _keys(env: str) -> set[str]:
    return {k.strip() for k in os.getenv(env, "").split(",") if k.strip()}


def _check(key: str | None, allowed: set[str]) -> None:
    if not allowed:  # modo desarrollo: sin claves configuradas
        return
    if not key or not any(secrets.compare_digest(key, k) for k in allowed):
        raise HTTPException(status_code=401, detail="API key inválida")


def require_client(x_api_key: str | None = Header(default=None)) -> None:
    _check(x_api_key, _keys("MONITOREO_API_KEYS") | _keys("MONITOREO_ADMIN_KEYS"))


def require_admin(x_api_key: str | None = Header(default=None)) -> None:
    _check(x_api_key, _keys("MONITOREO_ADMIN_KEYS"))


class DecisionResponse(BaseModel):
    transaction_id: str
    action: str
    risk_score: int
    reason_codes: list[str]
    reasons: list[str]
    alert_id: str | None
    ruleset_version: str
    latency_ms: float
    fallback: bool
    features: dict[str, Any] | None = None
    shadow_reason_codes: list[str] = []


def to_response(d: Decision, include_features: bool) -> DecisionResponse:
    return DecisionResponse(
        transaction_id=d.transaction_id,
        action=d.action.value,
        risk_score=d.risk_score,
        reason_codes=d.reason_codes,
        reasons=[h.reason for h in d.hits],
        alert_id=d.alert_id,
        ruleset_version=d.ruleset_version,
        latency_ms=d.latency_ms,
        fallback=d.fallback,
        features=d.features if include_features else None,
        shadow_reason_codes=[h.rule_id for h in d.shadow_hits],
    )


class DraftRequest(BaseModel):
    rule: RuleInput
    existing_id: str | None = None


class TestRequest(BaseModel):
    rule: RuleInput
    transaction: Transaction


class ExplainRequest(BaseModel):
    condition: str


class ParamsRequest(BaseModel):
    changes: dict[str, Any]


class TransitionRequest(BaseModel):
    to_status: AlertStatus
    comment: str = ""


def create_app(service: MonitoringService | None = None) -> FastAPI:
    if service is None:
        service = MonitoringService(
            config_dir=os.getenv("MONITOREO_CONFIG_DIR") or Path(__file__).resolve().parents[3] / "config",
            audit_path=os.getenv("MONITOREO_AUDIT_PATH"),
        )
    if not _keys("MONITOREO_API_KEYS") and not _keys("MONITOREO_ADMIN_KEYS"):
        log.warning("API sin autenticación: configure MONITOREO_API_KEYS / MONITOREO_ADMIN_KEYS en producción")

    app = FastAPI(
        title="Sistema de Monitoreo Transaccional",
        description="Motor de reglas de fraude y PLA/FT en tiempo real para adquirencia, cash-in y cash-out.",
        version="0.1.0",
    )
    app.state.service = service
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ------------------------------------------------------- evaluación
    @app.post("/v1/transactions/evaluate", response_model=DecisionResponse, dependencies=[Depends(require_client)])
    def evaluate(txn: Transaction, include_features: bool = Query(False)) -> DecisionResponse:
        return to_response(service.evaluate(txn), include_features)

    @app.post("/v1/transactions/evaluate/batch", response_model=list[DecisionResponse],
              dependencies=[Depends(require_client)])
    def evaluate_batch(txns: list[Transaction]) -> list[DecisionResponse]:
        if len(txns) > 1000:
            raise HTTPException(413, "Máximo 1000 transacciones por lote")
        return [to_response(service.evaluate(t), False) for t in txns]

    # ------------------------------------------------------------ reglas
    def rule_dict(r) -> dict[str, Any]:
        try:
            explanation = Explainer(service.params).explain(r.condition.source)["text"]
        except Exception:  # noqa: BLE001
            explanation = ""
        return {
            "id": r.id, "name": r.name, "description": r.description,
            "channels": [c.value for c in r.channels], "category": r.category.value,
            "severity": r.severity.value, "action": r.action.value, "score": r.score,
            "mode": r.mode, "enabled": r.enabled, "condition": " ".join(r.condition.source.split()),
            "reason": r.reason_template, "regulatory_refs": r.regulatory_refs, "owner": r.owner,
            "source": r.source, "deletable": r.source == "90_consola.yaml", "explanation": explanation,
        }

    def config_error(exc: Exception) -> HTTPException:
        return HTTPException(422, str(exc))

    @app.get("/v1/rules", dependencies=[Depends(require_client)])
    def list_rules() -> dict[str, Any]:
        rs = service.ruleset
        return {"version": rs.version, "rules": [rule_dict(r) for r in rs.rules]}

    @app.get("/v1/rules/catalog", dependencies=[Depends(require_client)])
    def rules_catalog() -> dict[str, Any]:
        """Todo lo necesario para escribir una regla: variables, parámetros,
        listas, funciones y referencias normativas."""
        return {
            **catalog(),
            "params": {k: v for k, v in service.params.items() if not isinstance(v, dict)},
            "lists": service.lists.summary(),
            "regulatory_refs": load_reference_codes(service.config_dir),
            "channels": ["ACQUIRING", "CASH_IN", "CASH_OUT"],
            "categories": ["FRAUD", "AML", "CFT", "OPERATIONAL"],
            "severities": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
            "actions": ["APPROVE", "REVIEW", "DECLINE"],
            "recent_evaluations": len(service._recent),
        }

    @app.post("/v1/rules/explain", dependencies=[Depends(require_client)])
    def explain(body: ExplainRequest) -> dict[str, Any]:
        try:
            return Explainer(service.params).explain(body.condition)
        except SyntaxError as exc:
            raise HTTPException(422, f"Sintaxis inválida: {exc.msg}") from exc

    @app.post("/v1/rules/validate", dependencies=[Depends(require_client)])
    def validate_rule(body: DraftRequest) -> dict[str, Any]:
        try:
            service.editor.validate_rule(body.rule, service.params, body.existing_id)
        except (ConfigError, RuleSetError, ExpressionError) as exc:
            raise config_error(exc) from exc
        return {"valid": True, "explanation": Explainer(service.params).explain(body.rule.condition)}

    @app.post("/v1/rules/backtest", dependencies=[Depends(require_client)])
    def backtest_rule(body: DraftRequest) -> dict[str, Any]:
        try:
            draft = service.compile_draft(body.rule)
        except (RuleSetError, ExpressionError, ValueError) as exc:
            raise config_error(exc) from exc
        missing = [x for x in references(body.rule.condition)["params"] if x not in service.params]
        if missing:
            raise HTTPException(422, "Parámetro inexistente: " + ", ".join("p." + m for m in missing))
        return service.backtest_rule(draft, replace_id=body.existing_id)

    @app.post("/v1/rules/test", dependencies=[Depends(require_client)])
    def test_rule(body: TestRequest) -> dict[str, Any]:
        try:
            draft = service.compile_draft(body.rule)
        except (RuleSetError, ExpressionError, ValueError) as exc:
            raise config_error(exc) from exc
        return service.test_transaction(draft, body.transaction)

    @app.post("/v1/rules", dependencies=[Depends(require_admin)], status_code=201)
    def create_rule(rule: RuleInput, x_user: str = Header(default="consola")) -> dict[str, Any]:
        try:
            return service.create_rule(rule, x_user)
        except (ConfigError, RuleSetError) as exc:
            raise config_error(exc) from exc

    @app.put("/v1/rules/{rule_id}", dependencies=[Depends(require_admin)])
    def update_rule(rule_id: str, rule: RuleInput, x_user: str = Header(default="consola")) -> dict[str, Any]:
        try:
            return service.update_rule(rule_id, rule, x_user)
        except (ConfigError, RuleSetError) as exc:
            raise config_error(exc) from exc

    @app.delete("/v1/rules/{rule_id}", dependencies=[Depends(require_admin)])
    def delete_rule(rule_id: str, x_user: str = Header(default="consola")) -> dict[str, Any]:
        try:
            return service.delete_rule(rule_id, x_user)
        except (ConfigError, RuleSetError) as exc:
            raise config_error(exc) from exc

    # -------------------------------------------------------- parámetros
    @app.get("/v1/params", dependencies=[Depends(require_client)])
    def list_params() -> list[dict[str, Any]]:
        usage: dict[str, list[str]] = {}
        for r in service.ruleset.rules:
            for name in references(r.condition.source)["params"]:
                usage.setdefault(name, []).append(r.id)
        items = service.editor.describe_params()
        for item in items:
            root = item["name"].split(".")[0]
            item["used_by"] = usage.get(item["name"], [])
            item["affects_features"] = root in FEATURE_PARAMS
            item["affects_decision"] = root in ("decision_thresholds", "fallback")
        return items

    @app.post("/v1/params/preview", dependencies=[Depends(require_client)])
    def preview_params(body: ParamsRequest) -> dict[str, Any]:
        try:
            return service.preview_params(body.changes)
        except ConfigError as exc:
            raise config_error(exc) from exc

    @app.put("/v1/params", dependencies=[Depends(require_admin)])
    def update_params(body: ParamsRequest, x_user: str = Header(default="consola")) -> dict[str, Any]:
        if not body.changes:
            raise HTTPException(422, "No hay cambios")
        try:
            return service.update_params(body.changes, x_user)
        except (ConfigError, RuleSetError) as exc:
            raise config_error(exc) from exc

    @app.get("/v1/config/history", dependencies=[Depends(require_client)])
    def config_history(limit: int = Query(100, le=1000)) -> list[dict[str, Any]]:
        return service.change_history(limit)

    @app.post("/v1/admin/reload", dependencies=[Depends(require_admin)])
    def reload(x_user: str = Header(default="admin")) -> dict[str, Any]:
        try:
            info = service.reload()
        except (RuleSetError, OSError, ValueError) as exc:
            raise HTTPException(422, f"Configuración inválida, se mantiene la anterior: {exc}") from exc
        service.audit.append("CONFIG_RELOAD_REQUEST", {"user": x_user, **info})
        return info

    # ----------------------------------------------------------- alertas
    @app.get("/v1/alerts", dependencies=[Depends(require_client)])
    def list_alerts(status: AlertStatus | None = None, limit: int = Query(100, le=1000)):
        return [a.model_dump(mode="json") for a in service.alerts.list(status, limit)]

    @app.get("/v1/alerts/stats", dependencies=[Depends(require_client)])
    def alert_stats():
        return service.alerts.stats()

    @app.get("/v1/alerts/{alert_id}", dependencies=[Depends(require_client)])
    def get_alert(alert_id: str):
        alert = service.alerts.get(alert_id)
        if alert is None:
            raise HTTPException(404, "Alerta inexistente")
        return alert.model_dump(mode="json")

    @app.post("/v1/alerts/{alert_id}/transition", dependencies=[Depends(require_client)])
    def transition(alert_id: str, body: TransitionRequest, x_user: str = Header(...)):
        try:
            alert = service.alerts.transition(alert_id, body.to_status, x_user, body.comment)
        except KeyError as exc:
            raise HTTPException(404, "Alerta inexistente") from exc
        except TransitionError as exc:
            raise HTTPException(409, str(exc)) from exc
        service.audit.append("ALERT_TRANSITION", {"alert_id": alert_id, "user": x_user,
                                                  "to": body.to_status.value, "comment": body.comment})
        return alert.model_dump(mode="json")

    # ---------------------------------------------------- observabilidad
    @app.get("/v1/audit/verify", dependencies=[Depends(require_admin)])
    def audit_verify():
        ok, idx = service.audit.verify()
        return {"integrity_ok": ok, "first_broken_index": idx, "records": len(service.audit.records())}

    @app.get("/health")
    def health():
        return {"status": "ok", "ruleset_version": service.ruleset.version, "rules": len(service.ruleset.rules)}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        return service.metrics.prometheus()

    @app.get("/v1/metrics", dependencies=[Depends(require_client)])
    def metrics_json():
        return {**service.metrics.snapshot(), "alerts": service.alerts.stats()}

    @app.get("/v1/stream/decisions", dependencies=[Depends(require_client)])
    async def stream(request: Request):
        """Server-Sent Events: publica cada decisión en tiempo real (dashboard / SOC)."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)

        def push(d: Decision) -> None:
            payload = json.dumps({
                "transaction_id": d.transaction_id, "channel": d.channel.value, "action": d.action.value,
                "risk_score": d.risk_score, "reason_codes": d.reason_codes,
                "reasons": [h.reason for h in d.hits], "latency_ms": d.latency_ms,
                "amount_ars": d.amount_ars, "evaluated_at": d.evaluated_at.isoformat(), "alert_id": d.alert_id,
            })

            def _put() -> None:
                if not queue.full():
                    queue.put_nowait(payload)
            loop.call_soon_threadsafe(_put)

        unsubscribe = service.subscribe(push)

        async def gen():
            try:
                yield ": conectado\n\n"
                while not await request.is_disconnected():
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"data: {item}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                unsubscribe()

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard():
        return (STATIC / "dashboard.html").read_text(encoding="utf-8")

    return app
