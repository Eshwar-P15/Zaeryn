from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestEngine, BacktestResult, TradeRecord
from backtest.metrics import (
    compute_annualized_return,
    compute_calmar,
    compute_max_drawdown,
    compute_metrics,
    compute_sharpe,
    compute_sortino,
    compute_win_loss_ratio,
)
from backtest.strategies import (
    BaseStrategy,
    BollingerBandStrategy,
    MACDCrossStrategy,
    RSIMeanReversionStrategy,
    Signal,
    ZAERYNMLStrategy,
)
from config.settings import (
    BACKTEST_INITIAL_CAPITAL,
    INDICATOR_WARMUP,
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

    returns = np.random.normal(drift, 0.02, n)
    prices = 40000.0 * np.exp(np.cumsum(returns))
    timestamps = pd.date_range(end=datetime.now(UTC), periods=n, freq="1h")

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "close": prices,
            "open": prices * (1 + np.random.normal(0, 0.002, n)),
            "high": prices * (1 + np.abs(np.random.normal(0, 0.005, n))),
            "low": prices * (1 - np.abs(np.random.normal(0, 0.005, n))),
            "volume": np.random.uniform(500, 5000, n),
        }
    )
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"] = df[["low", "open", "close"]].min(axis=1)

    from data.cleaner import clean_ohlcv, normalize_price_data
    from models.features import compute_technical_indicators

    df = clean_ohlcv(df)
    df = normalize_price_data(df)
    df = compute_technical_indicators(df)
    return df


def make_trade(pnl_usd: float, pnl_pct: float) -> TradeRecord:
    now = datetime.now(UTC)
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
    dd = compute_max_drawdown(curve)
    assert dd == pytest.approx(99.0, abs=1.0)


def test_max_drawdown_known_value():
    curve = [1000, 900, 800, 950, 1000]
    dd = compute_max_drawdown(curve)
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
    curve = [1000 * (1.001**i) for i in range(500)]
    sharpe = compute_sharpe(curve)
    assert sharpe > 0


def test_sharpe_negative_returns():
    curve = [1000 * (0.999**i) for i in range(500)]
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
    trades = [make_trade(50.0, 5.0)] * 3 + [make_trade(-20.0, -2.0)] * 3
    ratio = compute_win_loss_ratio(trades)
    assert ratio == pytest.approx(2.5, abs=0.01)


def test_win_loss_ratio_no_losers():
    trades = [make_trade(50.0, 5.0)] * 5
    ratio = compute_win_loss_ratio(trades)
    assert ratio > 0


def test_win_loss_ratio_empty():
    assert compute_win_loss_ratio([]) == 1.5


# -- Strategy signal tests -----------------------------------------------------


def test_macd_signal_hold_insufficient_data():
    # MACD needs 2 rows — pass a single-row window directly
    now = datetime.now(UTC)
    df = pd.DataFrame(
        {
            "timestamp": [now],
            "close": [40000.0],
            "open": [39900.0],
            "high": [40100.0],
            "low": [39800.0],
            "volume": [1000.0],
            "macd": [0.1],
            "macd_signal": [0.05],
        }
    )
    strat = MACDCrossStrategy()
    signal = strat.generate_signal(df)
    assert signal.action == "HOLD"


def test_macd_signal_returns_valid_action():
    df = make_candles(200)
    strat = MACDCrossStrategy()
    for i in range(10, 50):
        signal = strat.generate_signal(df.iloc[:i])
        assert signal.action in ("BUY", "SELL", "HOLD")
        assert 0.0 <= signal.confidence <= 1.0


def test_rsi_buy_when_oversold():
    df = make_candles(200)
    strat = RSIMeanReversionStrategy(oversold=30, overbought=70)
    df_mod = df.copy()
    df_mod.loc[df_mod.index[-1], "rsi_14"] = 20.0
    signal = strat.generate_signal(df_mod)
    assert signal.action == "BUY"


def test_rsi_sell_when_overbought():
    df = make_candles(200)
    strat = RSIMeanReversionStrategy(oversold=30, overbought=70)
    df_mod = df.copy()
    df_mod.loc[df_mod.index[-1], "rsi_14"] = 80.0
    signal = strat.generate_signal(df_mod)
    assert signal.action == "SELL"


def test_rsi_hold_in_neutral_zone():
    df = make_candles(200)
    strat = RSIMeanReversionStrategy(oversold=30, overbought=70)
    df_mod = df.copy()
    df_mod.loc[df_mod.index[-1], "rsi_14"] = 50.0
    signal = strat.generate_signal(df_mod)
    assert signal.action == "HOLD"


