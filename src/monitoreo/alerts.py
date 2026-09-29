"""Gestión de alertas y casos para analistas de Fraude / PLA-FT.

Ciclo de vida:
    OPEN -> IN_REVIEW -> CLOSED_FALSE_POSITIVE
                      -> CLOSED_CONFIRMED_FRAUD
                      -> ESCALATED_COMPLIANCE -> ROS_FILED | CLOSED_NO_ROS

La decisión de reportar una Operación Sospechosa (ROS) a la UIF la toma el
Oficial de Cumplimiento; se aplica el principio de los cuatro ojos: quien
escala no puede ser quien aprueba el ROS. El sistema nunca notifica al
cliente sobre el análisis (prohibición de "tipping-off", art. 22 Ley 25.246).
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .models import Action, Decision, RiskCategory, Severity


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    CLOSED_FALSE_POSITIVE = "CLOSED_FALSE_POSITIVE"
    CLOSED_CONFIRMED_FRAUD = "CLOSED_CONFIRMED_FRAUD"
    ESCALATED_COMPLIANCE = "ESCALATED_COMPLIANCE"
    ROS_FILED = "ROS_FILED"
    CLOSED_NO_ROS = "CLOSED_NO_ROS"


TRANSITIONS: dict[AlertStatus, set[AlertStatus]] = {
    AlertStatus.OPEN: {AlertStatus.IN_REVIEW},
    AlertStatus.IN_REVIEW: {AlertStatus.CLOSED_FALSE_POSITIVE, AlertStatus.CLOSED_CONFIRMED_FRAUD,
                            AlertStatus.ESCALATED_COMPLIANCE},
    AlertStatus.ESCALATED_COMPLIANCE: {AlertStatus.ROS_FILED, AlertStatus.CLOSED_NO_ROS},
}

SLA_BY_SEVERITY = {
    Severity.CRITICAL: timedelta(hours=1),
    Severity.HIGH: timedelta(hours=4),
    Severity.MEDIUM: timedelta(hours=24),
    Severity.LOW: timedelta(hours=72),
}

_SEV_ORDER = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]


class AlertEvent(BaseModel):
    at: datetime
    user: str
    from_status: AlertStatus | None
    to_status: AlertStatus
    comment: str = ""


class Alert(BaseModel):
    alert_id: str
    transaction_id: str
    channel: str
    customer_id: str | None
    action: Action
    risk_score: int
    severity: Severity
    categories: list[RiskCategory]
    rule_ids: list[str]
    reasons: list[str]
    created_at: datetime
    due_at: datetime
    status: AlertStatus = AlertStatus.OPEN
    assignee: str | None = None
    history: list[AlertEvent] = Field(default_factory=list)


class TransitionError(ValueError):
    pass


class AlertManager:
    def __init__(self) -> None:
        self._alerts: dict[str, Alert] = {}
        self._lock = threading.RLock()

    def create_from_decision(self, decision: Decision, customer_id: str | None) -> Alert | None:
        if decision.action == Action.APPROVE or not decision.hits:
            return None
        severity = max((h.severity for h in decision.hits), key=_SEV_ORDER.index)
        now = datetime.now(timezone.utc)
        alert = Alert(
            alert_id=f"ALR-{uuid.uuid4().hex[:12].upper()}",
            transaction_id=decision.transaction_id,
            channel=decision.channel.value,
            customer_id=customer_id,
            action=decision.action,
            risk_score=decision.risk_score,
            severity=severity,
            categories=sorted({h.category for h in decision.hits}, key=lambda c: c.value),
            rule_ids=[h.rule_id for h in decision.hits],
            reasons=[h.reason for h in decision.hits],
            created_at=now,
            due_at=now + SLA_BY_SEVERITY[severity],
        )
        alert.history.append(AlertEvent(at=now, user="system", from_status=None, to_status=AlertStatus.OPEN))
        with self._lock:
            self._alerts[alert.alert_id] = alert
        return alert

    def get(self, alert_id: str) -> Alert | None:
        with self._lock:
            return self._alerts.get(alert_id)

    def list(self, status: AlertStatus | None = None, limit: int = 100) -> list[Alert]:
        with self._lock:
            items = [a for a in self._alerts.values() if status is None or a.status == status]
        items.sort(key=lambda a: (-_SEV_ORDER.index(a.severity), a.created_at))
        return items[:limit]

    def transition(self, alert_id: str, to_status: AlertStatus, user: str, comment: str = "") -> Alert:
        with self._lock:
            alert = self._alerts.get(alert_id)
            if alert is None:
                raise KeyError(alert_id)
            if to_status not in TRANSITIONS.get(alert.status, set()):
                raise TransitionError(f"Transición inválida {alert.status.value} -> {to_status.value}")
            if to_status in (AlertStatus.CLOSED_FALSE_POSITIVE, AlertStatus.CLOSED_CONFIRMED_FRAUD,
                             AlertStatus.ESCALATED_COMPLIANCE, AlertStatus.CLOSED_NO_ROS) and not comment.strip():
                raise TransitionError("El cierre o escalamiento requiere fundamento (comentario)")
            if to_status in (AlertStatus.ROS_FILED, AlertStatus.CLOSED_NO_ROS):
                escalator = next((e.user for e in reversed(alert.history)
                                  if e.to_status == AlertStatus.ESCALATED_COMPLIANCE), None)
                if escalator == user:
                    raise TransitionError("Principio de 4 ojos: quien escaló no puede resolver el ROS")
            alert.history.append(AlertEvent(at=datetime.now(timezone.utc), user=user,
                                            from_status=alert.status, to_status=to_status, comment=comment))
            alert.status = to_status
            if to_status == AlertStatus.IN_REVIEW:
                alert.assignee = user
            return alert

    def stats(self) -> dict[str, Any]:
        with self._lock:
            alerts = list(self._alerts.values())
        now = datetime.now(timezone.utc)
        open_states = {AlertStatus.OPEN, AlertStatus.IN_REVIEW, AlertStatus.ESCALATED_COMPLIANCE}
        by_status: dict[str, int] = {}
        for a in alerts:
            by_status[a.status.value] = by_status.get(a.status.value, 0) + 1
        return {
            "total": len(alerts),
            "by_status": by_status,
            "overdue": sum(1 for a in alerts if a.status in open_states and a.due_at < now),
        }
