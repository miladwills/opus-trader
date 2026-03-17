"""
Bybit Control Center - Configuration Module

Contains API credentials, environment settings, and authentication utilities.
"""

import functools
import logging
import os
import json
import secrets
try:
    from flask import request, Response
except ImportError:
    request = None
    Response = None
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
except ImportError:
    ProxyFix = None

# Load .env file if it exists (before any os.getenv calls)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# =============================================================================
# Trading Environment Configuration
# =============================================================================
logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int = 0, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(int(raw), minimum)
    except (TypeError, ValueError):
        return default


# Default environment for new bots (mainnet only)
DEFAULT_TRADING_ENV = os.getenv("DEFAULT_TRADING_ENV", "mainnet").strip().lower()
if DEFAULT_TRADING_ENV != "mainnet":
    DEFAULT_TRADING_ENV = "mainnet"
# Active environment for the global client (falls back to default)
BYBIT_ACTIVE_ENV = os.getenv("BYBIT_ACTIVE_ENV", DEFAULT_TRADING_ENV).strip().lower()

# Legacy single-environment variables (kept for backwards compatibility)
# SECURITY: Defaults removed - credentials MUST come from environment variables
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_BASE_URL = os.getenv("BYBIT_BASE_URL", "")

# Environment-specific credentials
BYBIT_TESTNET_API_KEY = os.getenv("BYBIT_TESTNET_API_KEY", "")
BYBIT_TESTNET_API_SECRET = os.getenv("BYBIT_TESTNET_API_SECRET", "")
BYBIT_TESTNET_BASE_URL = os.getenv("BYBIT_TESTNET_BASE_URL", "https://api-testnet.bybit.com")

BYBIT_MAINNET_API_KEY = os.getenv("BYBIT_MAINNET_API_KEY", "")
BYBIT_MAINNET_API_SECRET = os.getenv("BYBIT_MAINNET_API_SECRET", "")
BYBIT_MAINNET_BASE_URL = os.getenv("BYBIT_MAINNET_BASE_URL", "https://api.bybit.com")

# Environment label for UI display
ENV_LABEL = os.getenv("ENV_LABEL", "Bybit Trading Bot")

# HTTP Basic Auth credentials for dashboard access
BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER", "").strip()
BASIC_AUTH_PASS = os.getenv("BASIC_AUTH_PASS", "").strip()

# =============================================================================
# IP Allowlist Configuration (NEW - Security Hardening)
# =============================================================================
# Optional IP allowlist - comma-separated, empty = allow all
# Example: DASH_ALLOW_IPS="192.168.1.100,10.0.0.5"
_allow_ips_raw = os.getenv("DASH_ALLOW_IPS", "")
DASH_ALLOW_IPS = [ip.strip() for ip in _allow_ips_raw.split(",") if ip.strip()]

# Localhost addresses always bypass IP allowlist
LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}
LOCALHOST_BYPASS_ENABLED = _env_flag("DASH_LOCALHOST_BYPASS", default=False)
TRUSTED_PROXY_HOPS = _env_int("DASH_TRUSTED_PROXY_HOPS", default=0, minimum=0)
FORWARDED_IP_HEADERS = ("X-Forwarded-For", "X-Real-IP", "Forwarded")


def _resolve_credentials(env_name: str) -> dict:
    """
    Resolve credentials for the given environment with backwards-compatible fallbacks.
    """
    if env_name == "mainnet":
        api_key = BYBIT_MAINNET_API_KEY or BYBIT_API_KEY
        api_secret = BYBIT_MAINNET_API_SECRET or BYBIT_API_SECRET
        base_url = BYBIT_MAINNET_BASE_URL or BYBIT_BASE_URL or "https://api.bybit.com"
    else:
        env_name = "testnet"
        api_key = BYBIT_TESTNET_API_KEY or BYBIT_API_KEY
        api_secret = BYBIT_TESTNET_API_SECRET or BYBIT_API_SECRET
        base_url = BYBIT_TESTNET_BASE_URL or BYBIT_BASE_URL or "https://api-testnet.bybit.com"

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "base_url": base_url,
        "trading_env": env_name,
    }


