# Arquitectura

```
                    ┌────────────────────────── Síncrono (pre-autorización) ─────────────────────────┐
 Autorizador POS /  │                                                                                │
 Gateway e-comm ────┤  POST /v1/transactions/evaluate  ──►  MonitoringService.evaluate()            │
 Core / Home banking│        (< 100 ms p99)                   │                                      │
 Red ATM / cobranza │                                         ├─ 1. Validación (Pydantic, sin PAN)   │
                    │                                         ├─ 2. Idempotencia (transaction_id)    │
                    └─────────────────────────────────────────┤─ 3. Features en tiempo real          │
                                                              │     (BehaviorStore: ventanas 10m…90d)│
 Kafka tx.acquiring ─┐                                        ├─ 4. Listas (sanciones, PEP, GAFI,    │
 Kafka tx.cash_in   ─┼─► stream.consumer ─────────────────────┤     mulas, BINs, dispositivos)       │
 Kafka tx.cash_out  ─┘  (asíncrono, at-least-once)            ├─ 5. Reglas YAML (evaluador seguro)   │
                                                              ├─ 6. Score noisy-OR + umbrales canal  │
                                                              ├─ 7. Decisión APPROVE/REVIEW/DECLINE  │
                                                              ├─ 8. Registro de historia             │
                                                              ├─ 9. Alerta / caso (si corresponde)   │
                                                              └─10. Auditoría encadenada (hash)      │
                                                                         │
                     monitoreo.decisions (Kafka) ◄───────────────────────┤
                     /v1/stream/decisions (SSE, dashboard) ◄─────────────┤
                     /metrics (Prometheus) ◄─────────────────────────────┘
```

## Componentes

| Módulo | Responsabilidad |
|---|---|
| `models.py` | Modelo canónico de transacción para los 3 canales. Rechaza PAN en texto libre; exige `amount_ars` en moneda extranjera. |
| `features/store.py` | `BehaviorStore`: historia por entidad (tarjeta, comercio, cliente-entrada, cliente-salida, contraparte, dispositivo, IP) con ventanas deslizantes. Implementación en memoria; interfaz lista para Redis/Aerospike en despliegues multi-réplica. |
| `features/extractor.py` | ~70 features: velocidad, montos acumulados, distintos (comercios, beneficiarios, originantes), viaje imposible, perfil vs ingresos declarados, z-score, cuenta puente, fraccionamiento, dispositivo/IP compartidos. |
| `engine/expression.py` | Evaluador de condiciones sin `eval`: AST en lista blanca, *null-safe*. |
| `engine/rules.py` | Carga y valida el catálogo YAML; versión = hash SHA-256 del contenido. Una regla con error se aísla y se registra, no detiene la evaluación. |
| `service.py` | Orquestación, decisión, idempotencia, locks por entidad, métricas, política de *fallback*. |
| `alerts.py` | Casos para analistas con SLA por severidad, transiciones controladas, fundamento obligatorio y 4 ojos para ROS. |
| `audit/log.py` | Registro append-only encadenado por hash, verificable (`/v1/audit/verify`). |
| `api/app.py` | API REST, SSE en vivo, dashboard, métricas Prometheus, autenticación por API key (cliente / admin). |
| `stream/consumer.py` | Consumidor Kafka con DLQ para mensajes inválidos y commit tras publicar. |

## Semántica de las acciones

| Acción | Adquirencia | Cash-in | Cash-out |
|---|---|---|---|
| `APPROVE` | Autorizar | Acreditar | Ejecutar |
| `REVIEW` | Autorizar y alertar (o *step-up* 3DS según integración) | Acreditar con fondos retenidos / bloqueo preventivo y alerta | Retener la transferencia hasta revisión del analista |
| `DECLINE` | Rechazar | Rechazar / devolver al originante (sanciones: congelar según procedimiento) | Rechazar |

Los rechazos se registran como **intentos** (cuentan para velocidad y rechazos
reiterados) pero no suman a montos acumulados ni a límites.

## Concurrencia y consistencia

- Locks por entidad principal (256 *stripes*): dos operaciones simultáneas de la misma
  tarjeta o cliente se serializan, evitando que ambas "no se vean" y eludan un límite.
- Idempotencia por `transaction_id`: un reintento del autorizador o un reproceso de Kafka
  devuelve la misma decisión sin duplicar historia.

## Escalado a producción

1. Reemplazar `InMemoryBehaviorStore` por un backend compartido (Redis Cluster con
   sorted sets por entidad y TTL de 90 días) para correr N réplicas detrás de un balanceador.
2. Persistir `AuditLog` en almacenamiento inmutable (WORM / object lock) con retención ≥ 10 años.
3. Persistir alertas en base transaccional (PostgreSQL) e integrarlas con la herramienta de
   gestión de casos y el circuito de ROS.
4. Sincronizar listas (RePET, ONU, PEP, GAFI) con jobs programados y `POST /v1/admin/reload`.
5. Poner la API detrás de mTLS / API gateway y SSO para el dashboard (el `EventSource`
   del navegador no envía cabeceras de API key).
6. Monitorear `monitoreo_latency_ms`, `engine_failures_total`, `rule_errors_total` y
   `latency_budget_exceeded_total` desde el SOC.
