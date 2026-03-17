"""Gunicorn configuration for Opus Trader dashboard."""

import os

# Bind to the same host/port as before
bind = f"{os.environ.get('APP_HOST', '0.0.0.0')}:{os.environ.get('APP_PORT', '8000')}"

# 2 workers × 4 threads = 8 concurrent requests.
# Fewer workers means better per-worker cache hit rates while still
# allowing parallel request handling (one slow endpoint won't block all).
workers = 4

# Use gthread worker for compatibility with Flask's threading model
# and to allow SSE streaming responses.
worker_class = "gthread"
threads = 8

# Timeout: some endpoints (bot-triage) take up to 15s
timeout = 30

# Graceful restart timeout
graceful_timeout = 10

# Do NOT preload — let each worker initialize its own runtime
# (file locks, threads, caches can't survive fork)
preload_app = False

# Keep-alive for persistent connections (SSE)
keepalive = 65

# Access log off (runner.log already captures everything)
accesslog = None
errorlog = "-"
loglevel = "warning"

# Limit request sizes
limit_request_line = 8190
limit_request_fields = 100


def on_starting(server):
    """Called just before the master process is initialized."""
    os.makedirs("storage", exist_ok=True)


def post_fork(server, worker):
    """Called just after a worker has been forked — initialize app runtime."""
    from app import initialize_app_runtime
    initialize_app_runtime()
