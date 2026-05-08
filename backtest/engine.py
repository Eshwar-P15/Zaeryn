import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from utils.logger import get_logger
from config.settings import (
    BACKTEST_COMMISSION_PCT,
    BACKTEST_INITIAL_CAPITAL,
    BACKTEST_POSITION_PCT,
    BACKTEST_STOP_LOSS_PCT,
    BACKTEST_TAKE_PROFIT_PCT,
    INDICATOR_WARMUP,
)
from data.storage import load_candles, init_db
from data.cleaner import clean_ohlcv, normalize_price_data
from models.features import compute_technical_indicators
from backtest.strategies import BaseStrategy, Signal

logger = get_logger(__name__)


@dataclass
class TradeRecord:
    asset:          str
    strategy:       str
    entry_time:     object
    entry_price:    float
    exit_time:      object
    exit_price:     float
    position_usd:   float
    pnl_usd:        float
    pnl_pct:        float
    exit_reason:    str
    signal_reason:  str

    @property
    def is_winner(self) -> bool:
        return self.pnl_usd > 0

    def to_dict(self) -> dict:
        entry_t = self.entry_time
        exit_t  = self.exit_time
        return {
            "asset":         self.asset,
            "strategy":      self.strategy,
            "entry_time":    entry_t.isoformat() if hasattr(entry_t, "isoformat") else str(entry_t),
            "entry_price":   self.entry_price,
            "exit_time":     exit_t.isoformat()  if hasattr(exit_t,  "isoformat") else str(exit_t),
            "exit_price":    self.exit_price,
            "position_usd":  self.position_usd,
            "pnl_usd":       round(self.pnl_usd,  4),
            "pnl_pct":       round(self.pnl_pct,  4),
            "exit_reason":   self.exit_reason,
            "signal_reason": self.signal_reason,
            "is_winner":     self.is_winner,
        }


@dataclass
class BacktestResult:
    strategy_name:    str
    asset:            str
    granularity:      str
    start_date:       object
    end_date:         object
    initial_capital:  float
    final_capital:    float
    trades:           list = field(default_factory=list)
    equity_curve:     list = field(default_factory=list)
    timestamps:       list = field(default_factory=list)

    @property
    def total_return_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return (self.final_capital - self.initial_capital) / self.initial_capital * 100

    def to_dict(self) -> dict:
        sd = self.start_date
        ed = self.end_date
        return {
            "strategy_name":    self.strategy_name,
            "asset":            self.asset,
            "granularity":      self.granularity,
            "start_date":       sd.isoformat() if hasattr(sd, "isoformat") else str(sd),
            "end_date":         ed.isoformat() if hasattr(ed, "isoformat") else str(ed),
            "initial_capital":  self.initial_capital,
            "final_capital":    round(self.final_capital, 2),
            "total_return_pct": round(self.total_return_pct, 4),
            "trades":           [t.to_dict() for t in self.trades],
            "equity_curve":     [round(v, 4) for v in self.equity_curve],
            "timestamps":       self.timestamps,
        }


