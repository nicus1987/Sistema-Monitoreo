"""Catálogo de variables disponibles para escribir reglas, en lenguaje de negocio.

Lo usa la consola para explicar las reglas existentes y para ayudar a construir
reglas nuevas. Un test verifica que toda feature calculada esté documentada acá.
"""

from __future__ import annotations

from typing import Any

A, CI, CO = "ACQUIRING", "CASH_IN", "CASH_OUT"
ALL = [A, CI, CO]
CASH = [CI, CO]

# nombre -> (etiqueta corta, descripción, canales, tipo, unidad)
FEATURES: dict[str, tuple[str, str, list[str], str, str]] = {
    # --- generales
    "hour_local": ("Hora local", "Hora del día (0-23) en Argentina en que se hace la operación.", ALL, "número", "hs"),
    "weekday": ("Día de la semana", "0 = lunes … 6 = domingo.", ALL, "número", ""),
    "is_night": ("Horario nocturno", "La operación ocurre en la franja nocturna definida en el parámetro night_hours.", ALL, "sí/no", ""),
    "is_round_amount": ("Monto redondo", "El monto es múltiplo exacto de round_base_ars y supera round_min_ars.", ALL, "sí/no", ""),
    "is_near_threshold": ("Monto cercano al umbral", "El monto está apenas por debajo del umbral de fraccionamiento (structuring_threshold_ars).", ALL, "sí/no", ""),
    "account_age_days": ("Antigüedad de la cuenta", "Días desde la apertura de la cuenta del cliente.", CASH, "número", "días"),
    "declared_monthly_income_ars": ("Ingreso mensual declarado", "Ingreso mensual declarado por el cliente (perfil KYC).", CASH, "monto", "ARS"),
    "merchant_age_days": ("Antigüedad del comercio", "Días desde la adhesión del comercio.", [A], "número", "días"),
    # --- adquirencia: tarjeta
    "card_count_10m": ("Operaciones de la tarjeta (10 min)", "Operaciones previas de la misma tarjeta en los últimos 10 minutos.", [A], "número", "ops"),
    "card_count_1h": ("Operaciones de la tarjeta (1 h)", "Operaciones previas de la misma tarjeta en la última hora.", [A], "número", "ops"),
    "card_count_24h": ("Operaciones de la tarjeta (24 h)", "Operaciones previas de la misma tarjeta en las últimas 24 horas.", [A], "número", "ops"),
    "card_sum_24h": ("Monto de la tarjeta (24 h)", "Suma aprobada de la tarjeta en 24 h, sin contar esta operación.", [A], "monto", "ARS"),
    "card_sum_24h_incl": ("Monto de la tarjeta (24 h, con esta)", "Suma aprobada de la tarjeta en 24 h incluyendo esta operación.", [A], "monto", "ARS"),
    "card_declines_1h": ("Rechazos de la tarjeta (1 h)", "Intentos rechazados de la tarjeta en la última hora.", [A], "número", "ops"),
    "card_distinct_merchants_1h": ("Comercios distintos (1 h)", "Cantidad de comercios distintos donde se usó la tarjeta en 1 h.", [A], "número", ""),
    "card_distinct_merchants_24h": ("Comercios distintos (24 h)", "Cantidad de comercios distintos donde se usó la tarjeta en 24 h.", [A], "número", ""),
    "card_distinct_countries_24h": ("Países emisores distintos (24 h)", "Países emisores distintos registrados para la tarjeta en 24 h.", [A], "número", ""),
    "card_small_txn_count_1h": ("Micro-operaciones (1 h)", "Operaciones de la tarjeta por montos ≤ card_testing_max_amount_ars en 1 h (testeo de tarjetas).", [A], "número", "ops"),
    "card_same_merchant_count_1h": ("Misma tarjeta y comercio (1 h)", "Operaciones previas de la tarjeta en el mismo comercio en 1 h.", [A], "número", "ops"),
    "card_is_new": ("Tarjeta nunca vista", "Es la primera operación registrada de esta tarjeta.", [A], "sí/no", ""),
    "card_geo_speed_kmh": ("Velocidad de desplazamiento", "Velocidad implícita entre la última operación presencial y esta (viaje imposible).", [A], "número", "km/h"),
    "card_geo_distance_km": ("Distancia a la operación anterior", "Kilómetros entre la última operación presencial y esta.", [A], "número", "km"),
    "card_not_present": ("Tarjeta no presente", "Operación de e-commerce o carga manual (sin tarjeta física).", [A], "sí/no", ""),
    "bin_country_mismatch": ("País emisor ≠ país de la IP", "El país emisor de la tarjeta difiere del país de la conexión.", [A], "sí/no", ""),
    # --- adquirencia: comercio
    "merchant_count_1h": ("Operaciones del comercio (1 h)", "Operaciones del comercio en la última hora.", [A], "número", "ops"),
    "merchant_distinct_cards_1h": ("Tarjetas distintas en el comercio (1 h)", "Cantidad de tarjetas distintas operando en el comercio en 1 h.", [A], "número", ""),
    "merchant_declines_1h": ("Rechazos del comercio (1 h)", "Operaciones rechazadas del comercio en 1 h.", [A], "número", "ops"),
    "merchant_decline_ratio_1h": ("Tasa de rechazo del comercio (1 h)", "Proporción de operaciones rechazadas del comercio en 1 h (0 a 1).", [A], "proporción", ""),
    "merchant_avg_ticket_30d": ("Ticket promedio del comercio (30 d)", "Monto promedio aprobado del comercio en 30 días.", [A], "monto", "ARS"),
    "merchant_ticket_ratio": ("Ticket vs. promedio del comercio", "Cuántas veces el monto supera el ticket promedio del comercio.", [A], "número", "veces"),
    "merchant_history_count_30d": ("Historia del comercio (30 d)", "Operaciones aprobadas del comercio en 30 días.", [A], "número", "ops"),
    "merchant_sum_24h_incl": ("Monto del comercio (24 h, con esta)", "Volumen aprobado del comercio en 24 h incluyendo esta operación.", [A], "monto", "ARS"),
    "merchant_foreign_card_ratio_1h": ("Tarjetas extranjeras en el comercio (1 h)", "Proporción de operaciones con tarjeta extranjera en 1 h (0 a 1).", [A], "proporción", ""),
    # --- cash-in / cash-out
    "cashin_count_1h": ("Ingresos del cliente (cantidad, 1 h)", "Ingresos aprobados del cliente en la última hora.", CASH, "número", "ops"),
    "cashin_sum_1h": ("Ingresos del cliente (monto, 1 h)", "Monto ingresado por el cliente en la última hora.", CASH, "monto", "ARS"),
    "cashin_count_24h": ("Ingresos del cliente (cantidad, 24 h)", "Ingresos aprobados del cliente en 24 h.", CASH, "número", "ops"),
    "cashin_sum_24h": ("Ingresos del cliente (monto, 24 h)", "Monto ingresado por el cliente en 24 h, sin contar esta operación.", CASH, "monto", "ARS"),
    "cashin_count_30d": ("Ingresos del cliente (cantidad, 30 d)", "Ingresos aprobados del cliente en 30 días.", CASH, "número", "ops"),
    "cashin_sum_30d": ("Ingresos del cliente (monto, 30 d)", "Monto ingresado por el cliente en 30 días, sin contar esta operación.", CASH, "monto", "ARS"),
    "cashin_sum_24h_incl": ("Ingresos 24 h (con esta)", "Monto ingresado en 24 h incluyendo esta operación.", [CI], "monto", "ARS"),
    "cashin_sum_30d_incl": ("Ingresos 30 d (con esta)", "Monto ingresado en 30 días incluyendo esta operación.", [CI], "monto", "ARS"),
    "cashin_distinct_senders_24h": ("Originantes distintos (24 h)", "Cuentas distintas que enviaron fondos al cliente en 24 h, incluyendo esta.", [CI], "número", ""),
    "cash_method_sum_30d": ("Efectivo depositado (30 d)", "Monto depositado en efectivo por el cliente en 30 días.", CASH, "monto", "ARS"),
    "cash_method_sum_30d_incl": ("Efectivo depositado 30 d (con esta)", "Efectivo en 30 días incluyendo esta operación.", [CI], "monto", "ARS"),
    "cashout_count_1h": ("Egresos del cliente (cantidad, 1 h)", "Egresos aprobados del cliente en la última hora.", CASH, "número", "ops"),
    "cashout_sum_1h": ("Egresos del cliente (monto, 1 h)", "Monto egresado por el cliente en la última hora.", CASH, "monto", "ARS"),
    "cashout_count_24h": ("Egresos del cliente (cantidad, 24 h)", "Egresos aprobados del cliente en 24 h.", CASH, "número", "ops"),
    "cashout_sum_24h": ("Egresos del cliente (monto, 24 h)", "Monto egresado en 24 h, sin contar esta operación.", CASH, "monto", "ARS"),
    "cashout_count_30d": ("Egresos del cliente (cantidad, 30 d)", "Egresos aprobados del cliente en 30 días.", CASH, "número", "ops"),
    "cashout_sum_30d": ("Egresos del cliente (monto, 30 d)", "Monto egresado en 30 días, sin contar esta operación.", CASH, "monto", "ARS"),
    "cashout_sum_24h_incl": ("Egresos 24 h (con esta)", "Monto egresado en 24 h incluyendo esta operación.", [CO], "monto", "ARS"),
    "cashout_sum_30d_incl": ("Egresos 30 d (con esta)", "Monto egresado en 30 días incluyendo esta operación.", [CO], "monto", "ARS"),
    "cashout_attempts_1h": ("Intentos de egreso (1 h)", "Intentos de egreso (aprobados o rechazados) en la última hora.", [CO], "número", "ops"),
    "cashout_declines_24h": ("Egresos rechazados (24 h)", "Intentos de egreso rechazados en 24 h.", [CO], "número", "ops"),
    "cashout_distinct_beneficiaries_24h": ("Beneficiarios distintos (24 h)", "Cuentas destino distintas en 24 h, incluyendo esta.", [CO], "número", ""),
    "passthrough_ratio_24h": ("Proporción que sale de lo que entró (24 h)", "Egresos 24 h (con esta) ÷ ingresos 24 h. Cerca de 1 = cuenta puente.", [CO], "proporción", ""),
    "minutes_since_last_cashin": ("Minutos desde el último ingreso", "Tiempo transcurrido desde el último ingreso aprobado del cliente.", [CO], "número", "min"),
    "last_cashin_amount": ("Monto del último ingreso", "Monto del último ingreso aprobado del cliente.", [CO], "monto", "ARS"),
    "is_new_beneficiary": ("Beneficiario nuevo", "Es la primera transferencia del cliente a esta cuenta (y no es cuenta propia).", [CO], "sí/no", ""),
    "history_count_90d": ("Historia del cliente (90 d)", "Operaciones aprobadas del mismo tipo (ingreso/egreso) en 90 días.", CASH, "número", "ops"),
    "avg_amount_90d": ("Monto promedio (90 d)", "Monto promedio del cliente para este tipo de operación en 90 días.", CASH, "monto", "ARS"),
    "amount_zscore": ("Desvío del monto (z-score)", "Cuántos desvíos estándar se aleja el monto del promedio del cliente.", CASH, "número", "σ"),
    "amount_to_avg_ratio": ("Monto vs. promedio del cliente", "Cuántas veces el monto supera el promedio histórico del cliente.", CASH, "número", "veces"),
    "profile_usage_ratio_30d": ("Uso del perfil transaccional (30 d)", "Movimiento de 30 días ÷ ingreso mensual declarado. 1,5 = 150% del perfil.", CASH, "número", "veces"),
    "near_threshold_count_7d": ("Operaciones cerca del umbral (7 d)", "Operaciones apenas debajo del umbral de fraccionamiento en 7 días, incluyendo esta.", CASH, "número", "ops"),
    "cpty_distinct_customers_24h": ("Clientes que operaron con la contraparte (24 h)", "Clientes propios distintos que enviaron a / recibieron de esta cuenta en 24 h.", CASH, "número", ""),
    "cpty_sum_24h_incl": ("Monto con la contraparte (24 h)", "Monto total operado con esta contraparte en 24 h, incluyendo esta.", CASH, "monto", "ARS"),
    # --- dispositivo / red
    "device_distinct_subjects_24h": ("Clientes en el dispositivo (24 h)", "Clientes o tarjetas distintas que usaron el mismo dispositivo en 24 h.", ALL, "número", ""),
    "ip_distinct_subjects_1h": ("Clientes en la IP (1 h)", "Clientes o tarjetas distintas que usaron la misma IP en 1 h.", ALL, "número", ""),
    "is_new_device": ("Dispositivo nuevo", "Primera vez que el cliente opera desde este dispositivo.", CASH, "sí/no", ""),
}

