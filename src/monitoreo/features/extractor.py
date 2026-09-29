"""Cálculo de features en tiempo real a partir de la transacción y su historia.

Las features se calculan sobre la historia PREVIA (sin incluir la transacción
evaluada) y luego se agregan variantes `*_incl` que suman la transacción
actual, para que las reglas puedan expresar "con esta operación supera X".
"""

from __future__ import annotations

import math
import statistics
import logging
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import Action, Channel, Method, Transaction
from .store import BehaviorStore, Event, agg, distinct

M10 = 600
log = logging.getLogger(__name__)

H1 = 3600
H24 = 86400
D7 = 7 * H24
D30 = 30 * H24
D90 = 90 * H24


def load_timezone(name: str) -> tzinfo:
    """Carga el huso horario; si el sistema no tiene la base IANA (p.ej. Windows
    sin el paquete tzdata) usa UTC-3 fijo (Argentina no aplica horario de verano)."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("Huso horario %s no disponible; se usa UTC-3 fijo. Instale el paquete tzdata.", name)
        return timezone(timedelta(hours=-3), "ART")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class FeatureExtractor:
    def __init__(self, store: BehaviorStore, params: dict[str, Any]):
        self.store = store
        self.params = params
        self.tz = load_timezone(params.get("timezone", "America/Argentina/Buenos_Aires"))

    # ------------------------------------------------------------------ keys
    @staticmethod
    def keys_for(txn: Transaction) -> dict[str, str]:
        keys: dict[str, str] = {}
        if txn.card:
            keys["card"] = f"card:{txn.card.card_fingerprint}"
        if txn.merchant:
            keys["merchant"] = f"merchant:{txn.merchant.merchant_id}"
        if txn.customer:
            keys["cust_in"] = f"cust:{txn.customer.customer_id}:in"
            keys["cust_out"] = f"cust:{txn.customer.customer_id}:out"
        if txn.counterparty:
            keys["cpty"] = f"cpty:{txn.counterparty.account_id}"
        if txn.device and txn.device.device_id:
            keys["device"] = f"device:{txn.device.device_id}"
        if txn.device and txn.device.ip:
            keys["ip"] = f"ip:{txn.device.ip}"
        return keys

    # --------------------------------------------------------------- extract
    def extract(self, txn: Transaction) -> dict[str, Any]:
        now = txn.timestamp.timestamp()
        amt = float(txn.amount_ars or txn.amount)
        keys = self.keys_for(txn)
        f: dict[str, Any] = {}

        local = txn.timestamp.astimezone(self.tz)
        night_start, night_end = self.params.get("night_hours", [0, 6])
        f["hour_local"] = local.hour
        f["weekday"] = local.weekday()
        f["is_night"] = night_start <= local.hour < night_end
        f["is_round_amount"] = amt >= self.params.get("round_min_ars", 10000) and amt % self.params.get("round_base_ars", 10000) == 0

        threshold = self.params.get("structuring_threshold_ars", 0)
        pct = self.params.get("structuring_band_pct", 0.10)
        f["is_near_threshold"] = bool(threshold) and threshold * (1 - pct) <= amt < threshold

        cust = txn.customer
        if cust:
            f["account_age_days"] = self._age_days(cust.account_opened_at, txn.timestamp)
            f["declared_monthly_income_ars"] = cust.declared_monthly_income_ars
        if txn.merchant:
            f["merchant_age_days"] = self._age_days(txn.merchant.onboarded_at, txn.timestamp)

        if txn.channel == Channel.ACQUIRING:
            self._acquiring(txn, keys, now, amt, f)
        else:
            self._cash(txn, keys, now, amt, f)

        self._device(txn, keys, now, f)
        return f

    @staticmethod
    def _age_days(since: datetime | None, now: datetime) -> float | None:
        if since is None:
            return None
        if since.tzinfo is None:
            since = since.replace(tzinfo=now.tzinfo)
        return max((now - since).total_seconds() / 86400, 0.0)

    def _window(self, key: str | None, now: float, seconds: int):
        return self.store.events(key, now - seconds, now) if key else []

    # ------------------------------------------------------------ acquiring
    def _acquiring(self, txn: Transaction, keys: dict[str, str], now: float, amt: float, f: dict[str, Any]) -> None:
        card_key, m_key = keys.get("card"), keys.get("merchant")

        card_24h = self._window(card_key, now, H24)
        card_1h = [e for e in card_24h if e.ts >= now - H1]
        card_10m = [e for e in card_1h if e.ts >= now - M10]
        f["card_count_10m"] = len(card_10m)
        f["card_count_1h"] = len(card_1h)
        f["card_count_24h"] = len(card_24h)
        f["card_sum_24h"] = agg(card_24h)[1]
        f["card_sum_24h_incl"] = f["card_sum_24h"] + amt
        f["card_declines_1h"] = sum(1 for e in card_1h if not e.approved)
        f["card_distinct_merchants_1h"] = distinct(card_1h, "merchant")
        f["card_distinct_merchants_24h"] = distinct(card_24h, "merchant")
        f["card_distinct_countries_24h"] = distinct(card_24h, "country")
        f["card_small_txn_count_1h"] = sum(1 for e in card_1h if e.amount <= self.params.get("card_testing_max_amount_ars", 1000))
        f["card_same_merchant_count_1h"] = sum(1 for e in card_1h if e.attrs.get("merchant") == (txn.merchant.merchant_id if txn.merchant else None))
        f["card_is_new"] = not card_24h and self.store.last(card_key) is None if card_key else True

        # Viaje imposible: operación presencial previa lejos en poco tiempo
        f["card_geo_speed_kmh"] = None
        if txn.device and txn.device.latitude is not None and txn.device.longitude is not None and card_key:
            prev = self.store.last(card_key, lambda e: e.attrs.get("lat") is not None)
            if prev:
                dist = haversine_km(prev.attrs["lat"], prev.attrs["lon"], txn.device.latitude, txn.device.longitude)
                hours = max((now - prev.ts) / 3600, 1 / 60)
                f["card_geo_speed_kmh"] = round(dist / hours, 1)
                f["card_geo_distance_km"] = round(dist, 1)

        m_1h = self._window(m_key, now, H1)
        m_30d = self._window(m_key, now, D30)
        approved_30d = [e.amount for e in m_30d if e.approved]
        f["merchant_count_1h"] = len(m_1h)
        f["merchant_distinct_cards_1h"] = distinct(m_1h, "card")
        f["merchant_declines_1h"] = sum(1 for e in m_1h if not e.approved)
        f["merchant_decline_ratio_1h"] = (f["merchant_declines_1h"] / len(m_1h)) if m_1h else 0.0
        f["merchant_avg_ticket_30d"] = statistics.fmean(approved_30d) if approved_30d else None
        f["merchant_ticket_ratio"] = (amt / f["merchant_avg_ticket_30d"]) if f["merchant_avg_ticket_30d"] else None
        f["merchant_history_count_30d"] = len(approved_30d)
        f["merchant_sum_24h_incl"] = agg([e for e in m_30d if e.ts >= now - H24])[1] + amt
        foreign = [e for e in m_1h if e.attrs.get("country") not in (None, "AR")]
        f["merchant_foreign_card_ratio_1h"] = (len(foreign) / len(m_1h)) if m_1h else 0.0

        f["card_not_present"] = txn.entry_mode in ("ECOMMERCE", "MANUAL")
        f["bin_country_mismatch"] = bool(txn.card and txn.device and txn.device.ip_country
                                         and txn.card.issuer_country != txn.device.ip_country)

    # ----------------------------------------------------------------- cash
    def _cash(self, txn: Transaction, keys: dict[str, str], now: float, amt: float, f: dict[str, Any]) -> None:
        in_key, out_key, cp_key = keys.get("cust_in"), keys.get("cust_out"), keys.get("cpty")

        in_90d = self._window(in_key, now, D90)
        out_90d = self._window(out_key, now, D90)
        in_30d = [e for e in in_90d if e.ts >= now - D30]
        out_30d = [e for e in out_90d if e.ts >= now - D30]
        in_24h = [e for e in in_30d if e.ts >= now - H24]
        out_24h = [e for e in out_30d if e.ts >= now - H24]
        in_1h = [e for e in in_24h if e.ts >= now - H1]
        out_1h = [e for e in out_24h if e.ts >= now - H1]

        f["cashin_count_1h"], f["cashin_sum_1h"] = agg(in_1h)
        f["cashin_count_24h"], f["cashin_sum_24h"] = agg(in_24h)
        f["cashin_count_30d"], f["cashin_sum_30d"] = agg(in_30d)
        f["cashout_count_1h"], f["cashout_sum_1h"] = agg(out_1h)
        f["cashout_count_24h"], f["cashout_sum_24h"] = agg(out_24h)
        f["cashout_count_30d"], f["cashout_sum_30d"] = agg(out_30d)
        f["cash_method_sum_30d"] = sum(e.amount for e in in_30d if e.approved and e.attrs.get("method") == Method.CASH.value)

        is_in = txn.channel == Channel.CASH_IN
        hist_same = in_90d if is_in else out_90d
        amounts = [e.amount for e in hist_same if e.approved]
        f["history_count_90d"] = len(amounts)
        f["avg_amount_90d"] = statistics.fmean(amounts) if amounts else None
        std = statistics.pstdev(amounts) if len(amounts) >= 2 else None
        f["amount_zscore"] = ((amt - f["avg_amount_90d"]) / std) if std else None
        f["amount_to_avg_ratio"] = (amt / f["avg_amount_90d"]) if f["avg_amount_90d"] else None

        if is_in:
            f["cashin_sum_24h_incl"] = f["cashin_sum_24h"] + amt
            f["cashin_sum_30d_incl"] = f["cashin_sum_30d"] + amt
            f["cashin_distinct_senders_24h"] = distinct(in_24h, "cpty") + (
                0 if txn.counterparty is None or any(e.attrs.get("cpty") == txn.counterparty.account_id for e in in_24h) else 1)
            f["cash_method_sum_30d_incl"] = f["cash_method_sum_30d"] + (amt if txn.method == Method.CASH else 0)
        else:
            f["cashout_sum_24h_incl"] = f["cashout_sum_24h"] + amt
            f["cashout_sum_30d_incl"] = f["cashout_sum_30d"] + amt
            f["cashout_attempts_1h"] = len(out_1h)
            f["cashout_declines_24h"] = sum(1 for e in out_24h if not e.approved)
            f["cashout_distinct_beneficiaries_24h"] = distinct(out_24h, "cpty") + (
                0 if txn.counterparty is None or any(e.attrs.get("cpty") == txn.counterparty.account_id for e in out_24h) else 1)
            # Cuenta puente / pass-through: sale casi todo lo que entró
            f["passthrough_ratio_24h"] = (f["cashout_sum_24h_incl"] / f["cashin_sum_24h"]) if f["cashin_sum_24h"] else None
            last_in = self.store.last(in_key, lambda e: e.approved) if in_key else None
            f["minutes_since_last_cashin"] = round((now - last_in.ts) / 60, 1) if last_in else None
            f["last_cashin_amount"] = last_in.amount if last_in else None
            if txn.counterparty and txn.customer:
                pair_key = f"pair:{txn.customer.customer_id}:{txn.counterparty.account_id}"
                f["is_new_beneficiary"] = not txn.counterparty.is_own_account and not self.store.seen(pair_key)

        # Perfil transaccional vs ingresos declarados (Res. UIF: perfil del cliente)
        income = txn.customer.declared_monthly_income_ars if txn.customer else None
        movement_30d = (f["cashin_sum_30d"] + (amt if is_in else 0)) if is_in else (f["cashout_sum_30d"] + amt)
        f["profile_usage_ratio_30d"] = (movement_30d / income) if income else None

        # Fraccionamiento: operaciones apenas debajo del umbral en 7 días
        band_events = [e for e in (in_90d if is_in else out_90d) if e.ts >= now - D7 and e.attrs.get("near_threshold")]
        f["near_threshold_count_7d"] = len(band_events) + (1 if f.get("is_near_threshold") else 0)

        # Mula receptora: la misma contraparte recibe/envía a muchos clientes nuestros
        if cp_key:
            cp_24h = self._window(cp_key, now, H24)
            f["cpty_distinct_customers_24h"] = distinct(cp_24h, "customer") + (
                0 if any(e.attrs.get("customer") == txn.customer.customer_id for e in cp_24h) else 1)
            f["cpty_sum_24h_incl"] = agg(cp_24h)[1] + amt

    # --------------------------------------------------------------- device
    def _device(self, txn: Transaction, keys: dict[str, str], now: float, f: dict[str, Any]) -> None:
        subject = txn.customer.customer_id if txn.customer else (txn.card.card_fingerprint if txn.card else None)
        d_key, ip_key = keys.get("device"), keys.get("ip")
        if d_key:
            d_24h = self._window(d_key, now, H24)
            f["device_distinct_subjects_24h"] = distinct(d_24h, "subject") + (
                0 if any(e.attrs.get("subject") == subject for e in d_24h) else 1)
            if txn.customer:
                f["is_new_device"] = not self.store.seen(f"devpair:{txn.customer.customer_id}:{txn.device.device_id}")
        if ip_key:
            ip_1h = self._window(ip_key, now, H1)
            f["ip_distinct_subjects_1h"] = distinct(ip_1h, "subject") + (
                0 if any(e.attrs.get("subject") == subject for e in ip_1h) else 1)

    # --------------------------------------------------------------- record
    def record(self, txn: Transaction, action: Action, features: dict[str, Any] | None = None) -> None:
        """Registra la operación en la historia. Se registran también los
        rechazos (como intentos), pero sólo las aprobadas suman montos."""
        now = txn.timestamp.timestamp()
        amt = float(txn.amount_ars or txn.amount)
        approved = action != Action.DECLINE
        keys = self.keys_for(txn)
        subject = txn.customer.customer_id if txn.customer else (txn.card.card_fingerprint if txn.card else None)
        near = bool(features and features.get("is_near_threshold"))
        attrs: dict[str, Any] = {
            "merchant": txn.merchant.merchant_id if txn.merchant else None,
            "card": txn.card.card_fingerprint if txn.card else None,
            "country": txn.card.issuer_country if txn.card else None,
            "cpty": txn.counterparty.account_id if txn.counterparty else None,
            "customer": txn.customer.customer_id if txn.customer else None,
            "method": txn.method.value,
            "subject": subject,
            "near_threshold": near,
        }
        if txn.device and txn.device.latitude is not None and txn.entry_mode not in ("ECOMMERCE", "MANUAL"):
            attrs["lat"], attrs["lon"] = txn.device.latitude, txn.device.longitude

        event = Event(ts=now, amount=amt, approved=approved, attrs=attrs)
        if txn.channel == Channel.ACQUIRING:
            for k in ("card", "merchant"):
                if k in keys:
                    self.store.add(keys[k], event)
        else:
            side = "cust_in" if txn.channel == Channel.CASH_IN else "cust_out"
            self.store.add(keys[side], event)
            if "cpty" in keys:
                self.store.add(keys["cpty"], event)
            if approved and txn.channel == Channel.CASH_OUT and txn.counterparty and txn.customer:
                self.store.mark(f"pair:{txn.customer.customer_id}:{txn.counterparty.account_id}")
        for k in ("device", "ip"):
            if k in keys:
                self.store.add(keys[k], event)
        if approved and txn.customer and txn.device and txn.device.device_id:
            self.store.mark(f"devpair:{txn.customer.customer_id}:{txn.device.device_id}")
