#!/usr/bin/env bash
# Regenera docs/Resumen_Normativo_Monitoreo_PLA_FT.docx con el mapeo actual de reglas.
# Requiere Node.js (npm install docx) y el paquete del proyecto instalado.
set -euo pipefail
cd "$(dirname "$0")"
python -c "
import json
from monitoreo.service import MonitoringService
m = {}
for r in MonitoringService().ruleset.rules:
    for ref in r.regulatory_refs:
        m.setdefault(ref, []).append({'id': r.id, 'name': r.name, 'mode': r.mode})
json.dump(m, open('rules.json', 'w'), ensure_ascii=False)
"
[ -d node_modules/docx ] || npm install --silent docx
node generar.js ../../docs/Resumen_Normativo_Monitoreo_PLA_FT.docx
