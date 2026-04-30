import time
import requests
import pandas as pd
from datetime import datetime

from config.settings import (
    COINBASE_EXCHANGE_URL,
    GRANULARITIES,
    DEFAULT_GRANULARITY,
    HISTORY_DAYS,
    ASSET_SOURCE,
    ALL_ASSETS,
    REQUEST_TIMEOUT,
    REQUEST_RETRY_ATTEMPTS,
    REQUEST_RETRY_DELAYS,
    CANDLE_REQUEST_SLEEP,
)
from utils.logger import get_logger
from utils.time_utils import date_range, chunk_date_range, to_iso, from_unix

logger = get_logger(__name__)


def _fetch_chunk(
    product_id: str,
    start: datetime,
    end: datetime,
    granularity_seconds: int,
) -> pd.DataFrame:
    url = f"{COINBASE_EXCHANGE_URL}/products/{product_id}/candles"
    params = {
        "start": to_iso(start),
        "end": to_iso(end),
        "granularity": granularity_seconds,
    }

    last_exception = None
    for attempt in range(REQUEST_RETRY_ATTEMPTS):
        if attempt > 0:
            wait = REQUEST_RETRY_DELAYS[attempt - 1]
            logger.debug(f"Retry {attempt}/{REQUEST_RETRY_ATTEMPTS-1} for {product_id} chunk, waiting {wait}s")
            time.sleep(wait)

        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            raw = response.json()

            if not raw:
                logger.debug(f"Empty candle response for {product_id} chunk {to_iso(start)} -> {to_iso(end)}")
                return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

            # Coinbase format: [unix_timestamp, low, high, open, close, volume]
            df = pd.DataFrame(raw, columns=["timestamp", "low", "high", "open", "close", "volume"])
            df["timestamp"] = df["timestamp"].apply(from_unix)
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]

            logger.debug(f"Fetched {len(df)} candles for {product_id} [{to_iso(start)} -> {to_iso(end)}]")
            return df

        except requests.exceptions.RequestException as e:
            last_exception = e
            logger.warning(f"Request failed for {product_id} (attempt {attempt + 1}): {e}")

    raise RuntimeError(
        f"All {REQUEST_RETRY_ATTEMPTS} attempts failed for {product_id}. Last error: {last_exception}"
    )


def _fetch_from_coinbase(
    product_id: str,
    granularity: str,
    days_back: int,
) -> pd.DataFrame:
    if granularity not in GRANULARITIES:
        raise ValueError(f"Invalid granularity '{granularity}'. Choose from: {list(GRANULARITIES.keys())}")

    granularity_seconds = GRANULARITIES[granularity]
    start, end = date_range(days_back)
    chunks = chunk_date_range(start, end, granularity)

    logger.info(f"Fetching {days_back}d of {granularity} candles for {product_id} in {len(chunks)} chunks...")

    all_chunks = []
    for i, (chunk_start, chunk_end) in enumerate(chunks):
        try:
            chunk_df = _fetch_chunk(product_id, chunk_start, chunk_end, granularity_seconds)
            if not chunk_df.empty:
                all_chunks.append(chunk_df)
        except RuntimeError as e:
            logger.error(f"Failed chunk {i+1}/{len(chunks)} for {product_id}: {e}")

        if i < len(chunks) - 1:
            time.sleep(CANDLE_REQUEST_SLEEP)

    if not all_chunks:
        logger.warning(f"No candle data retrieved for {product_id}")
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    combined = pd.concat(all_chunks, ignore_index=True)
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    combined = combined.drop_duplicates(subset="timestamp").reset_index(drop=True)

    logger.info(f"OK {product_id}: {len(combined)} candles fetched ({granularity}, {days_back}d)")
    return combined


def _fetch_from_dex(
    symbol: str,
    granularity: str,
    days_back: int,
) -> pd.DataFrame:
    from data.gecko_fetcher import fetch_dex_candles
    return fetch_dex_candles(symbol, granularity=granularity, days_back=days_back)


def fetch_candles(
    symbol: str,
    granularity: str = DEFAULT_GRANULARITY,
    days_back: int = 30,
) -> pd.DataFrame:
    """
    Universal candle fetcher - routes to correct data source based on ASSET_SOURCE config.

    Coinbase assets (BTC-USD etc.) -> Coinbase Exchange API
    Solana DEX tokens (JUP etc.)   -> GeckoTerminal via DexScreener
    """
    source = ASSET_SOURCE.get(symbol, "coinbase")

    if source == "coinbase":
        return _fetch_from_coinbase(symbol, granularity, days_back)
    elif source == "dex":
        return _fetch_from_dex(symbol, granularity, days_back)
    else:
        raise ValueError(f"Unknown data source '{source}' for symbol '{symbol}'")


def fetch_all_assets(
    granularity: str = DEFAULT_GRANULARITY,
    days_back: int = 30,
    sources: list[str] = None,
) -> dict[str, pd.DataFrame]:
    """
    Fetches candles for all tracked assets across all sources.

    Args:
        sources: Optional filter e.g. ["coinbase"] or ["dex"].
                 Default (None) fetches everything in ALL_ASSETS.
    """
    results = {}
    assets_to_fetch = ALL_ASSETS

    if sources:
        assets_to_fetch = [a for a in ALL_ASSETS if ASSET_SOURCE.get(a) in sources]

    for symbol in assets_to_fetch:
        try:
            df = fetch_candles(symbol, granularity=granularity, days_back=days_back)
            if not df.empty:
                results[symbol] = df
            else:
                logger.warning(f"Empty result for {symbol} - skipping")
        except Exception as e:
            logger.error(f"Failed to fetch {symbol}: {e}")

    logger.info(f"fetch_all_assets: {len(results)}/{len(assets_to_fetch)} assets retrieved")
    return results
