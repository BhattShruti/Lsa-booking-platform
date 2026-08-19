#!/bin/sh
# entrypoint.sh — Waits for PostgreSQL, runs Flask-Migrate, then starts Gunicorn.
#
# Startup sequence:
#   1. Poll PostgreSQL until it accepts connections (bounded retries).
#   2. Run `flask db upgrade` once — idempotent, Alembic tracks applied revisions.
#   3. exec the container CMD (gunicorn) — replaces this shell process.
#
# This script runs once per container start.  It does NOT run inside each
# Gunicorn worker.  Gunicorn's preload_app feature is NOT needed here because
# migrations happen before the master Gunicorn process forks workers.

set -e  # Exit immediately on any error

# ── 1. Wait for PostgreSQL ─────────────────────────────────────────────────────
MAX_RETRIES="${DB_WAIT_RETRIES:-30}"
SLEEP_SEC="${DB_WAIT_SLEEP:-2}"
attempt=0

echo "[entrypoint] Waiting for PostgreSQL to become available..."

until python - <<'PYEOF'
import os, sys, time
try:
    import psycopg2
    from urllib.parse import urlparse
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("[entrypoint] DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)
    # Normalise legacy postgres:// scheme
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    parsed = urlparse(url)
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        dbname=parsed.path.lstrip("/"),
        connect_timeout=3,
    )
    conn.close()
    sys.exit(0)
except Exception as e:
    sys.exit(1)
PYEOF
do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$MAX_RETRIES" ]; then
        echo "[entrypoint] PostgreSQL did not become available after ${MAX_RETRIES} attempts. Exiting."
        exit 1
    fi
    echo "[entrypoint] Attempt ${attempt}/${MAX_RETRIES}: PostgreSQL not ready. Retrying in ${SLEEP_SEC}s..."
    sleep "$SLEEP_SEC"
done

echo "[entrypoint] PostgreSQL is ready."

# ── 2. Run database migrations ─────────────────────────────────────────────────
echo "[entrypoint] Running Flask-Migrate database migrations..."
flask db upgrade
echo "[entrypoint] Migrations complete."

# ── 3. Start the application ───────────────────────────────────────────────────
echo "[entrypoint] Starting application: $*"
exec "$@"
