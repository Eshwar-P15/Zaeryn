"""Pinning tests for the backtest engine's signal-to-fill bar contract.

P7.S2.T5 audit found that ``BacktestEngine.run`` fills BUY/SELL
signals at the SAME bar's close that the signal was computed on,
which is an IMPOSSIBLE FILL (the close is observable only after
the bar has closed). These tests:

- Tests A and B pin the *current* contract so any future change
  is intentional and reviewed.
- Test C locks the *correct* contract the T6 remediation must
  satisfy. It is marked ``xfail(strict=True)``: it fails today,
  and when the fix lands, the unexpected pass forces the xfail
  marker to be removed deliberately.

See ``docs/data_integrity_audit.md`` → "Backtest engine fill-time
(T5)" for the full audit context.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestEngine
from backtest.strategies import BaseStrategy, Signal
from config.settings import (
    BACKTEST_COMMISSION_PCT,
    BACKTEST_INITIAL_CAPITAL,
    BACKTEST_POSITION_PCT,
    INDICATOR_WARMUP,
)


def _flat_candles(n: int = 80, base_price: float = 100.0) -> pd.DataFrame:
    """Deterministic monotone-up candles where open==high==low==close.

    With high==low==close, neither stop-loss nor take-profit can fire
    (no intra-bar excursion exists). The only way to exit a position
    is via a SIGNAL or END_OF_DATA, which isolates the audit target
    (signal-to-fill timing) from stop-trip side effects.

    Close at bar i equals ``base_price + i``, which is also open[i].
    Open[i+1] = base_price + i + 1, distinct from close[i] — this is
    what lets test C distinguish "fill at bar S close" from "fill at
    bar S+1 open".
    """
    closes = base_price + np.arange(n, dtype=float)
    timestamps = pd.date_range(start=datetime(2024, 1, 1, tzinfo=UTC), periods=n, freq="1h")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": np.full(n, 1000.0),
        }
    )


class _ScriptedSignalStrategy(BaseStrategy):
    """Returns BUY on the k-th call (0-indexed), SELL on the m-th call,
    HOLD otherwise. ``BacktestEngine.run`` iterates
    ``for i in range(INDICATOR_WARMUP, len(df))``, so call index k
    corresponds to bar ``i = INDICATOR_WARMUP + k``.
    """

    name = "ScriptedSignal"

    def __init__(self, buy_call_index: int, sell_call_index: int):
        self.buy_call_index = buy_call_index
        self.sell_call_index = sell_call_index
        self._call_count = -1

    def generate_signal(self, window: pd.DataFrame) -> Signal:
        self._call_count += 1
        if self._call_count == self.buy_call_index:
            return Signal("BUY", 1.0, "scripted buy")
        if self._call_count == self.sell_call_index:
            return Signal("SELL", 1.0, "scripted sell")
        return Signal("HOLD", 0.0, "scripted hold")


def _run_engine(df: pd.DataFrame, strategy: BaseStrategy):
    engine = BacktestEngine(strategy=strategy)
    with (
        patch("backtest.engine.load_candles", return_value=df),
        patch("backtest.engine.clean_ohlcv", side_effect=lambda x: x),
        patch("backtest.engine.normalize_price_data", side_effect=lambda x: x),
        patch("backtest.engine.compute_technical_indicators", side_effect=lambda x: x),
    ):
        return engine.run("BTC-USD")


# --- Test A: signal-to-fill bar offset (current contract) --------------------


def test_signal_fill_at_same_bar_close_current_contract():
    """Current contract: BUY at signal bar i fills at df.iloc[i]['close'].

    Pinned here as the audited status quo (T5 verdict: IMPOSSIBLE FILL,
    S5). The companion xfail test below locks the correct contract for
    the T6 remediation.
    """
    df = _flat_candles(n=80)
    signal_bar = INDICATOR_WARMUP + 5  # bar 65
    buy_call = 5  # 6th call (0-indexed)

    strat = _ScriptedSignalStrategy(
        buy_call_index=buy_call,
        sell_call_index=10_000,  # never sells via signal
    )
    result = _run_engine(df, strat)

    # The BUY opens a position that runs to end-of-data (no SELL ever
    # fires; flat OHLC means no stop/TP can trip).
    assert (
        len(result.trades) == 1
    ), f"expected exactly one trade (BUY held to EOD); got {len(result.trades)}"
    trade = result.trades[0]
    assert trade.exit_reason == "END_OF_DATA"

    expected_entry_price = float(df.iloc[signal_bar]["close"])
    expected_entry_time = df.iloc[signal_bar]["timestamp"]

    assert trade.entry_price == expected_entry_price, (
        "Current T5 contract: BUY fills at the SIGNAL bar's close. "
        f"Expected entry_price={expected_entry_price} "
        f"(df.iloc[{signal_bar}]['close']), got {trade.entry_price}."
    )
    assert trade.entry_time == expected_entry_time


# --- Test B: equity-curve mark-to-market frame --------------------------------


def test_equity_curve_marks_to_market_at_each_bar_close():
    """equity_curve[k] uses df.iloc[INDICATOR_WARMUP + k]['close']
    for the mark-to-market value at that bar.

    Expected portfolio value at any post-entry bar is hand-derived
    from the entry-price / current-close ratio using the deterministic
    flat-OHLC fixture.
    """
    df = _flat_candles(n=80)
    signal_bar = INDICATOR_WARMUP + 5  # bar 65
    buy_call = 5

    strat = _ScriptedSignalStrategy(buy_call_index=buy_call, sell_call_index=10_000)
    result = _run_engine(df, strat)

    entry_idx_in_curve = signal_bar - INDICATOR_WARMUP  # 5

    entry_price = float(df.iloc[signal_bar]["close"])
    position_usd = BACKTEST_INITIAL_CAPITAL * BACKTEST_POSITION_PCT
    entry_commission = position_usd * BACKTEST_COMMISSION_PCT
    cash_after_entry = BACKTEST_INITIAL_CAPITAL - position_usd - entry_commission

    # Sample three bars after entry, well before the final bar where
    # engine.py:216 rewrites equity_curve[-1] = cash after END_OF_DATA.
    for k_offset in (1, 2, 3):
        bar_idx = signal_bar + k_offset
        assert bar_idx < len(df) - 1, "test fixture too short — last bar excluded"

        mark_close = float(df.iloc[bar_idx]["close"])
        unrealized = (mark_close - entry_price) / entry_price * position_usd
        expected_pv = cash_after_entry + position_usd + unrealized

        actual_pv = result.equity_curve[entry_idx_in_curve + k_offset]
        assert abs(actual_pv - expected_pv) < 1e-6, (
            f"bar {bar_idx}: expected mark-to-market {expected_pv}, "
            f"got {actual_pv}. The equity-curve frame may have drifted "
            f"away from per-bar close mark-to-market."
        )


# --- Test C: correct contract (xfail; locks T6 remediation target) -----------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "T5 audit (P7.S2.T5) found S5 IMPOSSIBLE FILL: BacktestEngine.run "
        "fills at the SAME bar's close that the signal was computed on. "
        "This test locks the CORRECT contract (fill at bar S+1's open) "
        "that the T6 remediation must satisfy. When T6 lands, this test "
        "will start passing and strict=True will force the xfail marker "
        "to be removed deliberately. Until then, expected-fail is the "
        "audited state."
    ),
)
def test_buy_fills_at_next_bar_open_correct_contract():
    df = _flat_candles(n=80)
    signal_bar = INDICATOR_WARMUP + 5  # bar 65
    buy_call = 5

    strat = _ScriptedSignalStrategy(buy_call_index=buy_call, sell_call_index=10_000)
    result = _run_engine(df, strat)

    assert len(result.trades) == 1
    trade = result.trades[0]

    expected_entry_price = float(df.iloc[signal_bar + 1]["open"])
    expected_entry_time = df.iloc[signal_bar + 1]["timestamp"]

    assert trade.entry_price == expected_entry_price, (
        "Correct contract: BUY fills at bar S+1's open. "
        f"Expected entry_price={expected_entry_price} "
        f"(df.iloc[{signal_bar + 1}]['open']), got {trade.entry_price}."
    )
    assert trade.entry_time == expected_entry_time
