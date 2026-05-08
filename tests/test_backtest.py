import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from backtest.engine import BacktestEngine, BacktestResult, TradeRecord
from backtest.strategies import (
    Signal, BaseStrategy,
    MACDCrossStrategy, RSIMeanReversionStrategy,
    BollingerBandStrategy, ZAERYNMLStrategy,
)
from backtest.metrics import (
    compute_max_drawdown, compute_sharpe, compute_sortino,
    compute_calmar, compute_annualized_return, compute_metrics,
    compute_win_loss_ratio,
)
from config.settings import (
    BACKTEST_COMMISSION_PCT, BACKTEST_INITIAL_CAPITAL,
    BACKTEST_STOP_LOSS_PCT, BACKTEST_TAKE_PROFIT_PCT,
    INDICATOR_WARMUP, MIN_TRADES_FOR_METRICS,
)


# -- Synthetic helpers ---------------------------------------------------------

def make_candles(n: int = 300, seed: int = 42, trend: str = "flat") -> pd.DataFrame:
    np.random.seed(seed)

    if trend == "up":
        drift = 0.001
    elif trend == "down":
        drift = -0.001
    else:
        drift = 0.0

    returns    = np.random.normal(drift, 0.02, n)
    prices     = 40000.0 * np.exp(np.cumsum(returns))
    timestamps = pd.date_range(
        end=datetime.now(timezone.utc), periods=n, freq="1h"
    )

    df = pd.DataFrame({
        "timestamp": timestamps,
        "close":     prices,
        "open":      prices * (1 + np.random.normal(0, 0.002, n)),
        "high":      prices * (1 + np.abs(np.random.normal(0, 0.005, n))),
        "low":       prices * (1 - np.abs(np.random.normal(0, 0.005, n))),
        "volume":    np.random.uniform(500, 5000, n),
    })
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"]  = df[["low",  "open", "close"]].min(axis=1)

    from data.cleaner import clean_ohlcv, normalize_price_data
    from models.features import compute_technical_indicators

    df = clean_ohlcv(df)
    df = normalize_price_data(df)
    df = compute_technical_indicators(df)
    return df


def make_trade(pnl_usd: float, pnl_pct: float) -> TradeRecord:
    now = datetime.now(timezone.utc)
    return TradeRecord(
        asset="BTC-USD",
        strategy="Test",
        entry_time=now,
        entry_price=40000.0,
        exit_time=now + timedelta(hours=2),
        exit_price=40000.0 * (1 + pnl_pct / 100),
        position_usd=1000.0,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        exit_reason="SIGNAL",
        signal_reason="test",
    )


# -- compute_max_drawdown ------------------------------------------------------

def test_max_drawdown_no_drawdown():
    curve = [1000, 1100, 1200, 1300, 1400]
    assert compute_max_drawdown(curve) == 0.0

def test_max_drawdown_full_loss():
    curve = [1000, 500, 100, 10]
    dd    = compute_max_drawdown(curve)
    assert dd == pytest.approx(99.0, abs=1.0)

def test_max_drawdown_known_value():
    curve = [1000, 900, 800, 950, 1000]
    dd    = compute_max_drawdown(curve)
    assert dd == pytest.approx(20.0, abs=0.01)

def test_max_drawdown_empty():
    assert compute_max_drawdown([]) == 0.0

def test_max_drawdown_single():
    assert compute_max_drawdown([1000.0]) == 0.0


# -- compute_sharpe ------------------------------------------------------------

def test_sharpe_zero_variance():
    curve = [1000.0] * 100
    assert compute_sharpe(curve) == 0.0

def test_sharpe_positive_returns():
    curve  = [1000 * (1.001 ** i) for i in range(500)]
    sharpe = compute_sharpe(curve)
    assert sharpe > 0

def test_sharpe_negative_returns():
    curve  = [1000 * (0.999 ** i) for i in range(500)]
    sharpe = compute_sharpe(curve)
    assert sharpe < 0

def test_sharpe_insufficient_data():
    assert compute_sharpe([1000.0]) == 0.0


# -- compute_annualized_return -------------------------------------------------

def test_annualized_return_zero():
    assert compute_annualized_return(0.0, 1000) == pytest.approx(0.0, abs=0.001)

def test_annualized_return_positive():
    result = compute_annualized_return(10.0, 8760)
    assert abs(result - 10.0) < 1.0

def test_annualized_return_zero_candles():
    assert compute_annualized_return(10.0, 0) == 0.0


# -- compute_win_loss_ratio ----------------------------------------------------

def test_win_loss_ratio_known():
    trades = (
        [make_trade(50.0,  5.0)] * 3 +
        [make_trade(-20.0, -2.0)] * 3
    )
    ratio = compute_win_loss_ratio(trades)
    assert ratio == pytest.approx(2.5, abs=0.01)

def test_win_loss_ratio_no_losers():
    trades = [make_trade(50.0, 5.0)] * 5
    ratio  = compute_win_loss_ratio(trades)
    assert ratio > 0

def test_win_loss_ratio_empty():
    assert compute_win_loss_ratio([]) == 1.5


