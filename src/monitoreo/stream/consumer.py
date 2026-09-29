"""Procesamiento por streaming (Kafka) para monitoreo continuo.

Dos modos de integración conviven:

1. **Síncrono (API)**: el autorizador / core consulta `POST /v1/transactions/evaluate`
   antes de aprobar (adquirencia, transferencias salientes, extracciones).
2. **Asíncrono (stream)**: eventos que no pasan por el motor en línea (p.ej.
   transferencias entrantes informadas por la cámara, depósitos en redes de
   cobranza, liquidaciones) se consumen de Kafka, se evalúan y la decisión se
   publica en un tópico de salida para retención de fondos o alerta.

El consumidor usa commit manual del offset DESPUÉS de publicar la decisión
(semántica at-least-once); la idempotencia por `transaction_id` del motor
evita doble conteo ante reprocesos.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Awaitable, Callable

from pydantic import ValidationError

from ..models import Decision, Transaction
from ..service import MonitoringService

log = logging.getLogger(__name__)

Sink = Callable[[str, bytes, bytes], Awaitable[None]]


async def process_stream(
    service: MonitoringService,
    source: AsyncIterator[bytes],
    sink: Sink,
    decisions_topic: str = "monitoreo.decisions",
    dlq_topic: str = "monitoreo.dlq",
) -> int:
    """Consume mensajes JSON, evalúa y publica. Devuelve la cantidad procesada."""
    processed = 0
    async for raw in source:
        try:
            txn = Transaction.model_validate_json(raw)
        except ValidationError as exc:
            log.warning("Mensaje inválido enviado a DLQ: %s", exc.errors()[:1])
            await sink(dlq_topic, b"invalid", json.dumps({"error": str(exc), "raw": raw.decode(errors="replace")}).encode())
            continue
        decision: Decision = await asyncio.to_thread(service.evaluate, txn)
        await sink(decisions_topic, txn.transaction_id.encode(), decision.model_dump_json(exclude={"features"}).encode())
        processed += 1
    return processed


async def run_kafka(service: MonitoringService, bootstrap: str, topics: list[str], group_id: str) -> None:  # pragma: no cover
    try:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    except ImportError as exc:
        raise SystemExit("Instale el extra kafka: pip install '.[kafka]'") from exc

    consumer = AIOKafkaConsumer(*topics, bootstrap_servers=bootstrap, group_id=group_id,
                                enable_auto_commit=False, auto_offset_reset="earliest")
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap, acks="all", enable_idempotence=True)
    await consumer.start()
    await producer.start()

    async def sink(topic: str, key: bytes, value: bytes) -> None:
        await producer.send_and_wait(topic, value=value, key=key)

    async def source() -> AsyncIterator[bytes]:
        async for msg in consumer:
            yield msg.value
            await consumer.commit()

    try:
        await process_stream(service, source(), sink)
    finally:
        await consumer.stop()
        await producer.stop()


def main() -> None:  # pragma: no cover
    import os

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    service = MonitoringService(audit_path=os.getenv("MONITOREO_AUDIT_PATH"))
    asyncio.run(run_kafka(
        service,
        bootstrap=os.getenv("KAFKA_BOOTSTRAP", "localhost:9092"),
        topics=os.getenv("KAFKA_TOPICS", "tx.acquiring,tx.cash_in,tx.cash_out").split(","),
        group_id=os.getenv("KAFKA_GROUP", "monitoreo-engine"),
    ))


if __name__ == "__main__":  # pragma: no cover
    main()
