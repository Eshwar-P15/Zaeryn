import numpy as np
import pandas as pd
import ta

from utils.logger import get_logger
from config.settings import (
    FEATURE_COLUMNS,
    FEATURE_WINDOWS,
    MODEL_HORIZON,
    MODEL_MIN_ROWS,
    MODEL_HISTORY_DAYS,
    ANNUALIZATION_FACTOR,
)
from data.storage import load_candles, init_db
from data.cleaner import clean_ohlcv, normalize_price_data

logger = get_logger(__name__)


def compute_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds technical indicator columns to an OHLCV DataFrame.

    PRECONDITION: df must already contain columns from normalize_price_data():
        returns, log_returns, price_range, volume_ma20
    These are NOT recomputed here — they are used directly.

    All indicators are backward-looking only (no data leakage).
    NaN rows are NOT dropped here — build_feature_matrix() handles that
    after compute_targets() so we lose exactly the right rows.

    Returns: df copy with additional columns added.
    """
    df = df.copy()
    w  = FEATURE_WINDOWS

    # -- Trend Indicators ------------------------------------------------------

    df["sma_20"] = ta.trend.SMAIndicator(
        close=df["close"], window=w["sma_short"]
    ).sma_indicator()

    df["sma_50"] = ta.trend.SMAIndicator(
        close=df["close"], window=w["sma_long"]
    ).sma_indicator()

    df["ema_12"] = ta.trend.EMAIndicator(
        close=df["close"], window=w["ema_fast"]
    ).ema_indicator()

    df["ema_26"] = ta.trend.EMAIndicator(
        close=df["close"], window=w["ema_slow"]
    ).ema_indicator()

    _macd = ta.trend.MACD(
        close=df["close"],
        window_slow=w["ema_slow"],
        window_fast=w["ema_fast"],
        window_sign=w["macd_signal"],
    )
    df["macd"]        = _macd.macd()
    df["macd_signal"] = _macd.macd_signal()
    df["macd_hist"]   = _macd.macd_diff()

    df["price_vs_sma20"] = np.where(
        df["sma_20"].notna() & (df["sma_20"] > 0),
        (df["close"] - df["sma_20"]) / df["sma_20"],
        np.nan,
    )

    # -- Momentum Indicators ---------------------------------------------------

    df["rsi_14"] = ta.momentum.RSIIndicator(
        close=df["close"], window=w["rsi"]
    ).rsi()

    df["roc_10"] = ta.momentum.ROCIndicator(
        close=df["close"], window=w["roc"]
    ).roc()

    # Williams %R range is [-100, 0] — negative values are correct
    df["williams_r_14"] = ta.momentum.WilliamsRIndicator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        lbp=w["williams_r"],
    ).williams_r()

    # -- Volatility Indicators -------------------------------------------------

    df["atr_14"] = ta.volatility.AverageTrueRange(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=w["atr"],
    ).average_true_range()

    _bb = ta.volatility.BollingerBands(
        close=df["close"],
        window=w["bb"],
        window_dev=2,
    )
    df["bb_upper"]    = _bb.bollinger_hband()
    df["bb_lower"]    = _bb.bollinger_lband()
    df["bb_width"]    = _bb.bollinger_wband()
    df["bb_position"] = _bb.bollinger_pband()

    # Realized volatility — annualized rolling std of log_returns
    # log_returns already exists from normalize_price_data()
    df["realized_vol_20"] = (
        df["log_returns"]
        .rolling(window=w["realized_vol"])
        .std()
        * np.sqrt(ANNUALIZATION_FACTOR)
    )

    # -- Volume Indicators -----------------------------------------------------

    # volume_ratio uses volume_ma20 from normalize_price_data()
    # Guard: zero volume windows in illiquid DEX tokens (Rule 5)
    df["volume_ratio"] = np.where(
        df["volume_ma20"] > 0,
        df["volume"] / df["volume_ma20"],
        1.0,
    )

    # OBV normalized to z-score — raw OBV is not scale-invariant (Rule 8)
    _obv_raw  = ta.volume.OnBalanceVolumeIndicator(
        close=df["close"],
        volume=df["volume"],
    ).on_balance_volume()
    _obv_mean = _obv_raw.rolling(w["obv_norm"]).mean()
    _obv_std  = _obv_raw.rolling(w["obv_norm"]).std()
    df["obv"] = np.where(
        _obv_std > 0,
        (_obv_raw - _obv_mean) / _obv_std,
        0.0,
    )

    # VWAP ratio — close / rolling VWAP (scale-invariant)
    # Guard: zero volume windows (Rule 5)
    _vwap_num  = (df["close"] * df["volume"]).rolling(w["vwap"]).sum()
    _vwap_den  = df["volume"].rolling(w["vwap"]).sum()
    _vwap      = np.where(_vwap_den > 0, _vwap_num / _vwap_den, df["close"])
    df["vwap_ratio"] = np.where(
        _vwap > 0,
        df["close"] / _vwap,
        1.0,
    )

    # -- Time Features ---------------------------------------------------------

    df["hour_of_day"] = df["timestamp"].dt.hour.astype(float)
    df["day_of_week"]  = df["timestamp"].dt.dayofweek.astype(float)
    df["is_weekend"]   = (df["day_of_week"] >= 5).astype(float)

    # -- New Features ----------------------------------------------------------

    # Volatility regime: current vol vs 60-period rolling mean (>1 = elevated)
    df["vol_regime"] = np.where(
        df["realized_vol_20"].rolling(60).mean() > 0,
        df["realized_vol_20"] / df["realized_vol_20"].rolling(60).mean(),
        1.0,
    )

    # ADX-14: trend strength (>25 = strong trend, <20 = choppy)
    df["adx_14"] = ta.trend.ADXIndicator(
        high=df["high"],
        low=df["low"],
        close=df["close"],
        window=14,
    ).adx()

    # Volume trend: 10-period vs 30-period volume MA (>1 = growing participation)
    vol_ma_10 = df["volume"].rolling(10).mean()
    vol_ma_30 = df["volume"].rolling(30).mean()
    df["volume_trend"] = np.where(
        vol_ma_30 > 0,
        vol_ma_10 / vol_ma_30,
        1.0,
    )

    # Price position in 52-week range (0 = yearly low, 1 = yearly high)
    rolling_max_52w = df["close"].rolling(8760, min_periods=100).max()
    rolling_min_52w = df["close"].rolling(8760, min_periods=100).min()
    range_52w = rolling_max_52w - rolling_min_52w
    df["yearly_position"] = np.where(
        range_52w > 0,
        (df["close"] - rolling_min_52w) / range_52w,
        0.5,
    )

    # MACD histogram momentum: acceleration/deceleration of momentum
    df["macd_hist_momentum"] = df["macd_hist"].diff()

    logger.debug(
        f"compute_technical_indicators: {len(df.columns)} total columns, {len(df)} rows"
    )
    return df


def compute_targets(df: pd.DataFrame, horizon: int = MODEL_HORIZON) -> pd.DataFrame:
    """
    Adds forward-looking target columns. Intentionally uses future data.

    Last `horizon` rows will have NaN in target columns — this is correct.
    build_feature_matrix() drops those rows after calling this function.

    Columns added:
        target_volatility:  annualized vol of next horizon candles (regression)
        target_direction:   1.0=UP, 0.0=DOWN, NaN=unknown (classification)
        target_return_pct:  % return over next horizon (diagnostic only)
    """
    df = df.copy()

    # Target volatility: vol of log_returns over the NEXT horizon candles
    # shift(-1) → position t contains log_return[t+1]
    # rolling(horizon) at position t+horizon-1 → std of [t+1 .. t+horizon]
    df["target_volatility"] = (
        df["log_returns"]
        .shift(-1)
        .rolling(window=horizon)
        .std()
        * np.sqrt(ANNUALIZATION_FACTOR)
    )

    # Target direction: 1.0 if price at t+horizon > price at t, else 0.0
    # MUST use np.where — NaN > float silently returns False (Rule 4)
    future_close = df["close"].shift(-horizon)
    df["target_direction"] = np.where(
        future_close.isna(),
        np.nan,
        (future_close > df["close"]).astype(float),
    )

    # Future percentage return (diagnostic only — not used in training)
    df["target_return_pct"] = np.where(
        future_close.isna(),
        np.nan,
        ((future_close - df["close"]) / df["close"] * 100),
    )

    return df


def build_feature_matrix(
    asset: str,
    granularity: str = "1h",
    days_back: int = MODEL_HISTORY_DAYS,
    horizon: int = MODEL_HORIZON,
    conn=None,
) -> tuple | None:
    """
    Full pipeline from DB to clean feature matrix ready for training.

    Returns (X, y_volatility, y_direction) or None if insufficient data.
    Caller MUST check for None before using the result.

    Steps:
        1. load_candles() from SQLite
        2. clean_ohlcv()
        3. normalize_price_data() — adds returns, log_returns, price_range, volume_ma20
        4. compute_technical_indicators() — adds all feature columns
        5. compute_targets() — adds forward-looking targets
        6. Drop NaN rows from required columns
        7. Check minimum row count — return None if insufficient
        8. Return (X, y_vol, y_dir)
    """
    close_conn = False
    if conn is None:
        conn = init_db()
        close_conn = True

    try:
        raw = load_candles(asset, granularity, days_back=days_back, conn=conn)

        if raw.empty:
            logger.warning(
                f"build_feature_matrix [{asset}]: no candles in DB. "
                f"Run scripts/fetch_history.py first."
            )
            return None

        logger.debug(f"[{asset}] loaded {len(raw)} raw candles")

        df = clean_ohlcv(raw)
        df = normalize_price_data(df)
        df = compute_technical_indicators(df)
        df = compute_targets(df, horizon=horizon)

        required = FEATURE_COLUMNS + ["target_volatility", "target_direction"]

        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.error(f"[{asset}] missing columns after pipeline: {missing}")
            return None

        before_drop = len(df)
        df = df.dropna(subset=required).reset_index(drop=True)

        logger.debug(
            f"[{asset}] {len(raw)} raw → {before_drop} after indicators → "
            f"{len(df)} after dropna (dropped {before_drop - len(df)} rows)"
        )

        if len(df) < MODEL_MIN_ROWS:
            logger.warning(
                f"[{asset}] only {len(df)} clean rows after feature engineering "
                f"(minimum: {MODEL_MIN_ROWS}). Skipping. "
                f"Hint: run fetch_history.py with more days."
            )
            return None

        X     = df[FEATURE_COLUMNS].copy()
        y_vol = df["target_volatility"].copy()
        y_dir = df["target_direction"].copy()

        nan_count = X.isna().sum().sum()
        if nan_count > 0:
            bad = X.columns[X.isna().any()].tolist()
            logger.error(f"[{asset}] NaN in feature matrix after dropna: {bad}")
            return None

        logger.info(
            f"[{asset}] feature matrix: {len(X)} rows × {len(FEATURE_COLUMNS)} features | "
            f"target_vol mean={y_vol.mean():.4f} | "
            f"target_dir UP%={y_dir.mean() * 100:.1f}%"
        )
        return X, y_vol, y_dir

    finally:
        if close_conn and conn:
            conn.close()
