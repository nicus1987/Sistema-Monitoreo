import pytest
from fastapi.testclient import TestClient

from monitoreo import simulator as sim
from monitoreo.api import create_app


@pytest.fixture
def client(service, monkeypatch):
    monkeypatch.setenv("MONITOREO_API_KEYS", "client-key")
    monkeypatch.setenv("MONITOREO_ADMIN_KEYS", "admin-key")
    return TestClient(create_app(service))


C = {"X-API-Key": "client-key"}
A = {"X-API-Key": "admin-key"}


def test_requires_api_key(client):
    r = client.post("/v1/transactions/evaluate", json=sim.acquiring("FP", "M", 100))
    assert r.status_code == 401


def test_evaluate_and_alert_flow(client):
    [ev] = list(sim.account_takeover())
    r = client.post("/v1/transactions/evaluate?include_features=true", json=ev, headers=C)
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "DECLINE" and "COUT-004" in body["reason_codes"]
    assert body["features"]["is_new_device"] is True
    aid = body["alert_id"]
    r = client.post(f"/v1/alerts/{aid}/transition", json={"to_status": "IN_REVIEW"}, headers={**C, "X-User": "ana"})
    assert r.status_code == 200 and r.json()["assignee"] == "ana"
    r = client.post(f"/v1/alerts/{aid}/transition", json={"to_status": "ROS_FILED"}, headers={**C, "X-User": "ana"})
    assert r.status_code == 409


def test_validation_error(client):
    bad = sim.acquiring("FP", "M", 100)
    del bad["card"]
    assert client.post("/v1/transactions/evaluate", json=bad, headers=C).status_code == 422


def test_admin_endpoints(client):
    assert client.post("/v1/admin/reload", headers=C).status_code == 401
    assert client.post("/v1/admin/reload", headers=A).status_code == 200
    assert client.get("/v1/audit/verify", headers=A).json()["integrity_ok"] is True


def test_rules_health_metrics(client):
    rules = client.get("/v1/rules", headers=C).json()
    assert len(rules["rules"]) >= 60
    assert client.get("/health").json()["status"] == "ok"
    client.post("/v1/transactions/evaluate", json=sim.acquiring("FP", "M", 100), headers=C)
    assert "monitoreo_decisions_total" in client.get("/metrics").text
    assert client.get("/").status_code == 200
