# WeatherLens: one service. FastAPI serves the API and the built React app on the same origin.
#   docker build -t weatherlens .
#   docker run -p 8000:8000 -e GEMINI_API_KEY=... -e WEATHER_RISK_DEMO_PASSWORD=... weatherlens

# ---- 1. frontend build ------------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- 2. runtime ---------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
# dependencies first (cached layer), exactly as locked, without dev tools
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
RUN uv sync --frozen --no-dev
COPY config/ config/
COPY data/snapshot/ data/snapshot/
COPY --from=web /web/dist web/dist
# non-root; only the cache folder (SQLite response cache + sessions) is writable
RUN useradd --create-home --uid 10001 app && mkdir -p data/cache && chown app:app data/cache
USER app
# Production defaults; every value can be overridden by the platform's environment settings.
ENV WEATHER_RISK_OFFLINE=true \
    WEATHER_RISK_TRUSTED_PROXY_HOPS=1 \
    WEATHER_RISK_CORS_ORIGINS="" \
    LOG_LEVEL=INFO \
    PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"
# one worker: rate limits, the AI slot and sessions live in this process
CMD ["sh", "-c", "exec uvicorn weather_risk.api.app:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75 --no-server-header"]