# -- Strategy signal tests -----------------------------------------------------

def test_macd_signal_hold_insufficient_data():
    # MACD needs 2 rows — pass a single-row window directly
    now = datetime.now(timezone.utc)
    df  = pd.DataFrame({
        "timestamp": [now], "close": [40000.0], "open": [39900.0],
        "high": [40100.0], "low": [39800.0], "volume": [1000.0],
        "macd": [0.1], "macd_signal": [0.05],
    })
    strat  = MACDCrossStrategy()
    signal = strat.generate_signal(df)
    assert signal.action == "HOLD"

def test_macd_signal_returns_valid_action():
    df    = make_candles(200)
    strat = MACDCrossStrategy()
    for i in range(10, 50):
        signal = strat.generate_signal(df.iloc[:i])
        assert signal.action in ("BUY", "SELL", "HOLD")
        assert 0.0 <= signal.confidence <= 1.0

def test_rsi_buy_when_oversold():
    df    = make_candles(200)
    strat = RSIMeanReversionStrategy(oversold=30, overbought=70)
    df_mod = df.copy()
    df_mod.loc[df_mod.index[-1], "rsi_14"] = 20.0
    signal = strat.generate_signal(df_mod)
    assert signal.action == "BUY"

def test_rsi_sell_when_overbought():
    df    = make_candles(200)
    strat = RSIMeanReversionStrategy(oversold=30, overbought=70)
    df_mod = df.copy()
    df_mod.loc[df_mod.index[-1], "rsi_14"] = 80.0
    signal = strat.generate_signal(df_mod)
    assert signal.action == "SELL"

def test_rsi_hold_in_neutral_zone():
    df    = make_candles(200)
    strat = RSIMeanReversionStrategy(oversold=30, overbought=70)
    df_mod = df.copy()
    df_mod.loc[df_mod.index[-1], "rsi_14"] = 50.0
    signal = strat.generate_signal(df_mod)
    assert signal.action == "HOLD"

def test_bollinger_buy_at_lower_band():
    df    = make_candles(200)
    strat = BollingerBandStrategy(lower_threshold=0.05, upper_threshold=0.95)
    df_mod = df.copy()
    df_mod.loc[df_mod.index[-1], "bb_position"] = 0.01
    signal = strat.generate_signal(df_mod)
    assert signal.action == "BUY"

def test_bollinger_sell_at_upper_band():
    df    = make_candles(200)
    strat = BollingerBandStrategy()
    df_mod = df.copy()
    df_mod.loc[df_mod.index[-1], "bb_position"] = 0.99
    signal = strat.generate_signal(df_mod)
    assert signal.action == "SELL"


# -- BacktestEngine tests ------------------------------------------------------

def make_engine_result(n_candles: int = 300, trend: str = "flat") -> BacktestResult:
    df     = make_candles(n_candles, trend=trend)
    engine = BacktestEngine(strategy=MACDCrossStrategy())

    with patch("backtest.engine.load_candles", return_value=df), \
         patch("backtest.engine.clean_ohlcv", side_effect=lambda x: x), \
         patch("backtest.engine.normalize_price_data", side_effect=lambda x: x), \
         patch("backtest.engine.compute_technical_indicators", side_effect=lambda x: x):
        result = engine.run("BTC-USD", days_back=30)

    return result


def test_engine_equity_curve_length():
    n = 300
    r = make_engine_result(n)
    assert len(r.equity_curve) == n - INDICATOR_WARMUP


def test_engine_final_capital_matches_equity_curve():
    r = make_engine_result(300)
    if r.equity_curve:
        assert abs(r.final_capital - r.equity_curve[-1]) < 1.0


def test_engine_commission_reduces_capital():
    class AlwaysBuyStrategy(BaseStrategy):
        name = "Always Buy"
        def __init__(self):
            self._bought = False
        def generate_signal(self, window):
            if not self._bought:
                self._bought = True
                return Signal("BUY", 1.0, "always buy")
            return Signal("SELL", 1.0, "always sell")

    df     = make_candles(200)
    engine = BacktestEngine(strategy=AlwaysBuyStrategy(), commission_pct=0.001)

    with patch("backtest.engine.load_candles", return_value=df), \
         patch("backtest.engine.clean_ohlcv", side_effect=lambda x: x), \
         patch("backtest.engine.normalize_price_data", side_effect=lambda x: x), \
         patch("backtest.engine.compute_technical_indicators", side_effect=lambda x: x):
        result = engine.run("BTC-USD")

    assert result.final_capital < BACKTEST_INITIAL_CAPITAL + 100


def test_engine_no_open_position_at_end_by_default():
    r = make_engine_result(300)
    eod_trades = [t for t in r.trades if t.exit_reason == "END_OF_DATA"]
    assert len(eod_trades) <= 1


