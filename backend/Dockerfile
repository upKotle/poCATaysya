FROM ghcr.io/astral-sh/uv:0.12.10 AS uv
FROM python:3.12.15-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
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
RUN useradd --system --uid 10001 --create-home scenic
USER scenic
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
