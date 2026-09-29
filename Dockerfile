FROM python:3.11-slim
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir ".[kafka]"
ENV MONITOREO_CONFIG_DIR=/app/config \
    MONITOREO_AUDIT_PATH=/data/audit/decisions.jsonl \
    PORT=8000
# config/ debe ser escribible: la consola edita reglas y parámetros
RUN mkdir -p /data/audit && chown -R app /data /app/config
USER app
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')"
CMD ["python", "-m", "monitoreo"]
