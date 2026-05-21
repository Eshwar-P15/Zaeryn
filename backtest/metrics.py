from datetime import datetime

import numpy as np
import pandas as pd

from backtest.engine import BacktestResult, TradeRecord
from config.settings import (
    BACKTEST_ANNUALIZATION,
    MIN_TRADES_FOR_METRICS,
    RISK_FREE_RATE_ANNUAL,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def compute_max_drawdown(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0

    curve = np.array(equity_curve, dtype=float)
    peak = np.maximum.accumulate(curve)

    with np.errstate(divide="ignore", invalid="ignore"):
        drawdowns = np.where(peak > 0, (curve - peak) / peak, 0.0)

    return float(abs(drawdowns.min()) * 100)


def compute_sharpe(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0

    returns = pd.Series(equity_curve).pct_change().dropna()
    if returns.empty or returns.std() == 0:
        return 0.0

    risk_free_per_candle = RISK_FREE_RATE_ANNUAL / BACKTEST_ANNUALIZATION
    excess_returns = returns - risk_free_per_candle

    sharpe = (excess_returns.mean() / excess_returns.std()) * np.sqrt(BACKTEST_ANNUALIZATION)
    return round(float(sharpe), 4)


def compute_sortino(equity_curve: list[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0

    returns = pd.Series(equity_curve).pct_change().dropna()
    if returns.empty:
        return 0.0

    risk_free_per_candle = RISK_FREE_RATE_ANNUAL / BACKTEST_ANNUALIZATION
    excess_returns = returns - risk_free_per_candle
    downside_returns = excess_returns[excess_returns < 0]

    if len(downside_returns) == 0 or downside_returns.std() < 1e-10:
        return 0.0

    sortino = (excess_returns.mean() / downside_returns.std()) * np.sqrt(BACKTEST_ANNUALIZATION)
    return round(float(sortino), 4)


def compute_calmar(annualized_return: float, max_drawdown: float) -> float:
    if max_drawdown <= 0:
        return 0.0
    return round(annualized_return / max_drawdown, 4)


def compute_annualized_return(total_return_pct: float, n_candles: int) -> float:
    if n_candles <= 0:
        return 0.0

    total_return_decimal = total_return_pct / 100.0
    annualized = ((1 + total_return_decimal) ** (BACKTEST_ANNUALIZATION / n_candles) - 1) * 100.0
    return round(annualized, 4)


def compute_win_loss_ratio(trades: list[TradeRecord]) -> float:
    winners = [t.pnl_pct for t in trades if t.pnl_pct > 0]
    losers = [abs(t.pnl_pct) for t in trades if t.pnl_pct < 0]

    if not winners or not losers:
        return 1.5

    avg_win = np.mean(winners)
    avg_loss = np.mean(losers)

    if avg_loss == 0:
        return float("inf")

    return round(avg_win / avg_loss, 4)


def compute_metrics(result: BacktestResult) -> dict:
    trades = result.trades
    n_candles = len(result.equity_curve)

    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t.is_winner)
    losing_trades = total_trades - winning_trades

    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    winners_pnl = [t.pnl_usd for t in trades if t.is_winner]
    losers_pnl = [t.pnl_usd for t in trades if not t.is_winner]

    avg_win = float(np.mean(winners_pnl)) if winners_pnl else 0.0
    avg_loss = float(np.mean(losers_pnl)) if losers_pnl else 0.0

    gross_profit = sum(winners_pnl)
    gross_loss = abs(sum(losers_pnl))
    if gross_loss == 0:
        profit_factor = float("inf") if gross_profit > 0 else 0.0
    elif gross_profit == 0:
        profit_factor = 0.0
    else:
        profit_factor = gross_profit / gross_loss

    total_return = result.total_return_pct
    annualized_ret = compute_annualized_return(total_return, n_candles)

    best_trade = max((t.pnl_pct for t in trades), default=0.0)
    worst_trade = min((t.pnl_pct for t in trades), default=0.0)

    max_dd = compute_max_drawdown(result.equity_curve)
    sharpe = compute_sharpe(result.equity_curve)
    sortino = compute_sortino(result.equity_curve)
    calmar = compute_calmar(annualized_ret, max_dd)

    if trades:
        durations = []
        for t in trades:
            try:
                entry = (
                    t.entry_time
                    if isinstance(t.entry_time, datetime)
                    else datetime.fromisoformat(str(t.entry_time))
                )
                exit_ = (
                    t.exit_time
                    if isinstance(t.exit_time, datetime)
                    else datetime.fromisoformat(str(t.exit_time))
                )
                durations.append((exit_ - entry).total_seconds() / 3600)
            except Exception:
                continue
        avg_duration_h = float(np.mean(durations)) if durations else 0.0
    else:
        avg_duration_h = 0.0

    exit_reasons = {}
    for t in trades:
        exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1

    win_loss_ratio = compute_win_loss_ratio(trades)

    metrics = {
        "strategy": result.strategy_name,
        "asset": result.asset,
        "start_date": result.start_date.isoformat()
        if hasattr(result.start_date, "isoformat")
        else str(result.start_date),
        "end_date": result.end_date.isoformat()
        if hasattr(result.end_date, "isoformat")
        else str(result.end_date),
        "n_candles": n_candles,
        "initial_capital": result.initial_capital,
        "final_capital": round(result.final_capital, 2),
        "total_return_pct": round(total_return, 4),
        "annualized_return_pct": round(annualized_ret, 4),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate_pct": round(win_rate, 2),
        "avg_win_usd": round(avg_win, 4),
        "avg_loss_usd": round(avg_loss, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        "best_trade_pct": round(best_trade, 4),
        "worst_trade_pct": round(worst_trade, 4),
        "avg_duration_hours": round(avg_duration_h, 2),
        "exit_reasons": exit_reasons,
        "win_loss_ratio": win_loss_ratio,
        "max_drawdown_pct": round(max_dd, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "calmar_ratio": round(calmar, 4),
    }

    if total_trades < MIN_TRADES_FOR_METRICS:
        metrics["warning"] = (
            f"Only {total_trades} trades — metrics are statistically unreliable. "
            f"Run with more days or a more active strategy."
        )

    return metrics
