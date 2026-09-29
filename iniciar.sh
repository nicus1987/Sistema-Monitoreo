#!/usr/bin/env bash
# ============================================================================
#  Instala y levanta el Sistema de Monitoreo (macOS / Linux).
#  Uso: ./iniciar.sh      (la primera vez tarda unos minutos)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for cand in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[ERROR] Se necesita Python 3.11 o superior."
  echo "  macOS:  brew install python@3.12   (o https://www.python.org/downloads/)"
  echo "  Ubuntu: sudo apt install python3.12 python3.12-venv"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "[1/3] Creando entorno virtual..."
  "$PY" -m venv .venv
fi

echo "[2/3] Instalando dependencias..."
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e ".[dev]"

echo "[3/3] Levantando la API..."
.venv/bin/python -m monitoreo > monitoreo-api.log 2>&1 &
API_PID=$!
trap 'echo; echo "Deteniendo la API..."; kill $API_PID 2>/dev/null || true' EXIT

.venv/bin/python -m monitoreo.simulator --url http://localhost:8000 --wait-only >/dev/null
URL=http://localhost:8000
(command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true

echo
echo "  Dashboard:            $URL"
echo "  Documentación de API: $URL/docs"
echo "  Log de la API:        monitoreo-api.log"
echo
echo "  Enviando tráfico de prueba (normal + escenarios de fraude)..."
.venv/bin/python -m monitoreo.simulator --url "$URL" --rate 5
echo
echo "  La API sigue corriendo. Presioná Ctrl+C para detenerla."
wait $API_PID