# Campos de la transacción (txn.*)
TXN_FIELDS: dict[str, tuple[str, str]] = {
    "txn.amount_ars": ("Monto (ARS)", "Monto de la operación en pesos."),
    "txn.amount": ("Monto original", "Monto en la moneda original."),
    "txn.currency": ("Moneda", "Código ISO de la moneda, ej. 'ARS', 'USD'."),
    "txn.method": ("Medio", "'CARD', 'TRANSFER', 'DEBIN', 'CASH', 'QR', 'WALLET'."),
    "txn.entry_mode": ("Modo de ingreso", "'CHIP', 'CONTACTLESS', 'MAGSTRIPE', 'MANUAL', 'ECOMMERCE', 'QR'."),
    "txn.three_ds_authenticated": ("Autenticado 3DS", "True si la compra no presente pasó autenticación fuerte."),
    "txn.cvv_match": ("CVV correcto", "True/False según validación del código de seguridad."),
    "txn.is_recurring": ("Pago recurrente", "True si es un débito recurrente/suscripción."),
    "txn.customer.risk_level": ("Riesgo del cliente", "'LOW', 'MEDIUM' o 'HIGH' según la matriz de riesgo PLA/FT."),
    "txn.customer.is_pep": ("Cliente PEP", "True si es Persona Expuesta Políticamente."),
    "txn.customer.kyc_verified": ("KYC verificado", "True si la identidad del cliente está validada."),
    "txn.customer.segment": ("Segmento", "'RETAIL', 'PYME', 'CORPORATE', 'MERCHANT'."),
    "txn.customer.cuit": ("CUIT del cliente", "CUIT del titular."),
    "txn.merchant.mcc": ("Rubro del comercio (MCC)", "Código de categoría del comercio, ej. '5411'."),
    "txn.merchant.country": ("País del comercio", "Código ISO, ej. 'AR'."),
    "txn.merchant.merchant_id": ("ID de comercio", "Identificador del comercio."),
    "txn.card.bin": ("BIN", "Primeros 6-8 dígitos de la tarjeta."),
    "txn.card.issuer_country": ("País emisor", "País del banco emisor de la tarjeta."),
    "txn.card.card_type": ("Tipo de tarjeta", "'CREDIT', 'DEBIT', 'PREPAID'."),
    "txn.counterparty.account_id": ("Cuenta contraparte", "CBU/CVU (o su hash) de origen o destino."),
    "txn.counterparty.cuit": ("CUIT contraparte", "CUIT del originante o beneficiario."),
    "txn.counterparty.country": ("País contraparte", "País de la cuenta contraparte."),
    "txn.counterparty.is_own_account": ("Cuenta propia", "True si la contraparte es otra cuenta del mismo cliente."),
    "txn.device.device_id": ("Dispositivo", "Identificador del dispositivo."),
    "txn.device.ip_country": ("País de la IP", "País de la conexión."),
    "txn.device.is_emulator": ("Emulador", "True si el dispositivo es un emulador."),
    "txn.device.is_rooted": ("Dispositivo rooteado", "True si el dispositivo tiene root/jailbreak."),
    "txn.device.session_age_seconds": ("Antigüedad de la sesión", "Segundos desde el inicio de sesión."),
}

