# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 LOG_FORMAT=json
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY tigerkit.py tigerprod.py ./
COPY scamshield ./scamshield
COPY sql ./sql
COPY static ./static
RUN useradd --system --uid 10001 app && chown -R app /app
USER 10001
EXPOSE 8102
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8102/healthz')"
# Same image runs every process: api (default), `python -m scamshield.simulator --live`, `python -m scamshield.detector --loop 300`
CMD ["uvicorn", "scamshield.api:app", "--host", "0.0.0.0", "--port", "8102", "--proxy-headers", "--forwarded-allow-ips=*"]
