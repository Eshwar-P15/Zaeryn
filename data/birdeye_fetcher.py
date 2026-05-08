"""
Fetches historical 1h OHLCV candles from Birdeye API for Solana tokens.

Pagination: walks BACKWARDS from now in 1000-candle chunks.
Stops when API returns < BIRDEYE_CHUNK_SIZE items (token launch reached)
or target start date is covered.

Rate limit: 1.1s sleep between every request (free tier: 1 req/sec).

Output schema matches clean_ohlcv() contract:
  timestamp (UTC datetime), open, high, low, close, volume
"""

import time
import requests
import pandas as pd
from datetime import datetime, timezone

from utils.logger import get_logger
from config.settings import (
    BIRDEYE_API_KEY,
    BIRDEYE_BASE_URL,
    BIRDEYE_CHAIN,
    BIRDEYE_CHUNK_SIZE,
    BIRDEYE_RATE_LIMIT_SLEEP,
    BIRDEYE_HISTORY_DAYS,
    SOLANA_TOKENS,
)

logger = get_logger(__name__)

OHLCV_ENDPOINT = f"{BIRDEYE_BASE_URL}/defi/ohlcv"
INTERVAL_MAP   = {"1h": "1H", "1d": "1D", "15m": "15m"}


def _make_headers() -> dict:
    """Returns auth headers. Raises RuntimeError if API key not set."""
    if not BIRDEYE_API_KEY:
        raise RuntimeError(
            "BIRDEYE_API_KEY is not set in .env\n"
            "Get a free key at: https://bds.birdeye.so/auth/sign-up\n"
            "Then add to .env: BIRDEYE_API_KEY=your_key_here"
        )
    return {
        "X-API-KEY": BIRDEYE_API_KEY,
        "x-chain":   BIRDEYE_CHAIN,
        "accept":    "application/json",
    }


def _fetch_chunk(
    mint_address: str,
    time_from:    int,
    time_to:      int,
    interval:     str = "1H",
    attempt:      int = 0,
) -> list[dict] | None:
    """Fetches one time-window chunk from Birdeye. Returns items list or None."""
    try:
        resp = requests.get(
            OHLCV_ENDPOINT,
            headers=_make_headers(),
            params={
                "address":   mint_address,
                "type":      interval,
                "time_from": time_from,
                "time_to":   time_to,
            },
            timeout=15,
        )

        if resp.status_code == 401:
            raise RuntimeError(
                "Birdeye 401 Unauthorized — check BIRDEYE_API_KEY in .env"
            )

        if resp.status_code == 429:
            if attempt == 0:
                logger.warning("Birdeye rate limited — sleeping 60s then retrying")
                time.sleep(60)
                return _fetch_chunk(mint_address, time_from, time_to, interval, attempt=1)
            logger.error("Birdeye rate limited on retry — skipping chunk")
            return None

        if resp.status_code == 404:
            logger.warning(f"Birdeye 404 — address {mint_address[:8]}... not found")
            return None

        if resp.status_code != 200:
            logger.warning(f"Birdeye {resp.status_code}: {resp.text[:200]}")
            return None

        data = resp.json()
        if not data.get("success", True):
            logger.warning(f"Birdeye success=false: {data}")
            return None

        return data.get("data", {}).get("items", [])

    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"Birdeye request error: {e}")
        return None


def _items_to_dataframe(items: list[dict]) -> pd.DataFrame:
    """
    Converts Birdeye items list → ZAERYN-compatible DataFrame.

    Birdeye field: unixTime → timestamp (UTC datetime)
    All price/volume fields kept as float64.
    Output column order matches clean_ohlcv() contract exactly.
    """
    if not items:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(items)
    df = df.rename(columns={
        "unixTime": "timestamp",
        "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
    })
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df


def fetch_birdeye_ohlcv(
    mint_address: str,
    symbol:       str,
    granularity:  str = "1h",
    days_back:    int = BIRDEYE_HISTORY_DAYS,
) -> pd.DataFrame | None:
    """
    Fetches full available OHLCV history for a Solana token.

    Paginates backwards from now in BIRDEYE_CHUNK_SIZE chunks.
    Stops automatically at token launch date (API returns < chunk size).

    Returns DataFrame[timestamp, open, high, low, close, volume] or None.
    """
    interval     = INTERVAL_MAP.get(granularity, "1H")
    now          = int(datetime.now(timezone.utc).timestamp())
    target_start = now - (days_back * 24 * 3600)
    chunk_secs   = BIRDEYE_CHUNK_SIZE * 3600

    logger.info(
        f"[{symbol}] Birdeye fetch — interval={interval} "
        f"days_back={days_back} address={mint_address[:8]}..."
    )

    all_items      = []
    time_to        = now
    chunks_fetched = 0

    while time_to > target_start:
        time_from = max(time_to - chunk_secs, target_start)

        logger.debug(
            f"[{symbol}] chunk {chunks_fetched + 1}: "
            f"{datetime.fromtimestamp(time_from, tz=timezone.utc).strftime('%Y-%m-%d')} → "
            f"{datetime.fromtimestamp(time_to, tz=timezone.utc).strftime('%Y-%m-%d')}"
        )

        items = _fetch_chunk(mint_address, int(time_from), int(time_to), interval)

        time.sleep(BIRDEYE_RATE_LIMIT_SLEEP)

        if items is None:
            logger.warning(f"[{symbol}] chunk failed — stopping pagination")
            break

        all_items.extend(items)
        chunks_fetched += 1

        if len(items) < BIRDEYE_CHUNK_SIZE:
            logger.info(f"[{symbol}] reached launch date after {chunks_fetched} chunks")
            break

        time_to = time_from

    if not all_items:
        logger.error(f"[{symbol}] no candles returned from Birdeye")
        return None

    df = _items_to_dataframe(all_items)
    df = (
        df.drop_duplicates(subset=["timestamp"])
          .sort_values("timestamp")
          .reset_index(drop=True)
    )

    logger.info(
        f"[{symbol}] {len(df):,} candles | "
        f"{df['timestamp'].min().strftime('%Y-%m-%d')} → "
        f"{df['timestamp'].max().strftime('%Y-%m-%d')}"
    )
    return df


def fetch_all_solana_tokens(
    granularity: str = "1h",
    days_back:   int = BIRDEYE_HISTORY_DAYS,
) -> dict[str, pd.DataFrame | None]:
    """Fetches all 5 Solana tokens. Returns {symbol: DataFrame or None}."""
    results = {}
    tokens  = {k: v for k, v in SOLANA_TOKENS.items() if k in ["JUP", "BONK", "WIF", "PYTH", "RAY"]}

    logger.info(f"Fetching {len(tokens)} Solana tokens: {list(tokens.keys())}")

    for symbol, mint in tokens.items():
        logger.info(f"\n{'─'*50}\n{symbol}\n{'─'*50}")
        results[symbol] = fetch_birdeye_ohlcv(mint, symbol, granularity, days_back)

    return results
