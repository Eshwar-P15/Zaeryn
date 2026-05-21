# tests/test_birdeye.py
# Run: python -m pytest tests/test_birdeye.py -v -m "not integration"

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def make_items(n: int, start_unix: int = 1700000000) -> list[dict]:
    """Returns items in Birdeye's actual format (o/h/l/c/v short keys)."""
    items = []
    price = 0.05
    for i in range(n):
        price *= 1 + np.random.normal(0, 0.01)
        items.append(
            {
                "unixTime": start_unix + i * 3600,
                "o": round(price * 0.99, 8),
                "h": round(price * 1.01, 8),
                "l": round(price * 0.98, 8),
                "c": round(price, 8),
                "v": round(abs(np.random.normal(1e6, 2e5)), 2),
            }
        )
    return items


# -- _items_to_dataframe -------------------------------------------------------


def test_columns_correct():
    from data.birdeye_fetcher import _items_to_dataframe

    df = _items_to_dataframe(make_items(10))
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_timestamp_is_utc():
    from data.birdeye_fetcher import _items_to_dataframe

    df = _items_to_dataframe(make_items(5))
    assert str(df["timestamp"].dt.tz) == "UTC"


def test_sorted_ascending():
    from data.birdeye_fetcher import _items_to_dataframe

    df = _items_to_dataframe(list(reversed(make_items(20))))
    assert df["timestamp"].is_monotonic_increasing


def test_empty_input():
    from data.birdeye_fetcher import _items_to_dataframe

    df = _items_to_dataframe([])
    assert len(df) == 0
    assert "timestamp" in df.columns


def test_drops_nan_prices():
    from data.birdeye_fetcher import _items_to_dataframe

    items = make_items(5)
    items[2]["c"] = None
    df = _items_to_dataframe(items)
    assert df["close"].isna().sum() == 0


def test_float_dtypes():
    from data.birdeye_fetcher import _items_to_dataframe

    df = _items_to_dataframe(make_items(10))
    for col in ["open", "high", "low", "close", "volume"]:
        assert pd.api.types.is_float_dtype(df[col]), f"{col} not float"


# -- _make_headers -------------------------------------------------------------


def test_raises_without_api_key():
    from data import birdeye_fetcher

    orig = birdeye_fetcher.BIRDEYE_API_KEY
    try:
        birdeye_fetcher.BIRDEYE_API_KEY = ""
        with pytest.raises(RuntimeError, match="BIRDEYE_API_KEY"):
            birdeye_fetcher._make_headers()
    finally:
        birdeye_fetcher.BIRDEYE_API_KEY = orig


def test_headers_contain_required_keys():
    from data import birdeye_fetcher

    orig = birdeye_fetcher.BIRDEYE_API_KEY
    try:
        birdeye_fetcher.BIRDEYE_API_KEY = "test_key_abc"
        h = birdeye_fetcher._make_headers()
        assert h["X-API-KEY"] == "test_key_abc"
        assert h["x-chain"] == "solana"
    finally:
        birdeye_fetcher.BIRDEYE_API_KEY = orig


# -- _fetch_chunk --------------------------------------------------------------


def test_fetch_chunk_404_returns_none():
    from data import birdeye_fetcher

    birdeye_fetcher.BIRDEYE_API_KEY = "key"
    mock = MagicMock()
    mock.status_code = 404
    with patch("data.birdeye_fetcher.requests.get", return_value=mock):
        assert birdeye_fetcher._fetch_chunk("addr", 0, 1) is None


def test_fetch_chunk_401_raises():
    from data import birdeye_fetcher

    birdeye_fetcher.BIRDEYE_API_KEY = "bad"
    mock = MagicMock()
    mock.status_code = 401
    with (
        patch("data.birdeye_fetcher.requests.get", return_value=mock),
        pytest.raises(RuntimeError),
    ):
        birdeye_fetcher._fetch_chunk("addr", 0, 1)