def test_bollinger_buy_at_lower_band():
    df = make_candles(200)
    strat = BollingerBandStrategy(lower_threshold=0.05, upper_threshold=0.95)
    df_mod = df.copy()
    df_mod.loc[df_mod.index[-1], "bb_position"] = 0.01
    signal = strat.generate_signal(df_mod)
    assert signal.action == "BUY"


def test_bollinger_sell_at_upper_band():
    df = make_candles(200)
    strat = BollingerBandStrategy()
    df_mod = df.copy()
    df_mod.loc[df_mod.index[-1], "bb_position"] = 0.99
    signal = strat.generate_signal(df_mod)
    assert signal.action == "SELL"


# -- BacktestEngine tests ------------------------------------------------------


def make_engine_result(n_candles: int = 300, trend: str = "flat") -> BacktestResult:
    df = make_candles(n_candles, trend=trend)
    engine = BacktestEngine(strategy=MACDCrossStrategy())

    with (
        patch("backtest.engine.load_candles", return_value=df),
        patch("backtest.engine.clean_ohlcv", side_effect=lambda x: x),
        patch("backtest.engine.normalize_price_data", side_effect=lambda x: x),
        patch("backtest.engine.compute_technical_indicators", side_effect=lambda x: x),
    ):
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

    df = make_candles(200)
    engine = BacktestEngine(strategy=AlwaysBuyStrategy(), commission_pct=0.001)

    with (
        patch("backtest.engine.load_candles", return_value=df),
        patch("backtest.engine.clean_ohlcv", side_effect=lambda x: x),
        patch("backtest.engine.normalize_price_data", side_effect=lambda x: x),
        patch("backtest.engine.compute_technical_indicators", side_effect=lambda x: x),
    ):
        result = engine.run("BTC-USD")

    assert result.final_capital < BACKTEST_INITIAL_CAPITAL + 100


def test_engine_no_open_position_at_end_by_default():
    r = make_engine_result(300)
    eod_trades = [t for t in r.trades if t.exit_reason == "END_OF_DATA"]
    assert len(eod_trades) <= 1


def test_engine_stop_loss_uses_low_not_close():
    df = make_candles(200)

    entry_price = float(df["close"].iloc[INDICATOR_WARMUP])
    stop_price = entry_price * 0.99

    df_mod = df.copy()
    df_mod.loc[df_mod.index[INDICATOR_WARMUP + 2], "low"] = stop_price * 0.99
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

    with (
        patch("backtest.engine.load_candles", return_value=df_mod),
        patch("backtest.engine.clean_ohlcv", side_effect=lambda x: x),
        patch("backtest.engine.normalize_price_data", side_effect=lambda x: x),
        patch("backtest.engine.compute_technical_indicators", side_effect=lambda x: x),
    ):
        result = engine.run("BTC-USD")

    stop_exits = [t for t in result.trades if t.exit_reason == "STOP_LOSS"]
    assert len(stop_exits) >= 1, "Stop loss was not triggered despite low price crossing threshold"


# -- compute_metrics tests -----------------------------------------------------


def test_compute_metrics_keys():
    r = make_engine_result(300)
    m = compute_metrics(r)
    required = [
        "strategy",
        "asset",
        "total_return_pct",
        "annualized_return_pct",
        "total_trades",
        "win_rate_pct",
        "max_drawdown_pct",
        "sharpe_ratio",
        "profit_factor",
        "win_loss_ratio",
    ]
    for key in required:
        assert key in m, f"Missing metric key: {key}"


def test_compute_metrics_warning_few_trades():
    r = BacktestResult(
        strategy_name="Test",
        asset="BTC-USD",
        granularity="1h",
        start_date=datetime.now(UTC),
        end_date=datetime.now(UTC),
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
        start_date=datetime.now(UTC),
        end_date=datetime.now(UTC),
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
        strategy_name="Test",
        asset="BTC-USD",
        granularity="1h",
        start_date=datetime.now(UTC),
        end_date=datetime.now(UTC),
        initial_capital=10000.0,
        final_capital=11000.0,
        trades=[make_trade(100.0, 10.0)] * 5,
        equity_curve=[10000 + i * 200 for i in range(100)],
    )
    m = compute_metrics(r)
    assert m["profit_factor"] == 999.0


# -- BacktestResult serialization ----------------------------------------------


