import requests
from config.settings import ASSETS, COINBASE_PUBLIC_URL, REQUEST_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)


def _fetch_coinbase_prices() -> dict[str, float]:
    prices = {}
    for asset in ASSETS:
        try:
            url = f"{COINBASE_PUBLIC_URL}/prices/{asset}/spot"
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            price = float(data["data"]["amount"])
            prices[asset] = price
            logger.debug(f"Fetched spot price for {asset}: ${price:,.2f}")
        except Exception as e:
            logger.error(f"Failed to fetch spot price for {asset}: {e}")
    return prices


def fetch_prices() -> dict[str, float]:
    """Fetches current prices for all tracked assets (Coinbase + DEX)."""
    prices = {}

    try:
        coinbase_prices = _fetch_coinbase_prices()
        prices.update(coinbase_prices)
    except Exception as e:
        logger.error(f"Coinbase price fetch failed: {e}")

    try:
        from data.dex_fetcher import fetch_all_dex_prices
        dex_prices = fetch_all_dex_prices()
        prices.update(dex_prices)
    except Exception as e:
        logger.error(f"DEX price fetch failed: {e}")

    return prices


def poll_forever(interval_seconds: int = 10) -> None:
    """
    Continuously fetches live prices in a loop and persists them to SQLite.
    Runs until interrupted with Ctrl+C.
    """
    import time
    from data.storage import init_db, upsert_price_snapshot

    logger.info(f"Starting live price polling every {interval_seconds}s... (Ctrl+C to stop)")

    conn = init_db()

    try:
        while True:
            prices = fetch_prices()
            for asset, price in prices.items():
                upsert_price_snapshot(asset, price, conn)
                logger.info(f"  {asset}: ${price:,.8f}")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("Live polling stopped.")
    finally:
        conn.close()
