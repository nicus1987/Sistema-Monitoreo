@echo off
REM ==========================================================================
REM  Instala y levanta el Sistema de Monitoreo (Windows). Doble clic y listo.
REM  La primera vez tarda unos minutos (descarga dependencias).
REM ==========================================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul

if not exist "pyproject.toml" (
  echo.
  echo [ERROR] No se encuentran los archivos del proyecto.
  echo  Si abriste este archivo desde adentro del ZIP: primero hace clic derecho
  echo  en el ZIP, "Extraer todo...", y ejecuta iniciar_windows.bat desde la carpeta extraida.
  echo.
  pause
  exit /b 1
)

netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul 2>nul && (
  echo.
  echo [ERROR] El puerto 8000 ya esta en uso: probablemente el sistema ya esta corriendo
  echo  en otra ventana. Cerrala ^(o abri http://localhost:8000^) y volve a intentar.
  echo.
  pause
  exit /b 1
)

set "PY="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo [ERROR] No se encontro Python 3.11 o superior.
  echo  1. Descargalo de https://www.python.org/downloads/
  echo  2. Durante la instalacion marca la casilla "Add python.exe to PATH"
  echo  3. Volve a ejecutar este archivo
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creando entorno virtual...
  %PY% -m venv .venv || (echo [ERROR] No se pudo crear el entorno & pause & exit /b 1)
)

echo [2/3] Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -e ".[dev]" || (echo [ERROR] Fallo la instalacion & pause & exit /b 1)

echo [3/3] Levantando la API en una ventana nueva...
start "Monitoreo - API (cerrar para detener)" cmd /k .venv\Scripts\python.exe -m monitoreo

".venv\Scripts\python.exe" -m monitoreo.simulator --url http://localhost:8000 --wait-only
if errorlevel 1 (
  echo.
  echo [ERROR] La API no arranco. Mira el mensaje de error en la ventana
  echo  "Monitoreo - API" y copialo para pedir ayuda.
  echo.
  pause
  exit /b 1
)
start "" http://localhost:8000

echo.
echo  Dashboard abierto en http://localhost:8000
echo  Documentacion de la API en http://localhost:8000/docs
echo.
echo  Enviando trafico de prueba (normal + escenarios de fraude)...
".venv\Scripts\python.exe" -m monitoreo.simulator --url http://localhost:8000 --rate 5
echo.
echo  Listo. La API sigue corriendo en la otra ventana; cerrala para detenerla.
pause
