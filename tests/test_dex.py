import pytest
import pandas as pd
from unittest.mock import patch

from data.dex_fetcher import _select_best_pair
from data.gecko_fetcher import _parse_ohlcv_response
from config.settings import SOLANA_TOKENS, ASSET_SOURCE, ALL_ASSETS


# --- Config tests ---

def test_all_assets_have_source():
    for asset in ALL_ASSETS:
        assert asset in ASSET_SOURCE, f"{asset} missing from ASSET_SOURCE"

def test_all_dex_assets_have_mint_address():
    dex_assets = [a for a, s in ASSET_SOURCE.items() if s == "dex"]
    for asset in dex_assets:
        assert asset in SOLANA_TOKENS, f"{asset} is 'dex' source but missing from SOLANA_TOKENS"

def test_solana_token_addresses_are_valid_length():
    for symbol, address in SOLANA_TOKENS.items():
        assert 32 <= len(address) <= 44, (
            f"{symbol} mint address '{address}' looks invalid (length {len(address)})"
        )


# --- dex_fetcher tests ---

def make_pair(liquidity: float, volume: float, chain: str = "solana") -> dict:
    return {
        "chainId": chain,
        "pairAddress": "fake_pair_address",
        "dexId": "raydium",
        "priceUsd": "1.00",
        "liquidity": {"usd": liquidity},
        "volume": {"h24": volume},
        "baseToken": {"symbol": "TEST", "name": "Test Token"},
    }

def test_select_best_pair_picks_highest_liquidity():
    pairs = [
        make_pair(liquidity=100_000, volume=50_000),
        make_pair(liquidity=500_000, volume=200_000),
        make_pair(liquidity=200_000, volume=80_000),
    ]
    best = _select_best_pair(pairs, "TEST")
    assert best["liquidity"]["usd"] == 500_000

def test_select_best_pair_filters_non_solana():
    pairs = [
        make_pair(liquidity=1_000_000, volume=500_000, chain="ethereum"),
        make_pair(liquidity=100_000, volume=50_000, chain="solana"),
    ]
    best = _select_best_pair(pairs, "TEST")
    assert best["chainId"] == "solana"

def test_select_best_pair_returns_none_if_no_solana_pairs():
    pairs = [make_pair(liquidity=1_000_000, volume=500_000, chain="ethereum")]
    best = _select_best_pair(pairs, "TEST")
    assert best is None

def test_select_best_pair_falls_back_below_threshold():
    pairs = [make_pair(liquidity=1_000, volume=500)]
    best = _select_best_pair(pairs, "TEST")
    assert best is not None
    assert best.get("_below_threshold") == True


# --- gecko_fetcher tests ---

def test_parse_ohlcv_response_valid():
    import time
    now = int(time.time())
    mock_response = {
        "data": {
            "attributes": {
                "ohlcv_list": [
                    [now - 3600, 100.0, 105.0, 98.0, 102.0, 5000.0],
                    [now - 7200, 99.0,  103.0, 97.0, 100.0, 4500.0],
                ]
            }
        }
    }
    df = _parse_ohlcv_response(mock_response)
    assert len(df) == 2
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert df["close"].dtype == float

def test_parse_ohlcv_response_empty():
    mock_response = {"data": {"attributes": {"ohlcv_list": []}}}
    df = _parse_ohlcv_response(mock_response)
    assert df.empty

def test_parse_ohlcv_response_malformed():
    df = _parse_ohlcv_response({"unexpected": "structure"})
    assert df.empty

def test_parse_ohlcv_columns_match_coinbase_schema():
    import time
    now = int(time.time())
    mock = {"data": {"attributes": {"ohlcv_list": [[now, 1.0, 1.1, 0.9, 1.05, 1000.0]]}}}
    df = _parse_ohlcv_response(mock)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


# --- routing tests ---

def test_fetch_candles_routes_coinbase():
    with patch("data.historical._fetch_from_coinbase") as mock_cb, \
         patch("data.historical._fetch_from_dex") as mock_dex:
        mock_cb.return_value = pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        from data.historical import fetch_candles
        fetch_candles("BTC-USD", "1h", 7)
        mock_cb.assert_called_once()
        mock_dex.assert_not_called()

def test_fetch_candles_routes_dex():
    with patch("data.historical._fetch_from_coinbase") as mock_cb, \
         patch("data.historical._fetch_from_dex") as mock_dex:
        mock_dex.return_value = pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        from data.historical import fetch_candles
        fetch_candles("JUP", "1h", 7)
        mock_dex.assert_called_once()
        mock_cb.assert_not_called()


# --- Integration tests (live API calls) ---

@pytest.mark.integration
def test_fetch_token_info_live():
    from data.dex_fetcher import fetch_token_info
    info = fetch_token_info("JUP")
    assert info is not None
    assert info["price_usd"] > 0
    assert info["pair_address"] != ""
    assert info["symbol"] == "JUP"
    print(f"\nJUP live: ${info['price_usd']:.6f}, liq=${info['liquidity_usd']:,.0f}, vol24h=${info['volume_24h']:,.0f}")

@pytest.mark.integration
def test_fetch_dex_candles_live():
    from data.gecko_fetcher import fetch_dex_candles
    from data.cleaner import validate_ohlcv
    df = fetch_dex_candles("JUP", granularity="1h", days_back=3)
    assert not df.empty
    is_valid, errors = validate_ohlcv(df)
    assert is_valid, f"Live DEX candle data failed validation: {errors}"
    print(f"\nJUP live candles: {len(df)} rows")
    print(df[["timestamp", "open", "high", "low", "close", "volume"]].tail(3).to_string(index=False))

@pytest.mark.integration
def test_all_dex_prices_live():
    from data.dex_fetcher import fetch_all_dex_prices
    prices = fetch_all_dex_prices()
    assert len(prices) > 0
    print(f"\nDEX prices: {len(prices)}/{len(SOLANA_TOKENS)}")
    for sym, price in prices.items():
        print(f"  {sym}: ${price:.8f}")