def get_credentials_for_env(trading_env: str) -> dict:
    """
    Retrieve API credentials for mainnet only.

    Args:
        trading_env: "mainnet" only

    Returns:
        Dict containing api_key, api_secret, base_url, trading_env

    Raises:
        ValueError: If credentials are missing or non-mainnet env is requested
    """
    env = (trading_env or DEFAULT_TRADING_ENV).strip().lower()
    if env != "mainnet":
        raise ValueError("Testnet disabled. Mainnet only.")

    creds = _resolve_credentials(env)
    if not creds["api_key"] or not creds["api_secret"]:
        if env == "mainnet":
            raise ValueError(
                "Mainnet credentials not configured. Set BYBIT_MAINNET_API_KEY and BYBIT_MAINNET_API_SECRET. WARNING: MAINNET USES REAL MONEY."
            )
        raise ValueError("Testnet credentials not configured. Set BYBIT_TESTNET_API_KEY and BYBIT_TESTNET_API_SECRET.")

    return creds


def _get_active_env_name() -> str:
    env_to_use = BYBIT_ACTIVE_ENV if BYBIT_ACTIVE_ENV in ("testnet", "mainnet") else DEFAULT_TRADING_ENV
    if env_to_use != "mainnet":
        env_to_use = "mainnet"
    return env_to_use


def load_core_config() -> dict:
    """
    Return the core trading/runtime configuration without dashboard auth requirements.
    """
    env_to_use = _get_active_env_name()
    creds = get_credentials_for_env(env_to_use)

    return {
        # API credentials for the active environment
        "api_key": creds["api_key"],
        "api_secret": creds["api_secret"],
        "base_url": creds["base_url"],

        # UI/Auth-neutral metadata
        "env_label": ENV_LABEL,

        # Environment metadata
        "active_env": creds.get("trading_env", env_to_use),
        "default_trading_env": DEFAULT_TRADING_ENV,
    }


def load_dashboard_config() -> dict:
    """
    Return dashboard configuration and require Basic Auth credentials.
    """
    cfg = load_core_config()

    if not BASIC_AUTH_USER or not BASIC_AUTH_PASS:
        raise ValueError("BASIC_AUTH_USER and BASIC_AUTH_PASS must be set.")

    cfg["basic_auth_user"] = BASIC_AUTH_USER
    cfg["basic_auth_pass"] = BASIC_AUTH_PASS
    return cfg


def load_config(require_dashboard_auth: bool = True) -> dict:
    """
    Backwards-compatible configuration loader.
    """
    if require_dashboard_auth:
        return load_dashboard_config()
    return load_core_config()


def is_localhost_ip(client_ip: str | None) -> bool:
    return str(client_ip or "").strip().lower() in LOCALHOST_IPS


def should_bypass_localhost(
    client_ip: str | None = None,
    req=None,
) -> bool:
    if not LOCALHOST_BYPASS_ENABLED or TRUSTED_PROXY_HOPS > 0:
        return False
    current_request = req or request
    if current_request is not None and any(
        current_request.headers.get(header) for header in FORWARDED_IP_HEADERS
    ):
        return False
    return is_localhost_ip(client_ip or get_request_client_ip(current_request))


def get_request_client_ip(req=None) -> str | None:
    current_request = req or request
    if current_request is None:
        return None
    return getattr(current_request, "remote_addr", None)


def apply_trusted_proxy_fix(app):
    """
    Apply Werkzeug ProxyFix only when explicitly configured.
    """
    if TRUSTED_PROXY_HOPS <= 0 or ProxyFix is None:
        return app
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=TRUSTED_PROXY_HOPS)
    logger.info("Enabled ProxyFix with x_for=%s trusted hop(s)", TRUSTED_PROXY_HOPS)
    return app


def require_basic_auth(view_func):
    """
    Wrap a Flask view function and enforce HTTP Basic Auth using BASIC_AUTH_USER/PASS.
    If auth fails or is missing, return 401 with a WWW-Authenticate header and JSON body:
    { "error": "auth_required" }.
    """
    @functools.wraps(view_func)
    def decorated(*args, **kwargs):
        if not BASIC_AUTH_USER or not BASIC_AUTH_PASS:
            return Response(
                "Dashboard authentication is not configured.",
                status=503,
            )

        if should_bypass_localhost(req=request):
            return view_func(*args, **kwargs)

        auth = request.authorization
        provided_user = getattr(auth, "username", "") or ""
        provided_pass = getattr(auth, "password", "") or ""

        if (
            not auth
            or not secrets.compare_digest(provided_user, BASIC_AUTH_USER)
            or not secrets.compare_digest(provided_pass, BASIC_AUTH_PASS)
        ):
            return Response(
                'Unauthorized: Please login with your dashboard credentials.',
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="OpusTrader Login Verification"'}
            )

        return view_func(*args, **kwargs)

    return decorated