def test_backtest_result_to_dict_no_datetimes():
    import json

    r = BacktestResult(
        strategy_name="MACD Cross",
        asset="BTC-USD",
        granularity="1h",
        start_date=datetime.now(UTC),
        end_date=datetime.now(UTC),
        initial_capital=10000.0,
        final_capital=10200.0,
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
    print(
        f"\nMACD BTC-USD: return={m['total_return_pct']:.2f}% trades={m['total_trades']} sharpe={m['sharpe_ratio']:.3f}"
    )


@pytest.mark.integration
def test_zaeryn_ml_backtest_live():
    engine = BacktestEngine(strategy=ZAERYNMLStrategy("BTC-USD"))
    result = engine.run("BTC-USD", days_back=90)
    m = compute_metrics(result)
    print(
        f"\nZAERYN ML BTC-USD: return={m['total_return_pct']:.2f}% trades={m['total_trades']} sharpe={m['sharpe_ratio']:.3f}"
    )


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


# ════════════════════════════════════════════════════════════════════════════
# Sortino ratio — external ground truth (Phase 7 Step 1 Ticket 7, finding 11)
# ════════════════════════════════════════════════════════════════════════════
#
# Documented convention from backtest/metrics.py:45-61. A test reader should
# be able to verify expected values from this block alone:
#
#   sortino = (excess_returns.mean() / downside_returns.std(ddof=1))
#             * sqrt(BACKTEST_ANNUALIZATION)
#
#   - INPUT is the EQUITY CURVE; pct_change() is computed internally.
#   - excess_returns = returns - (RISK_FREE_RATE_ANNUAL / BACKTEST_ANNUALIZATION)
#                    = returns - 0.05 / 8760 ≈ returns - 5.7078e-6
#   - Downside threshold is **0** (not the risk-free rate):
#         downside = excess_returns[excess_returns < 0]
#   - Annualization factor is sqrt(8760) ≈ 93.5949.
#   - Final value is rounded to 4 decimals via round(x, 4).
#   - All edge cases return EXACTLY 0.0 (never inf, never NaN):
#       len(equity_curve) < 2 → 0.0
#       returns empty after pct_change().dropna() → 0.0
#       no downside (all excess >= 0) → 0.0
#       downside.std() < 1e-10 → 0.0
#
# Tolerance on hand-calculated expected values is abs=1e-4 because the impl
# applies round(x, 4) before returning — asserting at 1e-6 would fail on any
# externally-computed expected differing by >1e-4 from the rounded output.


def _equity_from_returns(returns: list[float], initial: float = 1000.0) -> list[float]:
    """Build a curve whose pct_change() reproduces `returns` exactly."""
    curve = [initial]
    for r in returns:
        curve.append(curve[-1] * (1 + r))
    return curve


def test_sortino_asymmetric_returns():
    """
    Asymmetric returns with a small downside present.

    returns = [0.02, -0.005, 0.03, -0.01, 0.015, 0.025, -0.003, 0.018]

    Hand-calculation (rf = 0.05/8760 ≈ 5.7078e-6):
        excess     ≈ [0.0199943, -0.0050057, 0.0299943, -0.0100057,
                      0.0149943,  0.0249943, -0.0030057,  0.0179943]
        mean(excess) ≈ 0.0112443
        downside (excess < 0) = [-0.0050057, -0.0100057, -0.0030057]
            mean(downside) = -0.006006
            squared deviations = (0.001)² + (-0.004)² + (0.003)² = 2.6e-5
            std(downside, ddof=1) = sqrt(2.6e-5 / 2) ≈ 0.0036056
        sortino = (0.0112443 / 0.0036056) * sqrt(8760)
                ≈ 3.118 * 93.595
                ≈ 291.886
        round(sortino, 4) → 291.8855
    """
    returns = [0.02, -0.005, 0.03, -0.01, 0.015, 0.025, -0.003, 0.018]
    curve = _equity_from_returns(returns)

    expected = 291.8855
    assert compute_sortino(curve) == pytest.approx(expected, abs=1e-4)


def test_sortino_all_positive_returns_is_zero():
    """
    No downside present → impl returns 0.0 sentinel (NOT inf).
    See guard at metrics.py:57-58: `if len(downside_returns) == 0 ... return 0.0`.
    """
    returns = [0.01, 0.02, 0.015, 0.025, 0.03, 0.018, 0.022]
    curve = _equity_from_returns(returns)
    assert compute_sortino(curve) == 0.0


def test_sortino_all_negative_returns_is_signed():
    """
    All-negative returns: numerator is negative, denominator is positive,
    sortino is large-magnitude negative.

    returns = [-0.01, -0.02, -0.015, -0.005, -0.025]

    Hand-calculation:
        excess ≈ returns - 5.7078e-6 (negligible shift; all still < 0)
        mean(excess) ≈ -0.015006
        downside == excess (all negative)
            std(excess, ddof=1) ≈ 0.0079057  (computed from the 5 excess values)
        sortino ≈ (-0.015006 / 0.0079057) * sqrt(8760)
                ≈ -1.8982 * 93.595
                ≈ -177.652
        round(sortino, 4) → -177.6514
    """
    returns = [-0.01, -0.02, -0.015, -0.005, -0.025]
    curve = _equity_from_returns(returns)

    expected = -177.6514
    assert compute_sortino(curve) == pytest.approx(expected, abs=1e-4)


def test_sortino_single_observation_is_zero():
    """
    Single equity value → pct_change().dropna() is empty → 0.0 sentinel.
    See guards at metrics.py:46-47 (len < 2) and metrics.py:50-51 (empty).
    """
    assert compute_sortino([1000.0]) == 0.0


def test_sortino_exceeds_sharpe_when_upside_dominates():
    """
    When upside variance dominates total variance, downside-only std is much
    smaller than total std, so Sortino must exceed Sharpe by a wide margin.

    returns = [0.05, 0.04, -0.005, 0.06, -0.003, 0.045, -0.002, 0.055]

    Computed values (for documentation only — assertion uses a multiplicative
    inequality, not magic literals):
        sharpe  ≈ 99.36
        sortino ≈ 1837.82
        ratio   ≈ 18.5x

    Asserted property: sortino > sharpe * 2.0 (downside std is materially
    smaller than total std) AND sortino is finite (no inf/NaN).
    """
    returns = [0.05, 0.04, -0.005, 0.06, -0.003, 0.045, -0.002, 0.055]
    curve = _equity_from_returns(returns)

    sharpe = compute_sharpe(curve)
    sortino = compute_sortino(curve)

    assert np.isfinite(sortino), "Sortino should not be inf/NaN"
    assert sortino > sharpe * 2.0, (
        f"Expected sortino ({sortino}) > 2 × sharpe ({sharpe}) "
        f"because downside variance is much smaller than total variance"
    )


# ════════════════════════════════════════════════════════════════════════════
# Calmar ratio — external ground truth (Phase 7 Step 1 Ticket 7, finding 11)
# ════════════════════════════════════════════════════════════════════════════
#
# Documented convention from backtest/metrics.py:64-67:
#
#   calmar = round(annualized_return / max_drawdown, 4)
#
#   - Two PRE-COMPUTED float inputs in percentage scale (0-100), where
#     max_drawdown is the unsigned magnitude returned by compute_max_drawdown.
#   - max_drawdown <= 0 → returns 0.0 sentinel (no drawdown ⇒ no
#     risk-adjusted denominator).
#   - SIGN IS PRESERVED through the division: negative annualized_return
#     yields a negative Calmar (no implicit floor at 0).
#   - Output rounded to 4 decimals.
#   - No curve handling inside compute_calmar; annualization and drawdown
#     extraction live in compute_annualized_return and compute_max_drawdown.


def test_calmar_known_inputs():
    """40% annualized return / 20% max drawdown = 2.0 (pure formula test)."""
    assert compute_calmar(40.0, 20.0) == 2.0


def test_calmar_zero_drawdown_returns_zero_sentinel():
    """max_drawdown <= 0 → 0.0 sentinel (division-by-zero guard)."""
    assert compute_calmar(40.0, 0.0) == 0.0
    assert (
        compute_calmar(40.0, -5.0) == 0.0
    )  # negative dd should never be passed but the guard fires


def test_calmar_negative_annualized_return_is_negative():
    """Negative annualized return yields negative Calmar (no floor at 0)."""
    assert compute_calmar(-30.0, 15.0) == -2.0


def test_calmar_integration_with_helpers():
    """
    Full chain: equity curve → compute_max_drawdown → compute_annualized_return
    → compute_calmar. Verifies the wiring matches the hand-calculation.

    Construction (8760-row curve so annualization is identity):
        Phase 1 (rows 0..2000):    linear ramp 10000 → 12500   (peak)
        Phase 2 (rows 2000..3000): linear drop  12500 → 10000  (20% drawdown)
        Phase 3 (rows 3000..end):  linear ramp 10000 → 14000   (recovery)

    Hand-calculated outcomes:
        max_drawdown = (10000 - 12500) / 12500 * 100 = 20.0
        total_return = (14000 - 10000) / 10000 * 100 = 40.0
        annualized   = ((1.40) ^ (8760/8760) - 1) * 100 = 40.0
        calmar       = 40.0 / 20.0 = 2.0
    """
    n = 8760
    curve = np.zeros(n)
    curve[0:2001] = np.linspace(10000.0, 12500.0, 2001)
    curve[2000:3001] = np.linspace(12500.0, 10000.0, 1001)
    curve[3000:] = np.linspace(10000.0, 14000.0, n - 3000)
    curve_list = curve.tolist()

    max_dd = compute_max_drawdown(curve_list)
    total_ret = (curve_list[-1] - curve_list[0]) / curve_list[0] * 100
    ann_ret = compute_annualized_return(total_ret, n)
    calmar = compute_calmar(ann_ret, max_dd)

    assert max_dd == pytest.approx(20.0, abs=1e-4)
    assert ann_ret == pytest.approx(40.0, abs=1e-4)
    assert calmar == pytest.approx(2.0, abs=1e-4)
