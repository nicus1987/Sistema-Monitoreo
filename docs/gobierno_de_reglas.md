# Gobierno de reglas

## Ciclo de vida de una regla

1. **Propuesta** — Fraude o Cumplimiento documenta la tipología, la hipótesis, la
   referencia normativa y el impacto esperado.
2. **Desarrollo** — se agrega la regla en `config/rules/*.yaml` con `mode: shadow`.
   Los tests de CI validan sintaxis, parámetros existentes y trazabilidad normativa.
3. **Shadow / challenger** — la regla se evalúa en producción sin afectar decisiones
   (`shadow_hits` en la decisión y métrica `monitoreo_shadow_rule_hits_total`). Mínimo
   2–4 semanas o volumen estadísticamente suficiente.
4. **Calibración** — se miden tasa de disparo, precisión (alertas confirmadas / totales),
   fraude/lavado detectado y fricción (aprobaciones legítimas afectadas). Se ajustan
   parámetros en `config/parameters.yaml`.
5. **Aprobación** — cambio aprobado por el responsable del área (`owner`) y, para reglas
   PLA/FT, por el Oficial de Cumplimiento. Revisión por pares del *pull request*.
6. **Activación** — `mode: active`, despliegue y `POST /v1/admin/reload` (queda registrado
   en auditoría con usuario y versión del ruleset).
7. **Revisión periódica** — al menos semestral (y ante cambios normativos, plenarios del
   GAFI o nuevas tipologías publicadas por la UIF). Reglas sin efectividad se retiran.

## Indicadores a seguir

| KPI | Definición | Uso |
|---|---|---|
| Tasa de alertas | alertas / transacciones por canal | Capacidad del equipo de análisis |
| Precisión por regla | alertas confirmadas / alertas cerradas | Retirar o recalibrar reglas ruidosas |
| Tasa de rechazo | DECLINE / total por canal | Fricción de negocio |
| Fraude no detectado | contracargos / reclamos no alertados | Brechas de cobertura |
| SLA de alertas | alertas vencidas (`/v1/alerts/stats`) | Dotación y priorización |
| Latencia p99 | `/metrics` | SLA técnico (< 100 ms) |

## Parametrización

- Todos los umbrales viven en `config/parameters.yaml`; las reglas no tienen montos
  hardcodeados. Esto permite actualizar por inflación o por cambios normativos sin tocar
  la lógica.
- Cada recarga genera una nueva versión del ruleset (hash); cada decisión guarda la
  versión que la produjo, lo que permite reconstruir cualquier decisión ante auditoría
  interna, externa o requerimientos del BCRA/UIF.

## Separación de funciones

| Rol | Puede |
|---|---|
| Sistema autorizador (API key cliente) | Evaluar transacciones, consultar reglas |
| Analista de fraude / PLA | Tomar, cerrar y escalar alertas (con fundamento) |
| Oficial de Cumplimiento | Resolver alertas escaladas: ROS presentado / sin ROS (distinto de quien escaló) |
| Administrador (API key admin) | Recargar configuración, verificar integridad de auditoría |
