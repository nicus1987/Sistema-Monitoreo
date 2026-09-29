# Sistema de Monitoreo Transaccional — Fraude y PLA/FT

Motor de reglas en **tiempo real** para evaluar transacciones de **adquirencia**, **cash-in**
y **cash-out**, identificar operaciones riesgosas y **rechazarlas, retenerlas o alertarlas**,
alineado a la normativa del **BCRA** y la **UIF** y a las buenas prácticas del sistema
financiero (GAFI, PCI DSS).

- **64 reglas** parametrizables en YAML (fraude, lavado de activos, financiamiento del terrorismo).
- **~70 features en tiempo real**: velocidad, acumulados, perfil transaccional, viaje
  imposible, cuenta puente, fraccionamiento, fan-in/fan-out, dispositivos compartidos.
- **Decisión < 1 ms p50** en proceso (SLA configurado: 100 ms p99), vía API REST síncrona o
  consumo de Kafka.
- **Auditoría inmutable** encadenada por hash, versionado de reglas, modo *shadow*,
  gestión de alertas con 4 ojos para ROS, política de contingencia ante fallas.

## Inicio rápido

```bash
pip install -e ".[dev]"
python -m pytest                       # 40 tests: reglas, escenarios, API, auditoría, stream
python -m monitoreo                    # API en http://localhost:8000  (dashboard en /)
python -m monitoreo.simulator --url http://localhost:8000 --rate 20   # tráfico + escenarios de fraude
```

Documentación interactiva de la API: `http://localhost:8000/docs`.

### Ejemplo: evaluar un cash-out

```bash
curl -s localhost:8000/v1/transactions/evaluate -H 'Content-Type: application/json' -d '{
  "transaction_id": "TX-0001", "channel": "CASH_OUT", "method": "TRANSFER", "amount": 2000000,
  "customer": {"customer_id": "C-1", "cuit": "20-11111111-2", "declared_monthly_income_ars": 1500000,
               "account_opened_at": "2026-09-20T10:00:00Z"},
  "counterparty": {"account_id": "CVU-DEST-1"},
  "device": {"device_id": "D-NUEVO", "ip": "190.1.2.3", "session_age_seconds": 40}
}'
```

```json
{"transaction_id": "TX-0001", "action": "DECLINE", "risk_score": 97,
 "reason_codes": ["COUT-002", "COUT-003", "COUT-004"],
 "reasons": ["Cuenta de 9.48 días egresa ARS 2,000,000.00",
             "Primera transferencia a CVU-DEST-1 por ARS 2,000,000.00",
             "Dispositivo nuevo, beneficiario nuevo y sesión de 40.00s"],
 "alert_id": "ALR-6CA13D655A49", "ruleset_version": "e407bad72d55", "latency_ms": 1.07, "fallback": false}
```

## Cómo decide

1. Cada regla activa que se cumple aporta su `score` y su `action`.
2. Los scores se combinan con **noisy-OR** (`1 − Π(1 − sᵢ/100)`): varias señales débiles
   suman riesgo, pero el resultado se mantiene en 0–100.
3. La acción final es la **más severa** entre la acción de las reglas y la que indican los
   umbrales del canal (`decision_thresholds` en `config/parameters.yaml`).
4. `REVIEW` o `DECLINE` con reglas disparadas generan una **alerta** con SLA por severidad.

## Estructura

```
config/
  parameters.yaml          umbrales y políticas (calibrar con Cumplimiento)
  rules/                   catálogo de reglas: 00_common, 10_acquiring, 20_cash_in, 30_cash_out
  lists/                   sanciones, mulas, BINs, dispositivos, GAFI, MCC de riesgo, contrapartes confiables
src/monitoreo/
  models.py                transacción canónica y decisión
  features/                feature store y cálculo de features en tiempo real
  engine/                  evaluador seguro de expresiones y motor de reglas
  service.py               orquestación, scoring, idempotencia, fallback, métricas
  alerts.py                casos, SLA, flujo de ROS con 4 ojos
  audit/                   log de auditoría inmutable
  api/                     FastAPI + SSE + dashboard en vivo
  stream/                  consumidor Kafka con DLQ
  simulator.py             tráfico sintético y escenarios de fraude/lavado
docs/
  marco_normativo.md       mapeo BCRA / UIF / GAFI / PCI de cada control
  catalogo_reglas.md       catálogo completo (autogenerado)
  arquitectura.md          diseño, semántica de acciones, escalado a producción
  gobierno_de_reglas.md    ciclo de vida, KPIs, separación de funciones
```

## API

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/v1/transactions/evaluate` | Evaluación síncrona (`?include_features=true` para depurar) |
| POST | `/v1/transactions/evaluate/batch` | Hasta 1000 transacciones |
| GET | `/v1/rules` | Catálogo vigente y versión |
| GET | `/v1/alerts`, `/v1/alerts/{id}`, `/v1/alerts/stats` | Bandeja de alertas |
| POST | `/v1/alerts/{id}/transition` | Tomar / cerrar / escalar / ROS (cabecera `X-User`) |
| GET | `/v1/stream/decisions` | Decisiones en vivo (Server-Sent Events) |
| POST | `/v1/admin/reload` | Recarga atómica de reglas, listas y parámetros (admin) |
| GET | `/v1/audit/verify` | Verifica integridad de la cadena de auditoría (admin) |
| GET | `/metrics`, `/health` | Prometheus y salud |

Autenticación: variables `MONITOREO_API_KEYS` (sistemas cliente) y `MONITOREO_ADMIN_KEYS`
(administración), separadas por coma, enviadas en la cabecera `X-API-Key`. Sin claves
configuradas la API corre en modo desarrollo (se registra una advertencia).

## Agregar o modificar una regla

```yaml
- id: COUT-099
  name: Egreso a cripto-exchange desde cuenta nueva
  channels: [CASH_OUT]
  category: AML            # FRAUD | AML | CFT | OPERATIONAL
  severity: HIGH           # LOW | MEDIUM | HIGH | CRITICAL
  action: REVIEW           # APPROVE | REVIEW | DECLINE
  score: 60
  mode: shadow             # empezar siempre en shadow
  condition: >
    in_list('vasp_accounts', txn.counterparty.account_id)
    and feat.account_age_days < p.new_account_days
  reason: "Egreso a VASP desde cuenta de {feat.account_age_days} días"
  regulatory_refs: [UIF-EEFF, GAFI-R10]
```

Luego: `python -m pytest && python scripts/generar_catalogo.py` y `POST /v1/admin/reload`.
Las condiciones admiten `txn.*` (transacción), `feat.*` (features), `p.*` (parámetros) y las
funciones `in_list`, `prefix_in_list`, `between`, `coalesce`, `min`, `max`, `abs`, `round`,
`len`, `startswith`, `upper`. No se permite ejecutar código arbitrario.

## Importante antes de producción

Los umbrales incluidos son **valores de referencia**: deben calibrarse con datos propios
(backtesting + período *shadow*) y validarse con el **Oficial de Cumplimiento** contra la
normativa vigente al momento del despliegue. Las listas de ejemplo son ficticias; deben
sincronizarse con las fuentes oficiales (RePET, ONU, nómina PEP, GAFI). Ver
`docs/arquitectura.md` → *Escalado a producción*.