FUNCTIONS: dict[str, str] = {
    "in_list('lista', valor)": "Verdadero si el valor está en la lista de control indicada (sanciones, mulas, etc.).",
    "prefix_in_list('lista', valor)": "Verdadero si el valor empieza con algún elemento de la lista (útil para BINs).",
    "between(x, desde, hasta)": "Verdadero si x está entre los dos valores (inclusive).",
    "coalesce(a, b, ...)": "Devuelve el primer valor que no esté vacío.",
    "min(a, b) / max(a, b)": "Mínimo / máximo.",
    "abs(x) / round(x)": "Valor absoluto / redondeo.",
}

OPERATORS: dict[str, str] = {
    "and / or / not": "y / o / no",
    ">= <= > < == !=": "mayor o igual, menor o igual, mayor, menor, igual, distinto",
    "in ['A', 'B']": "está entre los valores indicados",
    "+ - * /": "operaciones aritméticas (ej. p.high_amount_ars / 2)",
}

# Parámetros que intervienen en el cálculo de features (no sólo en reglas):
# cambiarlos no se refleja exactamente en la vista previa sobre tráfico ya evaluado.
FEATURE_PARAMS = {
    "timezone", "night_hours", "round_base_ars", "round_min_ars", "structuring_threshold_ars",
    "structuring_band_pct", "card_testing_max_amount_ars",
}


def catalog() -> dict[str, Any]:
    return {
        "features": [
            {"name": f"feat.{k}", "label": v[0], "description": v[1], "channels": v[2], "type": v[3], "unit": v[4]}
            for k, v in FEATURES.items()
        ],
        "transaction_fields": [{"name": k, "label": v[0], "description": v[1]} for k, v in TXN_FIELDS.items()],
        "functions": [{"syntax": k, "description": v} for k, v in FUNCTIONS.items()],
        "operators": [{"syntax": k, "description": v} for k, v in OPERATORS.items()],
    }