class BacktestEngine:
    def __init__(
        self,
        strategy:        BaseStrategy,
        initial_capital: float = BACKTEST_INITIAL_CAPITAL,
        commission_pct:  float = BACKTEST_COMMISSION_PCT,
        position_pct:    float = BACKTEST_POSITION_PCT,
        stop_loss_pct:   float = BACKTEST_STOP_LOSS_PCT,
        take_profit_pct: float = BACKTEST_TAKE_PROFIT_PCT,
    ):
        self.strategy        = strategy
        self.initial_capital = initial_capital
        self.commission_pct  = commission_pct
        self.position_pct    = position_pct
        self.stop_loss_pct   = stop_loss_pct
        self.take_profit_pct = take_profit_pct

    def run(
        self,
        asset:       str,
        granularity: str = "1h",
        days_back:   int = 90,
        conn         = None,
    ) -> BacktestResult:
        logger.info(
            f"Backtesting [{self.strategy.name}] on {asset} ({days_back}d, {granularity})"
        )

        close_conn = False
        if conn is None:
            conn = init_db()
            close_conn = True

        try:
            raw = load_candles(asset, granularity, days_back=days_back, conn=conn)
        finally:
            if close_conn:
                conn.close()

        if raw.empty or len(raw) < INDICATOR_WARMUP + 10:
            logger.warning(
                f"[{asset}] Insufficient candles for backtest: {len(raw)} rows"
            )
            return BacktestResult(
                strategy_name=self.strategy.name,
                asset=asset,
                granularity=granularity,
                start_date=datetime.now(timezone.utc),
                end_date=datetime.now(timezone.utc),
                initial_capital=self.initial_capital,
                final_capital=self.initial_capital,
            )

        df = clean_ohlcv(raw)
        df = normalize_price_data(df)
        df = compute_technical_indicators(df)
        df = df.reset_index(drop=True)

        cash     = self.initial_capital
        position = None
        trades:       list[TradeRecord] = []
        equity_curve: list[float]       = []
        timestamps:   list[str]         = []

        for i in range(INDICATOR_WARMUP, len(df)):
            row          = df.iloc[i]
            candle_high  = float(row["high"])
            candle_low   = float(row["low"])
            candle_close = float(row["close"])
            candle_time  = row["timestamp"]

            # Check stop loss / take profit (Rule 2 — check low first)
            if position is not None:
                exit_price  = None
                exit_reason = None

                if candle_low <= position["stop_loss"]:
                    exit_price  = position["stop_loss"]
                    exit_reason = "STOP_LOSS"
                elif candle_high >= position["take_profit"]:
                    exit_price  = position["take_profit"]
                    exit_reason = "TAKE_PROFIT"

                if exit_price is not None:
                    trade, cash = self._close_position(
                        position, exit_price, exit_reason, candle_time, cash
                    )
                    trades.append(trade)
                    position = None

            # Generate signal (Rule 1 — only data up to current candle)
            window = df.iloc[:i + 1]
            signal = self.strategy.generate_signal(window)

            if signal.action == "BUY" and position is None:
                position, cash = self._open_position(
                    asset, signal, candle_close, candle_time, cash
                )
            elif signal.action == "SELL" and position is not None:
                trade, cash = self._close_position(
                    position, candle_close, "SIGNAL", candle_time, cash
                )
                trades.append(trade)
                position = None

            # Equity curve (Rule 6 — every candle)
            if position is not None:
                unrealized = (
                    (candle_close - position["entry_price"])
                    / position["entry_price"]
                    * position["position_usd"]
                )
                portfolio_value = cash + position["position_usd"] + unrealized
            else:
                portfolio_value = cash

            equity_curve.append(portfolio_value)
            ts = candle_time
            timestamps.append(ts.isoformat() if hasattr(ts, "isoformat") else str(ts))

        # Close any open position at end of data
        if position is not None and len(df) > INDICATOR_WARMUP:
            last_close = float(df.iloc[-1]["close"])
            last_time  = df.iloc[-1]["timestamp"]
            trade, cash = self._close_position(
                position, last_close, "END_OF_DATA", last_time, cash
            )
            trades.append(trade)
            if equity_curve:
                equity_curve[-1] = cash

        final_capital = equity_curve[-1] if equity_curve else self.initial_capital

        result = BacktestResult(
            strategy_name=self.strategy.name,
            asset=asset,
            granularity=granularity,
            start_date=df.iloc[INDICATOR_WARMUP]["timestamp"],
            end_date=df.iloc[-1]["timestamp"],
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            trades=trades,
            equity_curve=equity_curve,
            timestamps=timestamps,
        )

        logger.info(
            f"[{self.strategy.name}] {asset}: "
            f"{len(trades)} trades | "
            f"return={result.total_return_pct:.2f}% | "
            f"final=${final_capital:.2f}"
        )
        return result

    def _open_position(
        self,
        asset:       str,
        signal:      Signal,
        entry_price: float,
        entry_time,
        cash:        float,
    ) -> tuple[dict, float]:
        position_usd = cash * self.position_pct
        entry_cost   = position_usd * self.commission_pct
        cash        -= (position_usd + entry_cost)

        position = {
            "asset":         asset,
            "entry_price":   entry_price,
            "entry_time":    entry_time,
            "position_usd":  position_usd,
            "stop_loss":     entry_price * (1 - self.stop_loss_pct),
            "take_profit":   entry_price * (1 + self.take_profit_pct),
            "signal_reason": signal.reason,
            "confidence":    signal.confidence,
        }

        logger.debug(
            f"OPEN  {asset} @ ${entry_price:.6f} | "
            f"size=${position_usd:.2f} | "
            f"stop=${position['stop_loss']:.6f} | target=${position['take_profit']:.6f}"
        )
        return position, cash

    def _close_position(
        self,
        position:    dict,
        exit_price:  float,
        exit_reason: str,
        exit_time,
        cash:        float,
    ) -> tuple[TradeRecord, float]:
        position_usd    = position["position_usd"]
        price_return    = (exit_price - position["entry_price"]) / position["entry_price"]
        gross_exit_val  = position_usd * (1 + price_return)
        exit_commission = gross_exit_val * self.commission_pct
        net_exit_val    = gross_exit_val - exit_commission

        pnl_usd = net_exit_val - position_usd
        pnl_pct = pnl_usd / position_usd * 100

        cash += net_exit_val

        record = TradeRecord(
            asset         = position["asset"],
            strategy      = self.strategy.name,
            entry_time    = position["entry_time"],
            entry_price   = position["entry_price"],
            exit_time     = exit_time,
            exit_price    = exit_price,
            position_usd  = position_usd,
            pnl_usd       = round(pnl_usd, 4),
            pnl_pct       = round(pnl_pct, 4),
            exit_reason   = exit_reason,
            signal_reason = position["signal_reason"],
        )

        logger.debug(
            f"CLOSE {position['asset']} @ ${exit_price:.6f} | "
            f"reason={exit_reason} | "
            f"pnl=${pnl_usd:.2f} ({pnl_pct:.2f}%)"
        )
        return record, cash
