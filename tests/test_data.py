import pytest
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from data.cleaner import validate_ohlcv, clean_ohlcv, detect_anomalies, normalize_price_data
from data.storage import init_db, upsert_candles, load_candles, upsert_price_snapshot, load_price_snapshots
from utils.time_utils import now_utc, to_unix, from_unix, chunk_date_range, date_range
from utils.math_utils import pct_change, rolling_mean, rolling_std, normalize_minmax, clamp


def make_sample_ohlcv(n: int = 50) -> pd.DataFrame:
    end = pd.Timestamp.now(tz="UTC").floor("h")
    start = end - pd.Timedelta(hours=n - 1)
    timestamps = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    closes = 40000.0 + np.cumsum(np.random.randn(n) * 100)
    closes = np.maximum(closes, 1000)

    return pd.DataFrame({
        "timestamp": timestamps,
        "open":   closes * 0.999,
        "high":   closes * 1.005,
        "low":    closes * 0.995,
        "close":  closes,
        "volume": np.random.uniform(100, 1000, n),
    })


@pytest.fixture
def sample_df():
    return make_sample_ohlcv(50)


@pytest.fixture
def mem_conn():
    conn = init_db(":memory:")
    yield conn
    conn.close()


# --- utils/math_utils tests ---

def test_pct_change_basic():
    assert pct_change(100, 110) == pytest.approx(10.0)
    assert pct_change(100, 90) == pytest.approx(-10.0)

def test_pct_change_zero_old():
    assert pct_change(0, 50) == 0.0

def test_rolling_mean_basic():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = rolling_mean(vals, window=3)
    assert result[0] != result[0]  # NaN
    assert result[1] != result[1]  # NaN
    assert result[2] == pytest.approx(2.0)
    assert result[4] == pytest.approx(4.0)

def test_normalize_minmax():
    vals = [0.0, 5.0, 10.0]
    result = normalize_minmax(vals)
    assert result[0] == pytest.approx(0.0)
    assert result[1] == pytest.approx(0.5)
    assert result[2] == pytest.approx(1.0)

def test_clamp():
    assert clamp(5.0, 0.0, 10.0) == 5.0
    assert clamp(-5.0, 0.0, 10.0) == 0.0
    assert clamp(15.0, 0.0, 10.0) == 10.0


# --- utils/time_utils tests ---

def test_unix_roundtrip():
    dt = now_utc().replace(microsecond=0)
    ts = to_unix(dt)
    recovered = from_unix(ts)
    assert dt == recovered

def test_chunk_date_range_covers_full_range():
    from datetime import timedelta
    start, end = date_range(30)
    chunks = chunk_date_range(start, end, "1h")
    assert chunks[0][0] == start
    assert chunks[-1][1] == end
    for i in range(len(chunks) - 1):
        assert chunks[i][1] == chunks[i + 1][0]


# --- data/cleaner tests ---

def test_validate_ohlcv_valid(sample_df):
    is_valid, errors = validate_ohlcv(sample_df)
    assert is_valid, f"Expected valid but got errors: {errors}"

def test_validate_ohlcv_missing_column(sample_df):
    broken = sample_df.drop(columns=["volume"])
    is_valid, errors = validate_ohlcv(broken)
    assert not is_valid
    assert any("volume" in e for e in errors)

def test_validate_ohlcv_negative_price(sample_df):
    broken = sample_df.copy()
    broken.loc[5, "close"] = -100.0
    is_valid, errors = validate_ohlcv(broken)
    assert not is_valid

def test_validate_ohlcv_high_less_than_low(sample_df):
    broken = sample_df.copy()
    broken.loc[3, "high"] = broken.loc[3, "low"] - 1.0
    is_valid, errors = validate_ohlcv(broken)
    assert not is_valid

def test_clean_ohlcv_drops_duplicates(sample_df):
    duped = pd.concat([sample_df, sample_df.iloc[:5]], ignore_index=True)
    cleaned = clean_ohlcv(duped)
    assert len(cleaned) == len(sample_df)

def test_clean_ohlcv_sorts_timestamps():
    df = make_sample_ohlcv(10)
    shuffled = df.sample(frac=1).reset_index(drop=True)
    cleaned = clean_ohlcv(shuffled)
    assert cleaned["timestamp"].is_monotonic_increasing

def test_detect_anomalies_flags_spike(sample_df):
    df = sample_df.copy()
    df.loc[10, "close"] = df.loc[9, "close"] * 1.30
    result = detect_anomalies(df)
    assert result.loc[10, "is_anomaly"] == True

def test_detect_anomalies_normal_data(sample_df):
    result = detect_anomalies(sample_df)
    assert result["is_anomaly"].sum() == 0

def test_normalize_price_data_columns(sample_df):
    result = normalize_price_data(sample_df)
    for col in ["returns", "log_returns", "price_range", "volume_ma20"]:
        assert col in result.columns, f"Missing column: {col}"


# --- data/storage tests ---

def test_upsert_and_load_candles(sample_df, mem_conn):
    written = upsert_candles("BTC-USD", "1h", sample_df, mem_conn)
    assert written == len(sample_df)

    loaded = load_candles("BTC-USD", "1h", days_back=365, conn=mem_conn)
    assert len(loaded) == len(sample_df)
    assert list(loaded.columns[:6]) == ["timestamp", "open", "high", "low", "close", "volume"]

def test_upsert_candles_no_duplicates(sample_df, mem_conn):
    upsert_candles("BTC-USD", "1h", sample_df, mem_conn)
    upsert_candles("BTC-USD", "1h", sample_df, mem_conn)

    loaded = load_candles("BTC-USD", "1h", days_back=365, conn=mem_conn)
    assert len(loaded) == len(sample_df)

def test_price_snapshots(mem_conn):
    upsert_price_snapshot("BTC-USD", 45000.0, mem_conn)
    upsert_price_snapshot("ETH-USD", 2500.0, mem_conn)

    snapshots = load_price_snapshots(mem_conn)
    assert snapshots["BTC-USD"] == 45000.0
    assert snapshots["ETH-USD"] == 2500.0

def test_upsert_updates_existing_snapshot(mem_conn):
    upsert_price_snapshot("BTC-USD", 40000.0, mem_conn)
    upsert_price_snapshot("BTC-USD", 50000.0, mem_conn)

    snapshots = load_price_snapshots(mem_conn)
    assert snapshots["BTC-USD"] == 50000.0


# --- Integration test (hits live Coinbase API) ---

@pytest.mark.integration
def test_fetch_candles_live():
    from data.historical import fetch_candles
    df = fetch_candles("BTC-USD", granularity="1h", days_back=2)

    assert not df.empty, "Expected candle data from live API"
    assert "close" in df.columns
    assert len(df) > 0
    assert (df["close"] > 0).all()

    is_valid, errors = validate_ohlcv(df)
    assert is_valid, f"Live data failed validation: {errors}"
