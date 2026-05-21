import time
from datetime import timedelta

import pandas as pd
import requests

from config.settings import (
    CANDLE_REQUEST_SLEEP,
    GECKO_AGGREGATES,
    GECKO_GRANULARITIES,
    GECKO_MAX_CANDLES_PER_REQUEST,
    GECKOTERMINAL_BASE_URL,
    GECKOTERMINAL_NETWORK,
    REQUEST_RETRY_ATTEMPTS,
    REQUEST_RETRY_DELAYS,
    REQUEST_TIMEOUT,
    SOLANA_TOKENS,
)
from utils.logger import get_logger
from utils.time_utils import from_unix, now_utc, to_unix

logger = get_logger(__name__)


def _get(url: str, params: dict = None) -> dict:
    last_error = None
    for attempt in range(REQUEST_RETRY_ATTEMPTS):
        if attempt > 0:
            wait = REQUEST_RETRY_DELAYS[attempt - 1]
            logger.debug(f"Retry {attempt} for GeckoTerminal, waiting {wait}s")
            time.sleep(wait)
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            last_error = e
            logger.warning(f"GeckoTerminal request failed (attempt {attempt + 1}): {e}")
    raise RuntimeError(f"All retries exhausted. Last error: {last_error}")


def _parse_ohlcv_response(data: dict) -> pd.DataFrame:
    try:
        ohlcv_list = data["data"]["attributes"]["ohlcv_list"]
    except (KeyError, TypeError):
        logger.warning("GeckoTerminal response missing ohlcv_list")
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    if not ohlcv_list:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(ohlcv_list, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = df["timestamp"].apply(from_unix)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

    return df


def _fetch_chunk(
    pool_address: str,
    timeframe: str,
    aggregate: int,
    before_timestamp: int,
    limit: int = 1000,
) -> pd.DataFrame:
    url = (
        f"{GECKOTERMINAL_BASE_URL}/networks/{GECKOTERMINAL_NETWORK}"
        f"/pools/{pool_address}/ohlcv/{timeframe}"
    )
    params = {
        "aggregate": aggregate,
        "before_timestamp": before_timestamp,
        "limit": min(limit, GECKO_MAX_CANDLES_PER_REQUEST),
        "currency": "usd",
        "token": "base",
    }

    data = _get(url, params=params)
    df = _parse_ohlcv_response(data)

    if not df.empty:
        df = df.sort_values("timestamp").reset_index(drop=True)

    return df


def fetch_dex_candles(
    symbol: str,
    granularity: str = "1h",
    days_back: int = 30,
) -> pd.DataFrame:
    if symbol not in SOLANA_TOKENS:
        raise ValueError(
            f"Unknown symbol '{symbol}'. Add it to SOLANA_TOKENS in config/settings.py"
        )

    if granularity not in GECKO_GRANULARITIES:
        raise ValueError(
            f"Invalid granularity '{granularity}'. Choose from: {list(GECKO_GRANULARITIES.keys())}"
        )

    from data.dex_fetcher import get_pair_address

    pool_address = get_pair_address(symbol)

    if not pool_address:
        logger.error(f"No qualifying pool found for {symbol} - cannot fetch OHLCV")
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    timeframe = GECKO_GRANULARITIES[granularity]
    aggregate = GECKO_AGGREGATES[granularity]

    granularity_hours = {"1m": 1 / 60, "5m": 5 / 60, "15m": 15 / 60, "1h": 1, "4h": 4, "1d": 24}
    hours_per_candle = granularity_hours.get(granularity, 1)
    total_candles_needed = int((days_back * 24) / hours_per_candle)

    logger.info(
        f"Fetching {days_back}d of {granularity} candles for {symbol} "
        f"(~{total_candles_needed} candles, pool: {pool_address[:8]}...)"
    )

    all_chunks = []
    before_ts = to_unix(now_utc())
    fetched_total = 0

    while fetched_total < total_candles_needed:
        remaining = total_candles_needed - fetched_total
        limit = min(remaining, GECKO_MAX_CANDLES_PER_REQUEST)

        try:
            chunk = _fetch_chunk(pool_address, timeframe, aggregate, before_ts, limit)
        except RuntimeError as e:
            logger.error(f"GeckoTerminal chunk failed for {symbol}: {e}")
            break

        if chunk.empty:
            logger.debug(f"Empty chunk for {symbol} - no more historical data available")
            break

        all_chunks.append(chunk)
        fetched_total += len(chunk)

        oldest_ts = to_unix(chunk["timestamp"].iloc[0])
        before_ts = oldest_ts - 1

        logger.debug(f"  {symbol}: fetched {fetched_total}/{total_candles_needed} candles so far")

        cutoff = now_utc() - timedelta(days=days_back)
        if chunk["timestamp"].iloc[0] <= cutoff:
            break

        time.sleep(CANDLE_REQUEST_SLEEP)

    if not all_chunks:
        logger.warning(f"No candle data retrieved for {symbol}")
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    combined = pd.concat(all_chunks, ignore_index=True)
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    combined = combined.drop_duplicates(subset="timestamp").reset_index(drop=True)

    cutoff = now_utc() - timedelta(days=days_back)
    combined = combined[combined["timestamp"] >= cutoff].reset_index(drop=True)

    logger.info(f"OK {symbol}: {len(combined)} candles fetched ({granularity}, {days_back}d)")
    return combined


def fetch_all_dex_candles(
    granularity: str = "1h",
    days_back: int = 30,
) -> dict[str, pd.DataFrame]:
    results = {}

    for symbol in SOLANA_TOKENS:
        try:
            df = fetch_dex_candles(symbol, granularity=granularity, days_back=days_back)
            if not df.empty:
                results[symbol] = df
            else:
                logger.warning(f"Empty OHLCV result for {symbol}")
        except Exception as e:
            logger.error(f"Failed to fetch OHLCV for {symbol}: {e}")

    logger.info(f"fetch_all_dex_candles: {len(results)}/{len(SOLANA_TOKENS)} tokens retrieved")
    return results