def test_fetch_chunk_200_returns_items():
    from data import birdeye_fetcher

    birdeye_fetcher.BIRDEYE_API_KEY = "key"
    items = make_items(10)
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"success": True, "data": {"items": items}}
    with (
        patch("data.birdeye_fetcher.requests.get", return_value=mock),
        patch("data.birdeye_fetcher.time.sleep"),
    ):
        result = birdeye_fetcher._fetch_chunk("addr", 0, 1)
    assert result == items


# -- fetch_birdeye_ohlcv -------------------------------------------------------


def test_stops_at_launch_date():
    """When API returns < CHUNK_SIZE, pagination stops."""
    from data import birdeye_fetcher

    birdeye_fetcher.BIRDEYE_API_KEY = "key"
    calls = [0]

    def mock_chunk(addr, tf, tt, interval="1H", attempt=0):
        calls[0] += 1
        return make_items(1000 if calls[0] == 1 else 50)

    with (
        patch.object(birdeye_fetcher, "_fetch_chunk", side_effect=mock_chunk),
        patch("data.birdeye_fetcher.time.sleep"),
    ):
        df = birdeye_fetcher.fetch_birdeye_ohlcv("addr", "TEST", days_back=365)

    assert calls[0] == 2
    assert df is not None


def test_no_duplicate_timestamps():
    """Overlapping candles between chunks must be deduplicated."""
    from data import birdeye_fetcher

    birdeye_fetcher.BIRDEYE_API_KEY = "key"
    shared = make_items(50)
    calls = [0]

    def mock_chunk(addr, tf, tt, interval="1H", attempt=0):
        calls[0] += 1
        return shared

    with (
        patch.object(birdeye_fetcher, "_fetch_chunk", side_effect=mock_chunk),
        patch("data.birdeye_fetcher.time.sleep"),
    ):
        df = birdeye_fetcher.fetch_birdeye_ohlcv("addr", "TEST", days_back=7)

    if df is not None:
        assert df["timestamp"].duplicated().sum() == 0


def test_returns_none_when_all_chunks_fail():
    from data import birdeye_fetcher

    birdeye_fetcher.BIRDEYE_API_KEY = "key"
    with (
        patch.object(birdeye_fetcher, "_fetch_chunk", return_value=None),
        patch("data.birdeye_fetcher.time.sleep"),
    ):
        assert birdeye_fetcher.fetch_birdeye_ohlcv("addr", "TEST") is None


def test_output_passes_clean_ohlcv():
    """Output must be compatible with the Phase 1 cleaning pipeline."""
    from data.birdeye_fetcher import _items_to_dataframe
    from data.cleaner import clean_ohlcv

    df = _items_to_dataframe(make_items(200))
    cleaned = clean_ohlcv(df)
    assert not cleaned.empty
    assert "timestamp" in cleaned.columns


# -- Integration ---------------------------------------------------------------


@pytest.mark.integration
def test_bonk_live():
    from config.settings import BIRDEYE_API_KEY, SOLANA_TOKENS
    from data.birdeye_fetcher import fetch_birdeye_ohlcv

    if not BIRDEYE_API_KEY:
        pytest.skip("BIRDEYE_API_KEY not set")
    df = fetch_birdeye_ohlcv(SOLANA_TOKENS["BONK"], "BONK", days_back=30)
    assert df is not None and len(df) > 100
    print(
        f"\nBONK: {len(df)} candles {df['timestamp'].min().date()} → {df['timestamp'].max().date()}"
    )


@pytest.mark.integration
def test_wif_live():
    from config.settings import BIRDEYE_API_KEY, SOLANA_TOKENS
    from data.birdeye_fetcher import fetch_birdeye_ohlcv

    if not BIRDEYE_API_KEY:
        pytest.skip("BIRDEYE_API_KEY not set")
    df = fetch_birdeye_ohlcv(SOLANA_TOKENS["WIF"], "WIF", days_back=30)
    assert df is not None and len(df) > 100
    print(
        f"\nWIF: {len(df)} candles {df['timestamp'].min().date()} → {df['timestamp'].max().date()}"
    )
