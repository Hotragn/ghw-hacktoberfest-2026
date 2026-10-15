# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 LOG_FORMAT=json
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY tigerkit.py tigerprod.py ./
COPY witness ./witness
COPY sql ./sql
COPY static ./static
RUN useradd --system --uid 10001 app && chown -R app /app
USER 10001
EXPOSE 8103
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8103/healthz')"
# migrations are a separate one-shot job (docker compose run migrate / CI step), never on app boot
CMD ["uvicorn", "witness.api:app", "--host", "0.0.0.0", "--port", "8103", "--proxy-headers", "--forwarded-allow-ips=*"]
