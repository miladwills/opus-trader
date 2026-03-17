"""
Bybit Control Center - Client Factory

Factory for creating Bybit clients (mainnet only).
"""

import logging
from typing import Optional
from services.bybit_client import BybitClient
from config.config import get_credentials_for_env

logger = logging.getLogger(__name__)
_mainnet_client_log_emitted = False


def create_bybit_client(trading_env: str = "mainnet", paper_trading: bool = False) -> BybitClient:
    """
    Create a Bybit client for mainnet only.

    Args:
        trading_env: Trading environment ("mainnet" only)
        paper_trading: Disabled (must be False)

    Returns:
        Initialized BybitClient instance

    Raises:
        ValueError: If credentials are missing or a non-mainnet env is requested
    """
    env = (trading_env or "mainnet").strip().lower()
    if env != "mainnet":
        raise ValueError("Testnet disabled. Mainnet only.")
    if paper_trading:
        raise ValueError("paper_trading disabled. Mainnet only.")

    # Get credentials for the specified environment
    creds = get_credentials_for_env(env)

    # Create client
    client = BybitClient(
        api_key=creds["api_key"],
        api_secret=creds["api_secret"],
        base_url=creds["base_url"],
    )

    # Log environment selection (without exposing keys), but avoid warning spam.
    global _mainnet_client_log_emitted
    if trading_env == "mainnet":
        if not _mainnet_client_log_emitted:
            logger.info(
                "Created Bybit client for MAINNET - paper_trading=%s",
                paper_trading,
            )
            _mainnet_client_log_emitted = True
        else:
            logger.debug(
                "Reusing MAINNET client context - paper_trading=%s",
                paper_trading,
            )
    else:
        logger.info(
            "Created Bybit client for TESTNET (safe) - paper_trading=%s",
            paper_trading,
        )

    return client


def get_client_for_bot(bot: dict, default_env: str = "mainnet") -> BybitClient:
    """
    Get a Bybit client configured for a specific bot's environment (mainnet only).

    Args:
        bot: Bot dictionary containing trading_env and paper_trading settings
        default_env: Default environment if bot doesn't specify one

    Returns:
        Initialized BybitClient instance for the bot's environment

    Raises:
        ValueError: If credentials are missing or a non-mainnet env is requested
    """
    trading_env = bot.get("trading_env", default_env) or default_env
    paper_trading = bot.get("paper_trading", False)

    return create_bybit_client(trading_env=trading_env, paper_trading=paper_trading)
