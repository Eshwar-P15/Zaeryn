from datetime import UTC, datetime, timedelta

import pandas as pd
import yfinance as yf

from config.settings import ASSET_CLASS, YFINANCE_MAX_DAYS_1H, YFINANCE_TICKER_MAP
from utils.logger import get_logger

logger = get_logger(__name__)

INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "1d": "1d",
}


def fetch_yfinance_ohlcv(
    symbol: str,
    granularity: str = "1h",
    days_back: int = 365,
) -> pd.DataFrame:
    """
    Fetches OHLCV candles from Yahoo Finance for stocks and forex.

    yfinance quirks handled:
    - Capitalized column names (Open/High/Low/Close/Volume) → normalized to lowercase
    - Multi-level column index (newer yfinance versions) → flattened
    - DatetimeIndex → reset to 'timestamp' column with UTC tz
    - Forex volume=0 is normal — negative volumes clipped, NaN filled to 0
    - 1h data capped at YFINANCE_MAX_DAYS_1H (730) by the API
    """
    ticker = YFINANCE_TICKER_MAP.get(symbol, symbol)
    interval = INTERVAL_MAP.get(granularity, "1h")

    if interval == "1h":
        days_back = min(days_back, YFINANCE_MAX_DAYS_1H)

    end = datetime.now(UTC)
    start = end - timedelta(days=days_back)

    try:
        raw = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=interval,
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        logger.error(f"yfinance download failed for {symbol} ({ticker}): {e}")
        return pd.DataFrame()

    if raw is None or raw.empty:
        logger.warning(f"yfinance returned empty data for {symbol} ({ticker})")
        return pd.DataFrame()

    # Flatten multi-level columns (can appear with newer yfinance on single tickers)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )

    # Reset DatetimeIndex → timestamp column
    raw = raw.reset_index()
    if "Datetime" in raw.columns:
        raw = raw.rename(columns={"Datetime": "timestamp"})
    elif "Date" in raw.columns:
        raw = raw.rename(columns={"Date": "timestamp"})

    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)

    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        logger.error(f"yfinance {symbol}: missing columns {missing} after normalization")
        return pd.DataFrame()

    raw = raw[required].copy()

    # Forex volume is legitimately 0 — clip negatives, fill NaN to 0
    if ASSET_CLASS.get(symbol) == "forex":
        raw["volume"] = raw["volume"].fillna(0.0).clip(lower=0.0)

    # Drop rows with NaN OHLC (yfinance occasionally emits partial rows)
    raw = raw.dropna(subset=["open", "high", "low", "close"])
    raw = raw.sort_values("timestamp").reset_index(drop=True)

    if raw.empty:
        logger.warning(f"yfinance {symbol}: no valid rows after NaN drop")
        return pd.DataFrame()

    logger.info(
        f"yfinance {symbol} ({ticker}): {len(raw)} candles | "
        f"{raw['timestamp'].min().date()} → {raw['timestamp'].max().date()}"
    )
    return raw
