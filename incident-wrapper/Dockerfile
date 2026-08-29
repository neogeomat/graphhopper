# syntax=docker/dockerfile:1

###############################################################################
# Incident / custom-model wrapper — FastAPI sidecar in front of GraphHopper.
# Built from this directory (see docker-compose.yml: build.context ./incident-wrapper)
###############################################################################
FROM python:3.12-slim

LABEL org.opencontainers.image.title="graphhopper-incident-wrapper" \
      org.opencontainers.image.description="FastAPI sidecar: incident CRUD, custom_model routing, Baato key proxy, MapLibre dashboard"

WORKDIR /app

# deps first so a code change doesn't re-resolve them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY static/ static/

# GRAPHOPPER_URL points at the compose service name, not localhost.
# The DB lives on a mounted volume so incidents survive rebuilds.
# BAATO_KEY is injected at runtime (env_file) — never baked into the image.
ENV GRAPHOPPER_URL="http://graphhopper:8989" \
    INCIDENTS_DB="/data/incidents.db" \
    PORT=8000

EXPOSE 8000

# python is guaranteed present here, unlike curl/wget
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# exec keeps uvicorn as PID 1 so SIGTERM shuts it down gracefully
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
