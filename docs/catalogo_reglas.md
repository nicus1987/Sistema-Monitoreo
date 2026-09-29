# Catálogo de reglas

Generado automáticamente desde `config/rules/` — versión del ruleset `e407bad72d55`, 64 reglas. No editar a mano: ejecutar `python scripts/generar_catalogo.py`.

Decisión final = acción más severa entre (a) la acción de cada regla activa disparada y (b) el score combinado (noisy-OR) contra los umbrales del canal:

| Canal | Revisión desde | Rechazo desde |
|---|---|---|
| ACQUIRING | 60 | 85 |
| CASH_IN | 50 | 90 |
| CASH_OUT | 50 | 80 |

## Adquirencia

| ID | Regla | Categoría | Severidad | Acción | Score | Modo | Condición | Normativa |
|---|---|---|---|---|---|---|---|---|
| CMN-001 | Cliente en listas de sanciones / terrorismo | CFT | CRITICAL | DECLINE | 100 | active | `in_list('sanctions', txn.customer.cuit)` | LEY-26734, DEC-918-2012, UIF-FT, GAFI-R6 |
| CMN-002 | Dispositivo en lista negra | FRAUD | CRITICAL | DECLINE | 95 | active | `in_list('blocked_devices', txn.device.device_id)` | BCRA-A7724, BCRA-PUSF |
| CMN-003 | Operación de monto muy elevado | AML | HIGH | REVIEW | 60 | active | `txn.amount_ars >= p.very_high_amount_ars` | UIF-EEFF, GAFI-R10 |
| ACQ-001 | Testeo de tarjetas (card testing) | FRAUD | HIGH | DECLINE | 90 | active | `txn.amount_ars <= p.card_testing_max_amount_ars and feat.card_small_txn_count_1h >= p.card_testing_min_attempts_1h` | PCI-DSS, BCRA-A7724 |
| ACQ-002 | Velocidad de tarjeta 10 minutos (no presente) | FRAUD | HIGH | DECLINE | 80 | active | `feat.card_not_present and feat.card_count_10m >= p.card_velocity_10m` | BCRA-A7724 |
| ACQ-003 | Velocidad de tarjeta 1 hora | FRAUD | MEDIUM | REVIEW | 45 | active | `feat.card_count_1h >= p.card_velocity_1h` | BCRA-A7724 |
| ACQ-004 | Rechazos reiterados de la tarjeta | FRAUD | HIGH | DECLINE | 85 | active | `feat.card_declines_1h >= p.card_max_declines_1h` | BCRA-A7724 |
| ACQ-005 | Tarjeta en múltiples comercios (no presente) | FRAUD | MEDIUM | REVIEW | 55 | active | `feat.card_not_present and feat.card_distinct_merchants_1h >= p.card_distinct_merchants_1h` | BCRA-A7724 |
| ACQ-006 | Viaje imposible | FRAUD | CRITICAL | DECLINE | 90 | active | `not feat.card_not_present and feat.card_geo_speed_kmh > p.impossible_travel_kmh` | BCRA-A7724 |
| ACQ-007 | Monto alto no presente sin autenticación 3DS | FRAUD | HIGH | DECLINE | 75 | active | `feat.card_not_present and txn.three_ds_authenticated != True and txn.amount_ars >= p.high_amount_ars` | BCRA-PUSF, PCI-DSS |
| ACQ-008 | CVV no coincide | FRAUD | HIGH | DECLINE | 90 | active | `txn.cvv_match == False` | PCI-DSS |
| ACQ-009 | Ingreso manual de tarjeta con monto alto | FRAUD | MEDIUM | REVIEW | 40 | active | `txn.entry_mode == 'MANUAL' and txn.amount_ars >= p.high_amount_ars / 2` | PCI-DSS |
| ACQ-010 | Banda magnética (posible clonación / fallback) | FRAUD | MEDIUM | REVIEW | 40 | active | `txn.entry_mode == 'MAGSTRIPE'` | PCI-DSS |
| ACQ-011 | País emisor distinto al país de la IP (no presente) | FRAUD | LOW | REVIEW | 35 | active | `feat.card_not_present and feat.bin_country_mismatch` | BCRA-A7724 |
| ACQ-012 | BIN comprometido | FRAUD | CRITICAL | DECLINE | 100 | active | `prefix_in_list('blocked_bins', txn.card.bin)` | PCI-DSS |
| ACQ-013 | Ticket anómalo para el comercio | FRAUD | MEDIUM | REVIEW | 50 | active | `feat.merchant_history_count_30d >= p.merchant_min_history and feat.merchant_ticket_ratio >= p.merchant_ticket_ratio_max` | UIF-EEFF, GAFI-R10 |
| ACQ-014 | Ataque de enumeración sobre comercio | FRAUD | CRITICAL | DECLINE | 85 | active | `feat.merchant_distinct_cards_1h >= p.merchant_distinct_cards_1h and feat.merchant_decline_ratio_1h >= p.merchant_decline_ratio_max` | PCI-DSS, BCRA-A7724 |
| ACQ-015 | Comercio nuevo con volumen elevado | AML | HIGH | REVIEW | 60 | active | `feat.merchant_age_days < p.merchant_new_days and feat.merchant_sum_24h_incl > p.merchant_new_daily_amount_ars` | UIF-EEFF, UIF-PSP, GAFI-R10 |
| ACQ-016 | MCC de alto riesgo con monto alto | AML | MEDIUM | REVIEW | 40 | active | `in_list('high_risk_mcc', txn.merchant.mcc) and txn.amount_ars >= p.high_amount_ars` | UIF-EEFF, GAFI-R10 |
| ACQ-017 | Tarjeta o comercio de jurisdicción de alto riesgo | AML | HIGH | REVIEW | 60 | active | `in_list('high_risk_countries', txn.card.issuer_country) or in_list('high_risk_countries', txn.merchant.country)` | GAFI-R19, UIF-EEFF |
| ACQ-018 | Tarjeta nueva, no presente, nocturna y monto alto | FRAUD | MEDIUM | REVIEW | 45 | active | `feat.is_night and feat.card_not_present and feat.card_is_new and txn.amount_ars >= p.high_amount_ars / 2` | BCRA-A7724 |
| ACQ-019 | Monto diario de tarjeta excedido | FRAUD | MEDIUM | REVIEW | 55 | active | `feat.card_sum_24h_incl > p.card_daily_amount_ars` | BCRA-A7724 |
| ACQ-020 | Concentración de tarjetas extranjeras en comercio | FRAUD | LOW | REVIEW | 40 | shadow | `feat.merchant_count_1h >= 10 and feat.merchant_foreign_card_ratio_1h > p.merchant_foreign_ratio_max` | BCRA-A7724 |
| ACQ-021 | Dispositivo emulado o rooteado (no presente) | FRAUD | HIGH | REVIEW | 60 | active | `feat.card_not_present and (txn.device.is_emulator or txn.device.is_rooted)` | BCRA-A7724 |
| ACQ-022 | Comercio bloqueado | FRAUD | CRITICAL | DECLINE | 100 | active | `in_list('blocked_merchants', txn.merchant.merchant_id)` | UIF-PSP |
| ACQ-023 | Fraccionamiento de venta en el mismo comercio | FRAUD | MEDIUM | REVIEW | 45 | active | `feat.card_same_merchant_count_1h >= 3 and not txn.is_recurring` | BCRA-A7724 |

