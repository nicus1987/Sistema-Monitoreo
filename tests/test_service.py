import json
import shutil

import pytest

from monitoreo import simulator as sim
from monitoreo.models import Action, Transaction
from monitoreo.service import DEFAULT_CONFIG_DIR, MonitoringService


def txn(amount=1000, **kw):
    return Transaction.model_validate(sim.cash("CASH_OUT", sim.customer("CUST-1"), amount, "CBU-1", **kw))


def test_idempotent_by_transaction_id(service):
    t = txn()
    d1, d2 = service.evaluate(t), service.evaluate(t)
    assert d1 is d2
    assert service.metrics.snapshot()["counters"]["idempotent_replays_total"] == 1


def test_shadow_rules_do_not_affect_decision(service):
    t = Transaction.model_validate(sim.cash("CASH_IN", sim.customer("CUST-R"), 600_000, "EF", method="CASH"))
    d = service.evaluate(t)
    assert "CIN-015" in [h.rule_id for h in d.shadow_hits]
    assert "CIN-015" not in d.reason_codes
    assert d.action == Action.APPROVE


def test_fallback_when_engine_fails(service, monkeypatch):
    def boom(_):
        raise RuntimeError("feature store caído")
    monkeypatch.setattr(service.extractor, "extract", boom)
    small = service.evaluate(txn(amount=1000))
    big = Transaction.model_validate(sim.cash("CASH_OUT", sim.customer("CUST-2"), 5_000_000, "CBU-2"))
    big_d = service.evaluate(big)
    assert small.fallback and small.action == Action.APPROVE
    assert big_d.fallback and big_d.action == Action.REVIEW
    assert "ENGINE_FALLBACK" in big_d.reason_codes


def test_audit_chain_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"
    svc = MonitoringService(DEFAULT_CONFIG_DIR, audit_path=path)
    for _ in range(3):
        svc.evaluate(txn())
    assert svc.audit.verify() == (True, None)
    lines = path.read_text().splitlines()
    rec = json.loads(lines[2])
    rec["payload"]["decision"]["action"] = "APPROVE_TAMPERED"
    lines[2] = json.dumps(rec)
    path.write_text("\n".join(lines) + "\n")
    assert svc.audit.verify() == (False, 2)


def test_audit_never_contains_full_pan(service):
    service.evaluate(Transaction.model_validate(sim.acquiring("FP-1", "MER-1", 1000)))
    decision = [r for r in service.audit.records() if r["type"] == "DECISION"][-1]
    assert set(decision["payload"]["transaction"]["card"]) == {"card_fingerprint", "bin", "last4", "issuer_country", "card_type"}


def test_invalid_reload_keeps_previous_config(tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, cfg)
    svc = MonitoringService(cfg)
    version = svc.ruleset.version
    (cfg / "rules" / "99_bad.yaml").write_text("rules:\n  - id: BAD\n    name: x\n    channels: [CASH_IN]\n    condition: 'import os'\n")
    with pytest.raises(Exception):
        svc.reload()
    assert svc.ruleset.version == version
    assert svc.evaluate(txn()).ruleset_version == version


def test_pan_rejected_in_free_text():
    with pytest.raises(ValueError):
        txn(description="pago tarjeta 4507990000001234")


def test_latency_under_budget(service):
    for e in sim.normal_traffic(200):
        service.evaluate(Transaction.model_validate(e))
    assert service.metrics.snapshot()["latency_ms"]["p99"] < service.params["latency_budget_ms"]
