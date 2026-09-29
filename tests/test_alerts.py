import pytest

from monitoreo import simulator as sim
from monitoreo.alerts import AlertStatus, TransitionError
from monitoreo.models import Transaction


@pytest.fixture
def alert(service):
    [d] = [service.evaluate(Transaction.model_validate(e)) for e in sim.sanctions()]
    return service.alerts.get(d.alert_id)


def test_ros_workflow_with_four_eyes(service, alert):
    am = service.alerts
    am.transition(alert.alert_id, AlertStatus.IN_REVIEW, "analista1")
    with pytest.raises(TransitionError):
        am.transition(alert.alert_id, AlertStatus.ESCALATED_COMPLIANCE, "analista1", "")
    am.transition(alert.alert_id, AlertStatus.ESCALATED_COMPLIANCE, "analista1", "Coincidencia confirmada con RePET")
    with pytest.raises(TransitionError):
        am.transition(alert.alert_id, AlertStatus.ROS_FILED, "analista1", "")
    a = am.transition(alert.alert_id, AlertStatus.ROS_FILED, "oficial_cumplimiento", "ROS FT presentado")
    assert a.status == AlertStatus.ROS_FILED
    assert [h.to_status for h in a.history][-1] == AlertStatus.ROS_FILED


def test_invalid_transition(service, alert):
    with pytest.raises(TransitionError):
        service.alerts.transition(alert.alert_id, AlertStatus.ROS_FILED, "x", "y")
