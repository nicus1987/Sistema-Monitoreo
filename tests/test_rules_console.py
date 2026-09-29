"""Consola de reglas y parámetros: entender, probar, crear, editar y auditar."""

import re
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from monitoreo import simulator as sim
from monitoreo.api import create_app
from monitoreo.features.catalog import FEATURES
from monitoreo.models import Transaction
from monitoreo.service import DEFAULT_CONFIG_DIR, MonitoringService

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def svc(tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, cfg)
    s = MonitoringService(cfg)
    for e in sim.all_traffic(200):
        s.evaluate(Transaction.model_validate(e))
    return s


@pytest.fixture
def client(svc, monkeypatch):
    monkeypatch.delenv("MONITOREO_API_KEYS", raising=False)
    monkeypatch.delenv("MONITOREO_ADMIN_KEYS", raising=False)
    return TestClient(create_app(svc))


def rule(**kw):
    base = {
        "id": "USR-001", "name": "Egreso relevante de cuenta reciente", "channels": ["CASH_OUT"],
        "category": "FRAUD", "severity": "MEDIUM", "action": "REVIEW", "score": 40, "mode": "shadow",
        "condition": "feat.account_age_days < 60 and txn.amount_ars >= p.new_account_cashout_ars",
        "reason": "Cuenta de {feat.account_age_days} días egresa ARS {txn.amount_ars}",
        "regulatory_refs": ["BCRA-PUSF"],
    }
    base.update(kw)
    return base


H = {"X-User": "ana"}


def test_every_computed_feature_is_documented(svc):
    computed = set()
    for r in svc._recent:
        computed |= {k for k in r["feat"] if not k.startswith("_")}
    assert computed, "no se registraron evaluaciones"
    assert computed <= set(FEATURES), f"features sin documentar: {sorted(computed - set(FEATURES))}"


def test_every_rule_condition_uses_documented_features(svc):
    for r in svc.ruleset.rules:
        for name in re.findall(r"\bfeat\.(\w+)", r.condition.source):
            assert name in FEATURES, f"{r.id} usa feat.{name} sin documentar"


def test_regulatory_reference_catalog_matches_docs():
    refs = yaml.safe_load((ROOT / "config" / "referencias_normativas.yaml").read_text(encoding="utf-8"))["references"]
    doc = (ROOT / "docs" / "marco_normativo.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([A-Z0-9-]+)` \|", doc, flags=re.M))
    assert set(refs) == documented


def test_rules_listing_includes_explanation(client):
    rules = {r["id"]: r for r in client.get("/v1/rules").json()["rules"]}
    cout1 = rules["COUT-001"]
    assert "passthrough_minutes (60)" in cout1["explanation"]
    assert cout1["deletable"] is False and cout1["source"] == "30_cash_out.yaml"


def test_explain_endpoint(client):
    r = client.post("/v1/rules/explain", json={"condition": "not feat.card_not_present and txn.amount_ars >= p.high_amount_ars / 2"})
    assert r.status_code == 200
    body = r.json()
    assert body["clauses"][0] == "Tarjeta no presente: no"
    assert "(= 1.000.000)" in body["clauses"][1]
    assert client.post("/v1/rules/explain", json={"condition": "feat.x >="}).status_code == 422


def test_catalog_endpoint(client):
    cat = client.get("/v1/rules/catalog").json()
    assert any(f["name"] == "feat.passthrough_ratio_24h" for f in cat["features"])
    assert "sanctions" in cat["lists"] and "BCRA-PUSF" in cat["regulatory_refs"]
    assert cat["recent_evaluations"] > 0


def test_backtest_new_rule_before_creating(client):
    bt = client.post("/v1/rules/backtest", json={"rule": rule(condition="txn.amount_ars > 0")}).json()
    assert bt["evaluated"] > 0 and bt["matched"] == bt["evaluated"] and bt["match_rate"] == 100
    assert bt["changed"] > 0  # una regla REVIEW que siempre dispara cambia las aprobaciones
    assert bt["decisions_after"]["APPROVE"] < bt["decisions_before"]["APPROVE"]


def test_test_single_transaction_does_not_record(client, svc):
    before, alerts_before = len(svc._recent), svc.alerts.stats()["total"]
    txn = sim.cash("CASH_OUT", sim.customer("C-T", account_opened_at="2026-09-25T00:00:00Z"), 2_000_000, "CVU-X")
    r = client.post("/v1/rules/test", json={"rule": rule(), "transaction": txn}).json()
    assert r["matched"] is True and r["applies_to_channel"] is True
    assert len(svc._recent) == before
    assert svc.alerts.stats()["total"] == alerts_before


