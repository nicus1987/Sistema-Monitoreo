# Marco normativo y buenas prácticas

Este documento vincula cada control del motor con la normativa argentina (BCRA / UIF),
los estándares internacionales (GAFI) y de la industria (PCI DSS). Cada regla del
catálogo declara en `regulatory_refs` uno o más de los códigos de la tabla; un test
automatizado (`tests/test_rules_catalog.py`) impide publicar reglas sin trazabilidad
normativa o con códigos no documentados aquí.

> **Aviso.** Las referencias son una guía de diseño técnico. La normativa se modifica con
> frecuencia (textos ordenados del BCRA, resoluciones UIF, montos y umbrales). Antes de
> pasar a producción, el **Oficial de Cumplimiento** y **Legales** deben validar la
> vigencia de cada norma citada, los umbrales configurados en `config/parameters.yaml`
> y la adecuación a la matriz de riesgo de la entidad.

## Códigos de referencia

| Código | Norma / estándar | Qué exige y cómo lo cubre el sistema |
|---|---|---|
| `LEY-25246` | Ley 25.246 de Encubrimiento y Lavado de Activos (y modificatorias, incl. Ley 27.739) | Deber de reportar operaciones sospechosas (ROS) a la UIF y confidencialidad (prohibición de *tipping-off*). El motor detecta tipologías (fraccionamiento, cuenta puente) y el flujo de alertas escala a Cumplimiento para decidir el ROS; nunca se informa al cliente el motivo. |
| `LEY-26734` | Ley 26.734 — Financiamiento del Terrorismo | Prevención del FT. Reglas `CMN-001`, `CIN-008`, `COUT-009` bloquean operaciones con personas listadas. |
| `DEC-918-2012` | Decreto 918/2012 — Congelamiento administrativo de bienes vinculados a FT | Ante coincidencia con RePET / listas ONU: rechazo inmediato + alerta CRÍTICA para que Cumplimiento evalúe congelamiento y comunicación a la UIF sin demora. |
| `UIF-FT` | Resoluciones UIF sobre reporte de FT y congelamiento (Res. UIF 29/2013 y complementarias) | Reporte de operaciones sospechosas de FT en plazo abreviado. Las alertas de categoría `CFT` tienen SLA de 1 hora. |
| `UIF-EEFF` | Resolución UIF aplicable a Entidades Financieras y Cambiarias (Res. UIF 14/2023 o la que la reemplace) | Enfoque basado en riesgo, debida diligencia del cliente, perfil transaccional, monitoreo con reglas parametrizables, análisis de operaciones inusuales y conservación de documentación. Cubierto por el perfilado (`profile_usage_ratio_30d`), reglas de inusualidad y el registro de auditoría. |
| `UIF-PSP` | Resolución UIF aplicable a Proveedores de Servicios de Pago que ofrecen cuentas de pago (Res. UIF 76/2019 o la que la reemplace) | Obligaciones PLA/FT para billeteras / CVU: monitoreo de cash-in/cash-out, perfil del cliente, adquirencia y comercios adheridos. |
| `UIF-PEP` | Resolución UIF sobre Personas Expuestas Políticamente (Res. UIF 35/2023) | Debida diligencia reforzada para PEP. Reglas `CIN-010`, `COUT-020`. |
| `BCRA-A7724` | Com. "A" 7724 — Requisitos mínimos para la gestión y control de los riesgos de tecnología y seguridad de la información | Trazabilidad, integridad y no repudio de registros (auditoría encadenada por hash), gestión de cambios (versionado de reglas), control de accesos (API keys con separación cliente/administrador), monitoreo de fraude en canales electrónicos, continuidad (política de *fallback*). |
| `BCRA-PUSF` | Texto ordenado "Protección de los usuarios de servicios financieros" | Deber de las entidades de implementar mecanismos de prevención y detección de fraude que protejan al usuario (ingeniería social, toma de cuentas, cuentas mula), y de gestionar reclamos. Reglas de ATO, beneficiario nuevo, mulas. |
| `BCRA-TRANSF` | Texto ordenado "Sistema Nacional de Pagos — Transferencias" (transferencias inmediatas, DEBIN, Transferencias 3.0 / QR interoperable) | Las transferencias inmediatas son irrevocables: el control debe ser previo (síncrono) y con baja latencia. El motor responde en < 100 ms (p99). |
| `PCI-DSS` | PCI Data Security Standard v4.x | Nunca se recibe ni se almacena el PAN: la tarjeta se identifica con `card_fingerprint` (token), BIN y últimos 4. El modelo rechaza textos libres con números de tarjeta. Reglas de card testing, CVV, BIN comprometido. |
| `GAFI-R1` | GAFI Recomendación 1 — Enfoque basado en riesgo | Umbrales y acciones diferenciados por nivel de riesgo del cliente (`risk_level`) y por canal. |
| `GAFI-R6` | GAFI Recomendación 6 — Sanciones financieras dirigidas (terrorismo) | Screening en tiempo real contra listas de sanciones. |
| `GAFI-R10` | GAFI Recomendación 10 — Debida diligencia del cliente | Validación de KYC, origen de fondos en efectivo, comercios nuevos. |
| `GAFI-R12` | GAFI Recomendación 12 — PEP | Reglas PEP. |
| `GAFI-R19` | GAFI Recomendación 19 — Países de mayor riesgo | Lista `high_risk_countries`, a actualizar tras cada plenario del GAFI. |
| `GAFI-R20` | GAFI Recomendación 20 — Reporte de operaciones sospechosas | Tipologías de lavado (fraccionamiento, fan-in/fan-out, cuenta puente) que alimentan el análisis para ROS. |

## Otras normas y lineamientos considerados en el diseño

- **Ley 25.326 de Protección de Datos Personales**: minimización de datos, finalidad y
  seguridad. El motor sólo requiere los datos necesarios para evaluar el riesgo; los
  identificadores de cuenta de contraparte pueden llegar hasheados.
- **Com. "A" 7266 — Lineamientos para la respuesta y recuperación ante ciberincidentes**:
  métricas y alertas de latencia/fallas del motor (`/metrics`) para integrarse al SOC.
- **Ley 25.065 de Tarjetas de Crédito**: contexto del negocio de adquirencia.
- **Conservación de registros**: la normativa PLA/FT exige conservar la documentación
  de las operaciones por un plazo mínimo (usualmente 10 años). El `AuditLog` debe
  persistirse en almacenamiento WORM / inmutable con esa retención.

## Principios operativos aplicados

1. **Enfoque basado en riesgo**: parámetros y umbrales configurables por canal y segmento.
2. **Control previo y en tiempo real** para operaciones irrevocables (cash-out, adquirencia).
3. **Separación de funciones y 4 ojos**: quien escala una alerta no puede resolver el ROS.
4. **Fundamentación obligatoria**: todo cierre o escalamiento de alerta exige comentario.
5. **Confidencialidad**: los motivos de rechazo de PLA/FT no se exponen al cliente.
6. **Gobierno de modelos/reglas**: modo *shadow*, backtesting, versionado y aprobación
   antes de activar (ver `docs/gobierno_de_reglas.md`).
7. **Resiliencia**: una regla con error no detiene la evaluación; si el motor falla se
   aplica una política de contingencia por canal y monto.