## Cash-in

| ID | Regla | Categoría | Severidad | Acción | Score | Modo | Condición | Normativa |
|---|---|---|---|---|---|---|---|---|
| CMN-001 | Cliente en listas de sanciones / terrorismo | CFT | CRITICAL | DECLINE | 100 | active | `in_list('sanctions', txn.customer.cuit)` | LEY-26734, DEC-918-2012, UIF-FT, GAFI-R6 |
| CMN-002 | Dispositivo en lista negra | FRAUD | CRITICAL | DECLINE | 95 | active | `in_list('blocked_devices', txn.device.device_id)` | BCRA-A7724, BCRA-PUSF |
| CMN-003 | Operación de monto muy elevado | AML | HIGH | REVIEW | 60 | active | `txn.amount_ars >= p.very_high_amount_ars` | UIF-EEFF, GAFI-R10 |
| CIN-001 | Fraccionamiento de ingresos (structuring) | AML | HIGH | REVIEW | 70 | active | `feat.near_threshold_count_7d >= p.structuring_min_count_7d` | LEY-25246, UIF-EEFF, GAFI-R20 |
| CIN-002 | Depósito en efectivo elevado | AML | HIGH | REVIEW | 60 | active | `txn.method == 'CASH' and txn.amount_ars >= p.cash_deposit_high_ars` | UIF-EEFF, GAFI-R10 |
| CIN-003 | Acumulado mensual de efectivo excedido | AML | HIGH | REVIEW | 65 | active | `txn.method == 'CASH' and feat.cash_method_sum_30d_incl > p.cash_monthly_cap_ars` | UIF-EEFF, GAFI-R10 |
| CIN-004 | Múltiples originantes hacia una cuenta (fan-in) | AML | HIGH | REVIEW | 70 | active | `feat.cashin_distinct_senders_24h >= p.fan_in_distinct_senders_24h and not in_list('trusted_counterparties', txn.counterparty.account_id)` | UIF-EEFF, BCRA-PUSF, GAFI-R20 |
| CIN-005 | Cuenta nueva con ingresos elevados | AML | HIGH | REVIEW | 65 | active | `feat.account_age_days < p.new_account_days and feat.cashin_sum_24h_incl >= p.new_account_cashin_24h_ars` | UIF-EEFF, GAFI-R10 |
| CIN-006 | Ingresos superan el perfil transaccional | AML | MEDIUM | REVIEW | 55 | active | `feat.profile_usage_ratio_30d >= p.profile_usage_ratio_review and feat.profile_usage_ratio_30d < p.profile_usage_ratio_critical` | UIF-EEFF, UIF-PSP |
| CIN-007 | Ingresos muy superiores al perfil transaccional | AML | HIGH | REVIEW | 80 | active | `feat.profile_usage_ratio_30d >= p.profile_usage_ratio_critical` | UIF-EEFF, UIF-PSP, LEY-25246 |
| CIN-008 | Originante en listas de sanciones | CFT | CRITICAL | DECLINE | 100 | active | `in_list('sanctions', txn.counterparty.cuit)` | LEY-26734, DEC-918-2012, UIF-FT, GAFI-R6 |
| CIN-009 | Fondos desde jurisdicción de alto riesgo | AML | HIGH | REVIEW | 70 | active | `in_list('high_risk_countries', txn.counterparty.country)` | GAFI-R19, UIF-EEFF |
| CIN-010 | PEP con operación relevante | AML | MEDIUM | REVIEW | 50 | active | `txn.customer.is_pep and txn.amount_ars >= p.high_amount_ars` | UIF-PEP, GAFI-R12 |
| CIN-011 | Cliente de riesgo alto con monto alto | AML | MEDIUM | REVIEW | 45 | active | `txn.customer.risk_level == 'HIGH' and txn.amount_ars >= p.high_amount_ars` | UIF-EEFF, GAFI-R1 |
| CIN-012 | Monto atípico respecto del histórico del cliente | AML | MEDIUM | REVIEW | 45 | active | `feat.history_count_90d >= p.min_history_for_profile and (feat.amount_zscore >= p.amount_zscore_max or feat.amount_to_avg_ratio >= p.amount_to_avg_ratio_max)` | UIF-EEFF |
| CIN-013 | Cliente sin KYC verificado con monto relevante | AML | HIGH | REVIEW | 60 | active | `txn.customer.kyc_verified == False and txn.amount_ars >= p.structuring_threshold_ars * 0.5` | UIF-EEFF, UIF-PSP, GAFI-R10 |
| CIN-014 | Velocidad de ingresos | AML | MEDIUM | REVIEW | 40 | active | `feat.cashin_count_1h >= p.cashin_velocity_1h` | UIF-EEFF |
| CIN-015 | Efectivo en montos redondos | AML | LOW | REVIEW | 20 | shadow | `txn.method == 'CASH' and feat.is_round_amount` | UIF-EEFF |
| CIN-016 | Originante que fondea a múltiples clientes | AML | HIGH | REVIEW | 60 | active | `feat.cpty_distinct_customers_24h >= p.mule_counterparty_customers_24h and not in_list('trusted_counterparties', txn.counterparty.account_id)` | UIF-EEFF, GAFI-R20 |
| CIN-017 | Originante en lista negra interna (mula) | FRAUD | CRITICAL | DECLINE | 95 | active | `in_list('mule_accounts', txn.counterparty.account_id)` | BCRA-PUSF |

