import os
import multiprocessing

# Server socket binding
port = os.environ.get("PORT", "5000")
bind = os.environ.get("GUNICORN_BIND", f"0.0.0.0:{port}")

# Worker processes and concurrency
# Default to 3 workers as a balanced baseline for typical container allocations (1-2 vCPUs)
# Configurable via GUNICORN_WORKERS for high-load or resource-constrained deployments
default_workers = os.environ.get("GUNICORN_WORKERS", "3")
workers = int(default_workers)
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "sync")

# Worker lifecycle & timeouts
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))

# Logging configuration
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)ss'
capture_output = True

# Process naming
proc_name = "habot_lsa_api"
