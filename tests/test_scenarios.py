"""Escenarios de punta a punta: cada tipología debe ser detectada por la regla esperada."""

from datetime import timedelta

from monitoreo import simulator as sim
from monitoreo.models import Action, Transaction


def run(service, events):
    return [service.evaluate(Transaction.model_validate(e)) for e in events]


def test_normal_traffic_is_mostly_approved(service):
    decisions = run(service, sim.normal_traffic(400))
    approved = sum(d.action == Action.APPROVE for d in decisions)
    assert approved / len(decisions) >= 0.97


def test_card_testing_declined(service):
    decisions = run(service, sim.card_testing())
    assert "ACQ-001" in decisions[-1].reason_codes
    assert decisions[-1].action == Action.DECLINE


def test_impossible_travel_declined(service):
    decisions = run(service, sim.impossible_travel())
    assert decisions[0].action == Action.APPROVE
    assert "ACQ-006" in decisions[1].reason_codes
    assert decisions[1].action == Action.DECLINE


def test_mule_passthrough_detected(service):
    decisions = run(service, sim.mule_passthrough())
    cash_ins, cash_out = decisions[:-1], decisions[-1]
    assert any("CIN-004" in d.reason_codes for d in cash_ins)  # fan-in
    assert any("CIN-005" in d.reason_codes for d in cash_ins)  # cuenta nueva
    assert "COUT-001" in cash_out.reason_codes                # cuenta puente
    assert cash_out.action in (Action.REVIEW, Action.DECLINE)
    assert cash_out.alert_id is not None


def test_structuring_detected(service):
    decisions = run(service, sim.structuring())
    assert "CIN-001" in decisions[-1].reason_codes
    assert decisions[-1].action == Action.REVIEW


def test_account_takeover_declined(service):
    [d] = run(service, sim.account_takeover())
    assert "COUT-004" in d.reason_codes
    assert d.action == Action.DECLINE


def test_sanctions_declined_with_critical_alert(service):
    [d] = run(service, sim.sanctions())
    assert "COUT-009" in d.reason_codes and d.action == Action.DECLINE
    alert = service.alerts.get(d.alert_id)
    assert alert.severity.value == "CRITICAL"
    assert alert.categories[0].value == "CFT"


def test_declined_cashout_does_not_consume_limit(service):
    cust = sim.customer("CUST-LIM", declared_monthly_income_ars=50_000_000)
    first = sim.cash("CASH_OUT", cust, 9_000_000, "CBU-A")
    second = sim.cash("CASH_OUT", cust, 7_000_000, "CBU-A")
    third = sim.cash("CASH_OUT", cust, 900_000, "CBU-A")
    d1, d2, d3 = run(service, [first, second, third])
    assert "COUT-007" not in d1.reason_codes and d1.action != Action.DECLINE
    assert "COUT-007" in d2.reason_codes and d2.action == Action.DECLINE
    assert "COUT-007" not in d3.reason_codes  # el rechazo no sumó al acumulado


def test_trusted_counterparty_excluded_from_mule_rule(service):
    ts = sim.NOW() - timedelta(minutes=30)
    events = [sim.cash("CASH_IN", sim.customer(f"CUST-P{i}"), 900_000, "CBU-EMPLEADOR-DEMO", ts=ts)
              for i in range(8)]
    assert all("CIN-016" not in d.reason_codes for d in run(service, events))
