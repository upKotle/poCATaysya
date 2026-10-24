FROM node:24.22.1-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.10 AS uv
FROM python:3.12.15-slim-bookworm
LABEL org.opencontainers.image.title="Scenic Drive" \
      org.opencontainers.image.licenses="MIT AND ODbL-1.0"
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    OSRM_BASE_URL=https://router.project-osrm.org \
    PATH="/app/backend/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/app ./app
COPY config /app/config
COPY data/moscow /app/data/moscow
COPY --from=frontend /frontend/dist /app/frontend/dist
COPY LICENSE THIRD_PARTY_NOTICES.md /app/
RUN useradd --system --uid 10001 --create-home scenic
USER scenic
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
