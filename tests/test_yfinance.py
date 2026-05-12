# tests/test_yfinance.py
# Run: python -m pytest tests/test_yfinance.py -v -m "not integration"

import inspect
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch
from datetime import datetime, timezone, timedelta


def _make_yf_df(n: int = 50, with_volume: bool = True, use_date_index: bool = False) -> pd.DataFrame:
    """Mock DataFrame matching yfinance.download() output."""
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    idx_name = "Date" if use_date_index else "Datetime"
    idx = pd.DatetimeIndex(
        [base + timedelta(hours=i) for i in range(n)], name=idx_name
    )
    price = 150.0
    rows = []
    for _ in range(n):
        price *= 1 + np.random.normal(0, 0.005)
        rows.append({
            "Open":   round(price * 0.999, 4),
            "High":   round(price * 1.002, 4),
            "Low":    round(price * 0.997, 4),
            "Close":  round(price, 4),
            "Volume": int(abs(np.random.normal(1_000_000, 200_000))) if with_volume else 0,
        })
    return pd.DataFrame(rows, index=idx)


# -- fetch_yfinance_ohlcv -------------------------------------------------------

class TestFetchYfinanceOhlcv:
    def test_columns_normalized(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        with patch("data.yfinance_fetcher.yf.download", return_value=_make_yf_df(30)):
            result = fetch_yfinance_ohlcv("AAPL")
        assert list(result.columns) == ["timestamp", "open", "high", "low", "close", "volume"]

    def test_returns_dataframe_with_correct_length(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        with patch("data.yfinance_fetcher.yf.download", return_value=_make_yf_df(50)):
            result = fetch_yfinance_ohlcv("AAPL")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 50

    def test_timestamp_is_utc(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        with patch("data.yfinance_fetcher.yf.download", return_value=_make_yf_df(20)):
            result = fetch_yfinance_ohlcv("AAPL")
        assert str(result["timestamp"].dt.tz) == "UTC"

    def test_empty_download_returns_empty_df(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        with patch("data.yfinance_fetcher.yf.download", return_value=pd.DataFrame()):
            result = fetch_yfinance_ohlcv("AAPL")
        assert result.empty

    def test_exception_returns_empty_df(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        with patch("data.yfinance_fetcher.yf.download", side_effect=Exception("network error")):
            result = fetch_yfinance_ohlcv("AAPL")
        assert result.empty

    def test_forex_zero_volume_accepted(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        with patch("data.yfinance_fetcher.yf.download", return_value=_make_yf_df(20, with_volume=False)):
            result = fetch_yfinance_ohlcv("EUR-USD")
        assert not result.empty
        assert (result["volume"] == 0).all()

    def test_multilevel_columns_flattened(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        raw = _make_yf_df(20)
        raw.columns = pd.MultiIndex.from_tuples(
            [(col, "AAPL") for col in raw.columns]
        )
        with patch("data.yfinance_fetcher.yf.download", return_value=raw):
            result = fetch_yfinance_ohlcv("AAPL")
        assert list(result.columns) == ["timestamp", "open", "high", "low", "close", "volume"]

    def test_ticker_map_resolves_forex(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        calls = []
        def mock_dl(ticker, **kwargs):
            calls.append(ticker)
            return _make_yf_df(10)
        with patch("data.yfinance_fetcher.yf.download", side_effect=mock_dl):
            fetch_yfinance_ohlcv("EUR-USD")
        assert calls[0] == "EURUSD=X"

    def test_1h_days_back_capped_at_730(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        captured = {}
        def mock_dl(ticker, **kwargs):
            captured.update(kwargs)
            return _make_yf_df(10)
        with patch("data.yfinance_fetcher.yf.download", side_effect=mock_dl):
            fetch_yfinance_ohlcv("AAPL", granularity="1h", days_back=1000)
        start = datetime.strptime(captured["start"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        expected = datetime.now(timezone.utc) - timedelta(days=729)
        assert abs((start - expected).days) <= 1

    def test_date_index_also_handled(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        with patch("data.yfinance_fetcher.yf.download", return_value=_make_yf_df(10, use_date_index=True)):
            result = fetch_yfinance_ohlcv("AAPL")
        assert "timestamp" in result.columns
        assert not result.empty

    def test_sorted_ascending(self):
        from data.yfinance_fetcher import fetch_yfinance_ohlcv
        with patch("data.yfinance_fetcher.yf.download", return_value=_make_yf_df(30)):
            result = fetch_yfinance_ohlcv("MSFT")
        assert result["timestamp"].is_monotonic_increasing


# -- cleaner gap_fill parameter -----------------------------------------------

class TestCleanerGapFill:
    def _df_with_isolated_nan(self) -> pd.DataFrame:
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        n = 20
        df = pd.DataFrame({
            "timestamp": pd.to_datetime([base + timedelta(hours=i) for i in range(n)], utc=True),
            "open":   [100.0] * n,
            "high":   [101.0] * n,
            "low":    [99.0]  * n,
            "close":  [100.5] * n,
            "volume": [1000.0] * n,
        })
        df.loc[5, "close"] = float("nan")   # isolated single NaN
        df.loc[10, "open"] = float("nan")
        return df

    def test_gap_fill_true_fills_isolated_nans(self):
        from data.cleaner import clean_ohlcv
        result = clean_ohlcv(self._df_with_isolated_nan(), gap_fill=True)
        assert not result[["open", "high", "low", "close"]].isna().any().any()

    def test_gap_fill_false_leaves_nans_unfilled(self):
        from data.cleaner import clean_ohlcv
        result = clean_ohlcv(self._df_with_isolated_nan(), gap_fill=False)
        assert result[["open", "close"]].isna().any().any()

    def test_default_is_gap_fill_true(self):
        from data.cleaner import clean_ohlcv
        sig = inspect.signature(clean_ohlcv)
        assert sig.parameters["gap_fill"].default is True

    def test_gap_fill_false_still_sorts_and_dedupes(self):
        from data.cleaner import clean_ohlcv
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        n = 10
        df = pd.DataFrame({
            "timestamp": pd.to_datetime([base + timedelta(hours=i) for i in range(n)], utc=True),
            "open":   [100.0] * n,
            "high":   [101.0] * n,
            "low":    [99.0]  * n,
            "close":  [100.5] * n,
            "volume": [1000.0] * n,
        })
        # Reverse order + duplicate first row
        df = pd.concat([df.iloc[[0]], df]).iloc[::-1].reset_index(drop=True)
        result = clean_ohlcv(df, gap_fill=False)
        assert result["timestamp"].is_monotonic_increasing
        assert result["timestamp"].duplicated().sum() == 0


# -- fetch_candles routing ------------------------------------------------------

class TestFetchCandlesRoutesYfinance:
    def test_routes_stock_to_yfinance(self):
        from data.historical import fetch_candles
        with patch("data.yfinance_fetcher.yf.download", return_value=_make_yf_df(20)):
            result = fetch_candles("AAPL", granularity="1h", days_back=7)
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_routes_forex_to_yfinance(self):
        from data.historical import fetch_candles
        with patch("data.yfinance_fetcher.yf.download", return_value=_make_yf_df(20)):
            result = fetch_candles("EUR-USD", granularity="1h", days_back=7)
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_all_stock_tickers_in_asset_source(self):
        from config.settings import ASSET_SOURCE, STOCK_TICKERS
        for t in STOCK_TICKERS:
            assert ASSET_SOURCE.get(t) == "yfinance", f"{t} not routed to yfinance"

    def test_all_forex_tickers_in_asset_source(self):
        from config.settings import ASSET_SOURCE, FOREX_TICKERS
        for t in FOREX_TICKERS:
            assert ASSET_SOURCE.get(t) == "yfinance", f"{t} not routed to yfinance"

    def test_all_assets_count(self):
        from config.settings import ALL_ASSETS
        assert len(ALL_ASSETS) == 22, f"Expected 22 assets, got {len(ALL_ASSETS)}"


# -- DEX sentiment skips yfinance assets ---------------------------------------

class TestDexSentimentSkipsYfinance:
    def test_stock_returns_neutral(self):
        from sentiment.dex_sentiment import fetch_dex_sentiment
        result = fetch_dex_sentiment("AAPL")
        assert result["score"] == 0.0
        assert result["confidence"] == 0.0
        assert "non-DEX" in result.get("note", "")

    def test_forex_returns_neutral(self):
        from sentiment.dex_sentiment import fetch_dex_sentiment
        result = fetch_dex_sentiment("EUR-USD")
        assert result["score"] == 0.0
        assert result["confidence"] == 0.0


# -- Integration ---------------------------------------------------------------

@pytest.mark.integration
def test_aapl_live():
    from data.yfinance_fetcher import fetch_yfinance_ohlcv
    result = fetch_yfinance_ohlcv("AAPL", granularity="1h", days_back=30)
    assert not result.empty
    assert len(result) > 50
    print(f"\nAAPL live: {len(result)} candles, "
          f"{result['timestamp'].min().date()} → {result['timestamp'].max().date()}")


@pytest.mark.integration
def test_eurusd_live():
    from data.yfinance_fetcher import fetch_yfinance_ohlcv
    result = fetch_yfinance_ohlcv("EUR-USD", granularity="1h", days_back=30)
    assert not result.empty
    print(f"\nEUR-USD live: {len(result)} candles, volume sample: {result['volume'].head(3).tolist()}")
