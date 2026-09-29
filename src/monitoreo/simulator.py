"""Generador de tráfico sintético con escenarios de fraude y lavado.

Uso:
    python -m monitoreo.simulator                     # evalúa en proceso y muestra resumen
    python -m monitoreo.simulator --url http://localhost:8000 --rate 20   # envía a la API
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def customer(cid: str, **kw: Any) -> dict[str, Any]:
    base = {"customer_id": cid, "cuit": f"20-{random.randint(10000000, 40000000)}-{random.randint(0, 9)}",
            "account_opened_at": (NOW() - timedelta(days=400)).isoformat(),
            "declared_monthly_income_ars": 2_500_000, "risk_level": "LOW"}
    base.update(kw)
    return base


def acquiring(card_fp: str, merchant_id: str, amount: float, ts: datetime | None = None, **kw: Any) -> dict[str, Any]:
    txn = {
        "transaction_id": _id("ACQ"), "channel": "ACQUIRING", "method": "CARD",
        "timestamp": (ts or NOW()).isoformat(), "amount": amount, "entry_mode": kw.pop("entry_mode", "CHIP"),
        "merchant": {"merchant_id": merchant_id, "mcc": kw.pop("mcc", "5411"),
                     "onboarded_at": kw.pop("merchant_onboarded_at", (NOW() - timedelta(days=500)).isoformat())},
        "card": {"card_fingerprint": card_fp, "bin": kw.pop("bin", "450799"), "last4": "1234",
                 "issuer_country": kw.pop("issuer_country", "AR")},
        "device": kw.pop("device", {"latitude": -34.60, "longitude": -58.38}),
    }
    txn.update(kw)
    return txn


def cash(channel: str, cust: dict[str, Any], amount: float, cpty: str, ts: datetime | None = None,
         method: str = "TRANSFER", **kw: Any) -> dict[str, Any]:
    txn = {
        "transaction_id": _id(channel[:4]), "channel": channel, "method": method,
        "timestamp": (ts or NOW()).isoformat(), "amount": amount, "customer": cust,
        "counterparty": {"account_id": cpty, "cuit": kw.pop("cpty_cuit", None), "country": kw.pop("cpty_country", "AR")},
        "device": kw.pop("device", {"device_id": f"DEV-{cust['customer_id']}", "ip": f"181.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}",
                                    "session_age_seconds": 900}),
    }
    txn.update(kw)
    return txn


# --------------------------------------------------------------- escenarios
def normal_traffic(n: int) -> Iterator[dict[str, Any]]:
    for _ in range(n):
        r = random.random()
        if r < 0.5:
            yield acquiring(f"CARD-{random.randint(1, 500)}", f"MER-{random.randint(1, 50)}",
                            round(random.uniform(2000, 80000), 2))
        elif r < 0.75:
            c = customer(f"CUST-{random.randint(1, 300)}")
            yield cash("CASH_IN", c, round(random.uniform(10000, 400000), 2), random.choice(["CBU-EMPLEADOR-DEMO", f"CBU-{random.randint(1, 5000)}"]))
        else:
            c = customer(f"CUST-{random.randint(1, 300)}")
            yield cash("CASH_OUT", c, round(random.uniform(5000, 200000), 2), f"CBU-{random.randint(1, 900)}")


def card_testing() -> Iterator[dict[str, Any]]:
    card = _id("CARD-STOLEN")
    for i in range(8):
        yield acquiring(card, "MER-ECOM-1", random.choice([100, 150, 200]), entry_mode="ECOMMERCE",
                        device={"ip": "45.1.1.1", "ip_country": "US"})


def impossible_travel() -> Iterator[dict[str, Any]]:
    card = _id("CARD-CLONED")
    t0 = NOW() - timedelta(minutes=30)
    yield acquiring(card, "MER-BA", 25000, ts=t0, device={"latitude": -34.60, "longitude": -58.38})
    yield acquiring(card, "MER-MDZ", 30000, ts=t0 + timedelta(minutes=20), device={"latitude": -32.89, "longitude": -68.83})


def mule_passthrough() -> Iterator[dict[str, Any]]:
    c = customer(_id("CUST-MULA"), account_opened_at=(NOW() - timedelta(days=5)).isoformat(),
                 declared_monthly_income_ars=800_000)
    t0 = NOW() - timedelta(minutes=40)
    for i in range(12):
        yield cash("CASH_IN", c, 350_000, f"CVU-VICTIMA-{i}", ts=t0 + timedelta(minutes=i))
    yield cash("CASH_OUT", c, 4_000_000, "CVU-DESTINO-X", ts=t0 + timedelta(minutes=20))


def structuring() -> Iterator[dict[str, Any]]:
    c = customer(_id("CUST-PITUFO"))
    for d in range(4):
        yield cash("CASH_IN", c, 950_000, "EFECTIVO-RED", ts=NOW() - timedelta(days=3 - d), method="CASH")


def account_takeover() -> Iterator[dict[str, Any]]:
    c = customer(_id("CUST-ATO"))
    yield cash("CASH_OUT", c, 2_000_000, _id("CVU-NUEVO"),
               device={"device_id": _id("DEV-NUEVO"), "ip": "190.2.2.2", "session_age_seconds": 45})


def sanctions() -> Iterator[dict[str, Any]]:
    yield cash("CASH_OUT", customer(_id("CUST")), 100_000, "CBU-EXT", cpty_cuit="20-99999999-1")


SCENARIOS = {
    "card_testing": card_testing,
    "impossible_travel": impossible_travel,
    "mule_passthrough": mule_passthrough,
    "structuring": structuring,
    "account_takeover": account_takeover,
    "sanctions": sanctions,
}


def all_traffic(normal: int = 300) -> list[dict[str, Any]]:
    """Tráfico normal con los escenarios intercalados en posiciones al azar
    (cada escenario conserva el orden interno de sus operaciones)."""
    events = list(normal_traffic(normal))
    for gen in SCENARIOS.values():
        pos = random.randint(0, len(events))
        events[pos:pos] = list(gen())
    return events


def wait_for_api(url: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2):  # noqa: S310
                return
        except OSError:
            if time.time() > deadline:
                raise SystemExit(f"La API no responde en {url}. ¿Está levantada (python -m monitoreo)?")
            print("Esperando a que la API esté lista...")
            time.sleep(2)


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="URL base de la API; si se omite se evalúa en proceso")
    parser.add_argument("--normal", type=int, default=300)
    parser.add_argument("--rate", type=float, default=0, help="transacciones por segundo (0 = sin límite)")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--wait-only", action="store_true", help="sólo esperar a que la API responda")
    args = parser.parse_args()

    if args.url:
        wait_for_api(args.url)
        if args.wait_only:
            return
    events = all_traffic(args.normal)
    actions: Counter[str] = Counter()
    rules: Counter[str] = Counter()
    service = None
    if not args.url:
        from .models import Transaction
        from .service import MonitoringService
        service = MonitoringService()

    for ev in events:
        if service:
            d = service.evaluate(Transaction.model_validate(ev))
            result = {"action": d.action.value, "reason_codes": d.reason_codes}
        else:
            req = urllib.request.Request(f"{args.url}/v1/transactions/evaluate", data=json.dumps(ev).encode(),
                                         headers={"Content-Type": "application/json",
                                                  **({"X-API-Key": args.api_key} if args.api_key else {})})
            with urllib.request.urlopen(req) as resp:  # noqa: S310
                result = json.loads(resp.read())
        actions[result["action"]] += 1
        rules.update(result["reason_codes"])
        if args.rate:
            time.sleep(1 / args.rate)

    print(f"Transacciones: {len(events)}  Decisiones: {dict(actions)}")
    print("Reglas más disparadas:")
    for rid, n in rules.most_common(15):
        print(f"  {rid:10s} {n}")
    if service:
        print("Latencia:", service.metrics.snapshot()["latency_ms"])


if __name__ == "__main__":  # pragma: no cover
    main()