def test_engine_stop_loss_uses_low_not_close():
    df = make_candles(200)

    entry_price = float(df["close"].iloc[INDICATOR_WARMUP])
    stop_price  = entry_price * 0.99

    df_mod = df.copy()
    df_mod.loc[df_mod.index[INDICATOR_WARMUP + 2], "low"]   = stop_price * 0.99
    df_mod.loc[df_mod.index[INDICATOR_WARMUP + 2], "close"] = stop_price * 1.01

    class BuyOnceStrategy(BaseStrategy):
        name = "Buy Once"
        def __init__(self):
            self._count = 0
        def generate_signal(self, window):
            if self._count == 0:
                self._count += 1
                return Signal("BUY", 1.0, "buy")
            return Signal("HOLD", 0.0, "hold")

    engine = BacktestEngine(strategy=BuyOnceStrategy(), stop_loss_pct=0.01)

    with patch("backtest.engine.load_candles", return_value=df_mod), \
         patch("backtest.engine.clean_ohlcv", side_effect=lambda x: x), \
         patch("backtest.engine.normalize_price_data", side_effect=lambda x: x), \
         patch("backtest.engine.compute_technical_indicators", side_effect=lambda x: x):
        result = engine.run("BTC-USD")

    stop_exits = [t for t in result.trades if t.exit_reason == "STOP_LOSS"]
    assert len(stop_exits) >= 1, "Stop loss was not triggered despite low price crossing threshold"


# -- compute_metrics tests -----------------------------------------------------

def test_compute_metrics_keys():
    r = make_engine_result(300)
    m = compute_metrics(r)
    required = [
        "strategy", "asset", "total_return_pct", "annualized_return_pct",
        "total_trades", "win_rate_pct", "max_drawdown_pct",
        "sharpe_ratio", "profit_factor", "win_loss_ratio",
    ]
    for key in required:
        assert key in m, f"Missing metric key: {key}"

def test_compute_metrics_warning_few_trades():
    r = BacktestResult(
        strategy_name="Test",
        asset="BTC-USD",
        granularity="1h",
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc),
        initial_capital=10000.0,
        final_capital=10100.0,
        trades=[make_trade(10.0, 1.0)] * 3,
        equity_curve=[10000.0] * 100,
    )
    m = compute_metrics(r)
    assert "warning" in m

def test_compute_metrics_no_trades():
    r = BacktestResult(
        strategy_name="Test",
        asset="BTC-USD",
        granularity="1h",
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc),
        initial_capital=10000.0,
        final_capital=10000.0,
        trades=[],
        equity_curve=[10000.0] * 100,
    )
    m = compute_metrics(r)
    assert m["total_trades"] == 0
    assert m["win_rate_pct"] == 0.0

def test_profit_factor_all_winners():
    r = BacktestResult(
        strategy_name="Test", asset="BTC-USD", granularity="1h",
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc),
        initial_capital=10000.0, final_capital=11000.0,
        trades=[make_trade(100.0, 10.0)] * 5,
        equity_curve=[10000 + i * 200 for i in range(100)],
    )
    m = compute_metrics(r)
    assert m["profit_factor"] == 999.0


# -- BacktestResult serialization ----------------------------------------------

def test_backtest_result_to_dict_no_datetimes():
    import json
    r = BacktestResult(
        strategy_name="MACD Cross", asset="BTC-USD", granularity="1h",
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc),
        initial_capital=10000.0, final_capital=10200.0,
        trades=[make_trade(50.0, 5.0)],
        equity_curve=[10000.0, 10100.0, 10200.0],
    )
    d = r.to_dict()
    serialized = json.dumps(d)
    assert len(serialized) > 0

def test_trade_record_to_dict():
    import json
    t = make_trade(50.0, 5.0)
    d = t.to_dict()
    json.dumps(d)


# -- Integration tests ---------------------------------------------------------

@pytest.mark.integration
def test_macd_backtest_live():
    engine = BacktestEngine(strategy=MACDCrossStrategy())
    result = engine.run("BTC-USD", days_back=90)
    assert result.final_capital > 0
    assert len(result.equity_curve) > 0
    m = compute_metrics(result)
    print(f"\nMACD BTC-USD: return={m['total_return_pct']:.2f}% trades={m['total_trades']} sharpe={m['sharpe_ratio']:.3f}")

@pytest.mark.integration
def test_zaeryn_ml_backtest_live():
    engine = BacktestEngine(strategy=ZAERYNMLStrategy("BTC-USD"))
    result = engine.run("BTC-USD", days_back=90)
    m = compute_metrics(result)
    print(f"\nZAERYN ML BTC-USD: return={m['total_return_pct']:.2f}% trades={m['total_trades']} sharpe={m['sharpe_ratio']:.3f}")

@pytest.mark.integration
def test_all_strategies_btc():
    from backtest.reporter import compare_strategies, print_comparison_table

    strategies = [
        MACDCrossStrategy(),
        RSIMeanReversionStrategy(),
        BollingerBandStrategy(),
        ZAERYNMLStrategy("BTC-USD"),
    ]
    results = []
    for strat in strategies:
        engine = BacktestEngine(strategy=strat)
        r = engine.run("BTC-USD", days_back=60)
        m = compute_metrics(r)
        results.append((r, m))

    df = compare_strategies(results)
    print_comparison_table(df)
    assert len(df) == 4
