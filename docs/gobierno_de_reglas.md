# Gobierno de reglas

## Ciclo de vida de una regla

1. **Propuesta** — Fraude o Cumplimiento documenta la tipología, la hipótesis, la
   referencia normativa y el impacto esperado.
2. **Desarrollo** — se crea la regla desde la consola (pestaña Reglas) o en `config/rules/*.yaml`,
   siempre en modo **sombra**. La consola valida sintaxis, parámetros y listas existentes y
   referencia normativa antes de guardar; los tests de CI validan lo mismo para los archivos.
   Antes de guardar se usa **Probar con tráfico reciente** para estimar tasa de disparo e impacto.
3. **Shadow / challenger** — la regla se evalúa en producción sin afectar decisiones
   (`shadow_hits` en la decisión y métrica `monitoreo_shadow_rule_hits_total`). Mínimo
   2–4 semanas o volumen estadísticamente suficiente.
4. **Calibración** — se miden tasa de disparo, precisión (alertas confirmadas / totales),
   fraude/lavado detectado y fricción (aprobaciones legítimas afectadas). Se ajustan
   parámetros desde la pestaña Parámetros (con **Ver impacto** antes de guardar) o en
   `config/parameters.yaml`.
5. **Aprobación** — cambio aprobado por el responsable del área (`owner`) y, para reglas
   PLA/FT, por el Oficial de Cumplimiento. Revisión por pares del *pull request*.
6. **Activación** — cambio de estado a **Activa** desde la consola (o `mode: active` y
   `POST /v1/admin/reload`). Queda registrado en el Historial de cambios con usuario, valores
   anteriores y nuevos, y la versión de configuración resultante.
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
| Administrador (API key admin) | Crear/modificar reglas y parámetros, recargar configuración, verificar integridad de auditoría |
