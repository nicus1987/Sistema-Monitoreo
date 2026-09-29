"""Modelos de dominio: transacción canónica, decisión y resultado de reglas.

Principios aplicados:
- Nunca se recibe ni persiste el PAN completo (PCI DSS / Com. "A" 7724 BCRA):
  la tarjeta se identifica por token/huella (`card_fingerprint`), BIN y últimos 4.
- Montos siempre en moneda original + equivalente en ARS para aplicar umbrales.
- Todo evento tiene un identificador único e idempotente (`transaction_id`).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

_PAN_RE = re.compile(r"\b\d{13,19}\b")


class Channel(str, Enum):
    ACQUIRING = "ACQUIRING"  # Pagos con tarjeta procesados para comercios
    CASH_IN = "CASH_IN"  # Ingreso de fondos: depósito, transferencia entrante, carga en efectivo
    CASH_OUT = "CASH_OUT"  # Egreso: transferencia saliente, extracción, retiro en red


class EntryMode(str, Enum):
    CHIP = "CHIP"
    CONTACTLESS = "CONTACTLESS"
    MAGSTRIPE = "MAGSTRIPE"
    MANUAL = "MANUAL"  # Key entry
    ECOMMERCE = "ECOMMERCE"
    QR = "QR"
    NA = "NA"


class Method(str, Enum):
    CARD = "CARD"
    TRANSFER = "TRANSFER"  # Transferencia inmediata CBU/CVU/alias
    DEBIN = "DEBIN"
    CASH = "CASH"  # Efectivo en red de cobranza / ventanilla / ATM
    QR = "QR"
    WALLET = "WALLET"


class Action(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"  # Aprobar/retener y generar alerta para analista
    DECLINE = "DECLINE"

    @property
    def weight(self) -> int:
        return {"APPROVE": 0, "REVIEW": 1, "DECLINE": 2}[self.value]


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskCategory(str, Enum):
    FRAUD = "FRAUD"  # Fraude (tarjeta, ATO, ingeniería social)
    AML = "AML"  # Prevención de lavado de activos (PLA)
    CFT = "CFT"  # Financiamiento del terrorismo / sanciones
    OPERATIONAL = "OPERATIONAL"


class Customer(BaseModel):
    """Datos KYC mínimos del cliente/titular de cuenta (debida diligencia)."""

    customer_id: str
    cuit: str | None = None
    segment: str = "RETAIL"  # RETAIL | PYME | CORPORATE | MERCHANT
    risk_level: str = "MEDIUM"  # Matriz de riesgo PLA/FT: LOW | MEDIUM | HIGH
    is_pep: bool = False
    kyc_verified: bool = True
    account_opened_at: datetime | None = None
    declared_monthly_income_ars: float | None = None  # Perfil transaccional
    country: str = "AR"


class Merchant(BaseModel):
    merchant_id: str
    mcc: str
    country: str = "AR"
    onboarded_at: datetime | None = None
    risk_level: str = "MEDIUM"


class Card(BaseModel):
    card_fingerprint: str = Field(..., description="Token/huella irreversible de la tarjeta")
    bin: str = Field(..., min_length=6, max_length=8)
    last4: str = Field(..., min_length=4, max_length=4)
    issuer_country: str = "AR"
    card_type: str = "CREDIT"  # CREDIT | DEBIT | PREPAID


class Counterparty(BaseModel):
    """Contraparte en transferencias (origen en cash-in, destino en cash-out)."""

    account_id: str  # CBU/CVU hasheado o alias normalizado
    cuit: str | None = None
    name: str | None = None
    bank_code: str | None = None
    country: str = "AR"
    is_own_account: bool = False


class Device(BaseModel):
    device_id: str | None = None
    ip: str | None = None
    ip_country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_emulator: bool = False
    is_rooted: bool = False
    session_age_seconds: float | None = None


class Transaction(BaseModel):
    transaction_id: str
    channel: Channel
    method: Method
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    amount: float = Field(..., gt=0)
    currency: str = "ARS"
    amount_ars: float | None = Field(None, description="Equivalente en ARS; si falta y currency=ARS se usa amount")
    entry_mode: EntryMode = EntryMode.NA

    customer: Customer | None = None
    merchant: Merchant | None = None
    card: Card | None = None
    counterparty: Counterparty | None = None
    device: Device | None = None

    three_ds_authenticated: bool | None = None
    cvv_match: bool | None = None
    avs_match: bool | None = None
    is_recurring: bool = False
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

    @field_validator("description")
    @classmethod
    def _no_pan_in_text(cls, v: str | None) -> str | None:
        if v and _PAN_RE.search(v):
            raise ValueError("El campo description no puede contener números de tarjeta (PCI DSS)")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> "Transaction":
        if self.amount_ars is None:
            if self.currency != "ARS":
                raise ValueError("amount_ars es obligatorio para monedas distintas de ARS")
            self.amount_ars = self.amount
        if self.channel == Channel.ACQUIRING and (self.merchant is None or self.card is None):
            raise ValueError("Las transacciones de adquirencia requieren merchant y card")
        if self.channel in (Channel.CASH_IN, Channel.CASH_OUT) and self.customer is None:
            raise ValueError("Las transacciones de cash-in/cash-out requieren customer")
        return self

    @property
    def primary_entity(self) -> str | None:
        """Entidad principal sobre la que se acumulan comportamientos."""
        if self.channel == Channel.ACQUIRING:
            return self.card.card_fingerprint if self.card else None
        return self.customer.customer_id if self.customer else None


class RuleHit(BaseModel):
    rule_id: str
    name: str
    category: RiskCategory
    severity: Severity
    action: Action
    score: int
    mode: str  # active | shadow
    reason: str
    regulatory_refs: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    transaction_id: str
    channel: Channel
    action: Action
    risk_score: int
    amount_ars: float | None = None
    reason_codes: list[str]
    hits: list[RuleHit]
    shadow_hits: list[RuleHit] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    ruleset_version: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = 0.0
    fallback: bool = False
    alert_id: str | None = None
