# Benny & 叮當 web edition. Build from the repository root:
#   docker compose -f web/docker-compose.yml up -d --build
# Only the files the web edition needs are copied (see Dockerfile.dockerignore);
# the desktop app is not part of the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/web:/app/apps/backend/src:/app/packages/openmimicry-memory/src \
    BENNY_WEB_DATA=/app/web/data \
    BENNY_WEB_CHARACTERS=/app/characters

WORKDIR /app
COPY web/requirements.txt web/requirements.txt
RUN pip install --no-cache-dir -r web/requirements.txt

# Reused read-only from the desktop code base.
COPY apps/backend/src/openmimicry_backend/__init__.py apps/backend/src/openmimicry_backend/
COPY apps/backend/src/openmimicry_backend/llm_response.py \
     apps/backend/src/openmimicry_backend/bible_search.py \
     apps/backend/src/openmimicry_backend/bible_topics.py \
     apps/backend/src/openmimicry_backend/buddhist_search.py \
     apps/backend/src/openmimicry_backend/novels.py \
     apps/backend/src/openmimicry_backend/
COPY packages/openmimicry-memory/src packages/openmimicry-memory/src
COPY characters/ai_girlfriend characters/ai_girlfriend
COPY characters/dingdong/faces characters/dingdong/faces
COPY web web

RUN useradd --create-home benny && mkdir -p /app/web/data && chown -R benny /app/web/data
USER benny
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
# Only Caddy/cloudflared can reach port 8080 (not published), so trust their
# X-Forwarded-For: the passcode throttle then works per real visitor IP.
CMD ["uvicorn", "benny_web.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
