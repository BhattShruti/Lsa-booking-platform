# ── Build stage: install dependencies ────────────────────────────────────────
FROM python:3.10-slim AS deps

WORKDIR /app

# Install system build deps (psycopg2-binary bundles libpq, so no libpq-dev needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies in a separate layer for cache efficiency
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.10-slim AS runtime

# Create a non-root user and group to run the application
RUN groupadd --system appgroup && \
    useradd --system --gid appgroup --home /app --no-create-home appuser

WORKDIR /app

# Copy installed packages from deps stage (keeps runtime image clean)
COPY --from=deps /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=deps /usr/local/bin/gunicorn /usr/local/bin/gunicorn
COPY --from=deps /usr/local/bin/flask    /usr/local/bin/flask
COPY --from=deps /usr/local/bin/alembic  /usr/local/bin/alembic

# Install curl in runtime for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy application source (only what the application needs)
COPY app/           ./app/
COPY migrations/    ./migrations/
COPY gunicorn.conf.py ./
COPY run.py ./
COPY entrypoint.sh ./

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Give ownership to the app user
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Expose application port
EXPOSE 5000

# Docker health check — targets the readiness endpoint so Docker tracks real readiness
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:5000/health/ready || exit 1

# Entrypoint waits for Postgres, runs migrations, then execs gunicorn
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "run:app"]
