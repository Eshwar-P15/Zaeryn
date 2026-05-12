import numpy as np
import pandas as pd
from utils.logger import get_logger

logger = get_logger(__name__)

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
PRICE_COLUMNS = ["open", "high", "low", "close"]
MAX_CONSECUTIVE_FILL = 3
ANOMALY_THRESHOLD_PCT = 20.0


def validate_ohlcv(df: pd.DataFrame) -> tuple[bool, list[str]]:
    errors = []

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        errors.append(f"Missing columns: {missing_cols}")
        return False, errors

    if df.empty:
        errors.append("DataFrame is empty")
        return False, errors

    for col in PRICE_COLUMNS:
        nan_count = df[col].isna().sum()
        if nan_count > 0:
            errors.append(f"Column '{col}' has {nan_count} NaN values")

    invalid_hl = (df["high"] < df["low"]).sum()
    if invalid_hl > 0:
        errors.append(f"{invalid_hl} rows where high < low (bad data)")

    for col in PRICE_COLUMNS:
        non_positive = (df[col] <= 0).sum()
        if non_positive > 0:
            errors.append(f"Column '{col}' has {non_positive} non-positive values")

    if not df["timestamp"].is_monotonic_increasing:
        errors.append("Timestamps are not monotonically increasing (not sorted)")

    is_valid = len(errors) == 0
    return is_valid, errors


def clean_ohlcv(df: pd.DataFrame, gap_fill: bool = True) -> pd.DataFrame:
    """
    gap_fill=True  (default): forward-fill isolated NaN runs ≤ MAX_CONSECUTIVE_FILL.
    gap_fill=False: skip all NaN filling — use for stocks/forex where overnight/weekend
                    gaps should not be synthetically filled.
    """
    df = df.copy()

    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    df = df.sort_values("timestamp").reset_index(drop=True)

    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    dropped = before - len(df)
    if dropped > 0:
        logger.debug(f"Dropped {dropped} duplicate rows")

    for col in PRICE_COLUMNS + ["volume"]:
        df[col] = df[col].astype(float)

    if gap_fill:
        for col in PRICE_COLUMNS:
            nan_mask = df[col].isna()
            if nan_mask.any():
                nan_groups = nan_mask.ne(nan_mask.shift()).cumsum()
                group_sizes = nan_mask.groupby(nan_groups).transform("sum")

                fillable = nan_mask & (group_sizes <= MAX_CONSECUTIVE_FILL)
                large_gaps = nan_mask & (group_sizes > MAX_CONSECUTIVE_FILL)

                if large_gaps.any():
                    logger.warning(f"Large data gap detected in '{col}' - {large_gaps.sum()} unfilled NaNs")

                df.loc[fillable, col] = df[col].ffill()

    df = df.reset_index(drop=True)
    logger.debug(f"clean_ohlcv: {len(df)} rows after cleaning")
    return df


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    pct_changes = df["close"].pct_change().abs() * 100
    df["is_anomaly"] = pct_changes > ANOMALY_THRESHOLD_PCT

    anomaly_count = df["is_anomaly"].sum()
    if anomaly_count > 0:
        logger.warning(f"Detected {anomaly_count} anomalous candles (>{ANOMALY_THRESHOLD_PCT}% price jump)")
    else:
        logger.debug("No anomalies detected")

    return df


def normalize_price_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["returns"] = df["close"].pct_change() * 100
    df["log_returns"] = np.log(df["close"] / df["close"].shift(1))
    df["price_range"] = (df["high"] - df["low"]) / df["close"]
    df["volume_ma20"] = df["volume"].rolling(window=20, min_periods=1).mean()

    logger.debug("normalize_price_data: added returns, log_returns, price_range, volume_ma20")
    return df
