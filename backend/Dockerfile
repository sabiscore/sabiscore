# Development stage
FROM python:3.11-slim AS development

# Survive slow/flaky PyPI links: default 15s read-timeout aborts large
# scientific wheels (xgboost/lightgbm) on constrained connections.
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5

WORKDIR /app

# Install system dependencies.
# apt over HTTPS: plain-HTTP mirrors get hijacked by carrier captive portals
# (observed: Airtel NG zerod portal returning 400 for deb.debian.org).
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y \
    gcc \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
# Prefer a minimal requirements file for faster builds in CI/deploy. You can override by
# providing a different filename via build ARG (e.g. --build-arg REQUIREMENTS=requirements.txt)
ARG REQUIREMENTS=requirements.min.txt
COPY ${REQUIREMENTS} ./
COPY requirements.txt ./requirements.txt
# Cache mount: downloaded wheels survive failed builds (flaky-network resilience)
# without ever entering the image layer.
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ -f "${REQUIREMENTS}" ]; then pip install -r ${REQUIREMENTS}; else pip install -r requirements.txt; fi

# Copy source code
COPY src/ ./src/

# Expose port
EXPOSE 8000

# Run the application with auto-reload
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Production stage - updated with libgomp
FROM python:3.11-slim AS production

# PIP_NO_CACHE_DIR intentionally absent: pip's cache lives in a BuildKit cache
# mount (never in the image), and must persist across builds so a corrupted
# download on a flaky connection doesn't restart the full 2GB+ fetch.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5 \
    PORT=8000

WORKDIR /app

# Install runtime dependencies (apt over HTTPS — see development stage note)
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y \
    postgresql-client \
    redis-tools \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy only application source. Referencing the development stage made a
# production build install the minimal dependencies before installing the full
# production requirements below, duplicating network and disk work.
COPY src/ ./src/

# Install Python dependencies in production
COPY requirements.runtime.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.runtime.txt

# Create directories for volume mounts
RUN mkdir -p /app/models /app/data

# Non-root user for production security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=3s \
  CMD curl -f http://localhost:$PORT/health || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning", "--workers", "1", "--limit-max-requests", "500", "--timeout-keep-alive", "30"]