## Cash-out

| ID | Regla | Categoría | Severidad | Acción | Score | Modo | Condición | Normativa |
|---|---|---|---|---|---|---|---|---|
| CMN-001 | Cliente en listas de sanciones / terrorismo | CFT | CRITICAL | DECLINE | 100 | active | `in_list('sanctions', txn.customer.cuit)` | LEY-26734, DEC-918-2012, UIF-FT, GAFI-R6 |
| CMN-002 | Dispositivo en lista negra | FRAUD | CRITICAL | DECLINE | 95 | active | `in_list('blocked_devices', txn.device.device_id)` | BCRA-A7724, BCRA-PUSF |
| CMN-003 | Operación de monto muy elevado | AML | HIGH | REVIEW | 60 | active | `txn.amount_ars >= p.very_high_amount_ars` | UIF-EEFF, GAFI-R10 |
| COUT-001 | Cuenta puente (pass-through) | AML | HIGH | REVIEW | 75 | active | `feat.minutes_since_last_cashin <= p.passthrough_minutes and feat.passthrough_ratio_24h >= p.passthrough_ratio and feat.cashin_sum_24h >= p.passthrough_min_cashin_ars` | LEY-25246, UIF-EEFF, UIF-PSP, GAFI-R20 |
| COUT-002 | Cuenta nueva con egreso relevante | FRAUD | MEDIUM | REVIEW | 55 | active | `feat.account_age_days < p.new_account_days and txn.amount_ars >= p.new_account_cashout_ars` | UIF-EEFF, BCRA-PUSF |
| COUT-003 | Beneficiario nuevo con monto alto | FRAUD | MEDIUM | REVIEW | 50 | active | `feat.is_new_beneficiary and txn.amount_ars >= p.new_beneficiary_high_ars` | BCRA-PUSF, BCRA-TRANSF |
| COUT-004 | Toma de cuenta (ATO) - dispositivo nuevo + beneficiario nuevo + sesión corta | FRAUD | CRITICAL | DECLINE | 85 | active | `feat.is_new_device and feat.is_new_beneficiary and txn.device.session_age_seconds < p.new_device_session_seconds` | BCRA-A7724, BCRA-PUSF |
| COUT-005 | Dispositivo emulado o rooteado | FRAUD | HIGH | REVIEW | 60 | active | `txn.device.is_emulator or txn.device.is_rooted` | BCRA-A7724 |
| COUT-006 | Dispersión a múltiples beneficiarios (fan-out) | AML | HIGH | REVIEW | 65 | active | `feat.cashout_distinct_beneficiaries_24h >= p.fan_out_distinct_beneficiaries_24h` | UIF-EEFF, GAFI-R20 |
| COUT-007 | Límite diario de egresos excedido | OPERATIONAL | MEDIUM | DECLINE | 80 | active | `feat.cashout_sum_24h_incl > p.cashout_daily_limit_ars` | BCRA-PUSF |
| COUT-008 | Velocidad de egresos | FRAUD | MEDIUM | REVIEW | 50 | active | `feat.cashout_count_1h >= p.cashout_velocity_1h` | BCRA-A7724 |
| COUT-009 | Beneficiario en listas de sanciones | CFT | CRITICAL | DECLINE | 100 | active | `in_list('sanctions', txn.counterparty.cuit)` | LEY-26734, DEC-918-2012, UIF-FT, GAFI-R6 |
| COUT-010 | Envío a jurisdicción de alto riesgo | AML | HIGH | REVIEW | 75 | active | `in_list('high_risk_countries', txn.counterparty.country)` | GAFI-R19, UIF-EEFF |
| COUT-011 | Beneficiario en lista negra interna (mula) | FRAUD | CRITICAL | DECLINE | 100 | active | `in_list('mule_accounts', txn.counterparty.account_id)` | BCRA-PUSF |
| COUT-012 | Egreso nocturno a beneficiario nuevo | FRAUD | MEDIUM | REVIEW | 45 | active | `feat.is_night and feat.is_new_beneficiary and txn.amount_ars >= p.new_account_cashout_ars` | BCRA-PUSF |
| COUT-013 | Fraccionamiento de egresos (structuring) | AML | HIGH | REVIEW | 65 | active | `feat.near_threshold_count_7d >= p.structuring_min_count_7d` | LEY-25246, UIF-EEFF, GAFI-R20 |
| COUT-014 | Dispositivo compartido por múltiples clientes | FRAUD | HIGH | REVIEW | 60 | active | `feat.device_distinct_subjects_24h >= p.device_distinct_subjects_24h` | BCRA-A7724 |
| COUT-015 | Egresos superan el perfil transaccional | AML | MEDIUM | REVIEW | 55 | active | `feat.profile_usage_ratio_30d >= p.profile_usage_ratio_review` | UIF-EEFF, UIF-PSP |
| COUT-016 | Beneficiario que recibe de múltiples clientes (mula / estafa) | FRAUD | HIGH | REVIEW | 70 | active | `feat.cpty_distinct_customers_24h >= p.mule_counterparty_customers_24h and not in_list('trusted_counterparties', txn.counterparty.account_id)` | BCRA-PUSF, UIF-EEFF |
| COUT-017 | Monto atípico respecto del histórico del cliente | FRAUD | MEDIUM | REVIEW | 45 | active | `feat.history_count_90d >= p.min_history_for_profile and (feat.amount_zscore >= p.amount_zscore_max or feat.amount_to_avg_ratio >= p.amount_to_avg_ratio_max)` | BCRA-PUSF |
| COUT-018 | Intentos rechazados reiterados | FRAUD | HIGH | DECLINE | 70 | active | `feat.cashout_declines_24h >= p.cashout_max_declines_24h` | BCRA-A7724 |
| COUT-019 | Cliente sin KYC verificado | AML | HIGH | DECLINE | 90 | active | `txn.customer.kyc_verified == False and txn.amount_ars >= p.new_account_cashout_ars` | UIF-EEFF, UIF-PSP, GAFI-R10 |
| COUT-020 | PEP con egreso relevante | AML | MEDIUM | REVIEW | 50 | active | `txn.customer.is_pep and txn.amount_ars >= p.high_amount_ars` | UIF-PEP, GAFI-R12 |
| COUT-021 | IP compartida por múltiples clientes | FRAUD | MEDIUM | REVIEW | 45 | active | `feat.ip_distinct_subjects_1h >= p.ip_distinct_subjects_1h` | BCRA-A7724 |