def test_create_update_delete_custom_rule(client, svc):
    r = client.post("/v1/rules", json=rule(), headers=H)
    assert r.status_code == 201, r.text
    v1 = r.json()["ruleset_version"]
    path = svc.config_dir / "rules" / "90_consola.yaml"
    assert "USR-001" in path.read_text(encoding="utf-8")
    listed = {x["id"]: x for x in client.get("/v1/rules").json()["rules"]}
    assert listed["USR-001"]["mode"] == "shadow" and listed["USR-001"]["deletable"]

    # la regla en sombra se evalúa pero no cambia la decisión
    txn = Transaction.model_validate(sim.cash("CASH_OUT", sim.customer("C-N", account_opened_at="2026-09-25T00:00:00Z"), 1_100_000, "CVU-Y"))
    d = svc.evaluate(txn)
    assert "USR-001" in [h.rule_id for h in d.shadow_hits] and "USR-001" not in d.reason_codes

    r = client.put("/v1/rules/USR-001", json=rule(mode="active", score=55), headers=H)
    assert r.status_code == 200 and r.json()["ruleset_version"] != v1
    txn2 = Transaction.model_validate(sim.cash("CASH_OUT", sim.customer("C-M", account_opened_at="2026-09-25T00:00:00Z"), 1_100_000, "CVU-Z"))
    assert "USR-001" in svc.evaluate(txn2).reason_codes

    assert client.delete("/v1/rules/USR-001", headers=H).status_code == 200
    assert not path.exists()
    types = [h["type"] for h in client.get("/v1/config/history").json()]
    assert types[:3] == ["RULE_DELETED", "RULE_UPDATED", "RULE_CREATED"]


def test_edit_base_rule_preserves_file_format(client, svc):
    path = svc.config_dir / "rules" / "10_acquiring.yaml"
    original = path.read_text(encoding="utf-8")
    current = next(x for x in client.get("/v1/rules").json()["rules"] if x["id"] == "ACQ-003")
    body = {k: current[k] for k in ("id", "name", "description", "channels", "category", "severity", "action",
                                    "score", "mode", "enabled", "condition", "reason", "regulatory_refs", "owner")}
    body["score"] = 50
    assert client.put("/v1/rules/ACQ-003", json=body, headers=H).status_code == 200
    changed = [(a, b) for a, b in zip(original.splitlines(), path.read_text(encoding="utf-8").splitlines()) if a != b]
    assert changed == [("    score: 45", "    score: 50")]


@pytest.mark.parametrize("bad, fragment", [
    ({"condition": "txn.amount_ars > p.no_existe"}, "parámetro inexistente"),
    ({"condition": "import os"}, "Sintaxis"),
    ({"condition": "in_list('no_existe', txn.amount_ars)"}, "lista inexistente"),
    ({"regulatory_refs": ["INVENTADA"]}, "referencia normativa"),
    ({"regulatory_refs": []}, "regulatory_refs"),
    ({"id": "ACQ-001"}, "Ya existe"),
    ({"id": "sin guion"}, "formato"),
])
def test_invalid_rules_rejected(client, svc, bad, fragment):
    r = client.post("/v1/rules", json=rule(**bad), headers=H)
    assert r.status_code == 422
    assert fragment.lower() in r.text.lower()
    assert not (svc.config_dir / "rules" / "90_consola.yaml").exists()


def test_base_rules_cannot_be_deleted(client):
    r = client.delete("/v1/rules/ACQ-001", headers=H)
    assert r.status_code == 422 and "desactivala" in r.json()["detail"]


def test_params_listing_preview_and_update(client, svc):
    params = {p["name"]: p for p in client.get("/v1/params").json()}
    assert all(p["description"] for p in params.values())
    assert "COUT-001" in params["passthrough_ratio"]["used_by"]
    assert params["decision_thresholds.CASH_OUT.review"]["affects_decision"]

    pv = client.post("/v1/params/preview", json={"changes": {"decision_thresholds.CASH_OUT.review": 1}}).json()
    assert pv["evaluated"] > 0
    assert pv["decisions_after"]["APPROVE"] <= pv["decisions_before"]["APPROVE"]

    v0 = client.get("/health").json()["ruleset_version"]
    r = client.put("/v1/params", json={"changes": {"high_amount_ars": "2500000"}}, headers=H)
    assert r.status_code == 200, r.text
    assert svc.params["high_amount_ars"] == 2500000
    assert r.json()["ruleset_version"] != v0  # la versión refleja también los parámetros
    text = (svc.config_dir / "parameters.yaml").read_text(encoding="utf-8")
    assert "high_amount_ars: 2500000        # operación de monto alto" in text
    hist = client.get("/v1/config/history").json()[0]
    assert hist["type"] == "PARAMS_UPDATED" and hist["before"]["high_amount_ars"] == 2000000 and hist["user"] == "ana"


@pytest.mark.parametrize("changes", [
    {"decision_thresholds.CASH_IN.review": 95},
    {"passthrough_ratio": 3},
    {"high_amount_ars": -1},
    {"high_amount_ars": "mucho"},
    {"no_existe": 1},
])
def test_invalid_params_rejected(client, svc, changes):
    before = (svc.config_dir / "parameters.yaml").read_text(encoding="utf-8")
    assert client.put("/v1/params", json={"changes": changes}, headers=H).status_code == 422
    assert (svc.config_dir / "parameters.yaml").read_text(encoding="utf-8") == before


def test_writes_require_admin_key(svc, monkeypatch):
    monkeypatch.setenv("MONITOREO_API_KEYS", "cli")
    monkeypatch.setenv("MONITOREO_ADMIN_KEYS", "adm")
    c = TestClient(create_app(svc))
    assert c.post("/v1/rules", json=rule(), headers={"X-API-Key": "cli"}).status_code == 401
    assert c.put("/v1/params", json={"changes": {"high_amount_ars": 1}}, headers={"X-API-Key": "cli"}).status_code == 401
    assert c.post("/v1/rules/backtest", json={"rule": rule()}, headers={"X-API-Key": "cli"}).status_code == 200
    assert c.post("/v1/rules", json=rule(), headers={"X-API-Key": "adm"}).status_code == 201
