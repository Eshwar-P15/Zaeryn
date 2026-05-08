import os
import json
import numpy as np
import pandas as pd
from datetime import datetime

from utils.logger import get_logger
from config.settings import BACKTEST_REPORTS_DIR, BACKTEST_INITIAL_CAPITAL
from backtest.engine import BacktestResult
from backtest.metrics import compute_metrics

logger = get_logger(__name__)


def print_summary(result: BacktestResult, metrics: dict) -> None:
    W = 55
    print(f"\n{'─'*W}")
    print(f"  {metrics['strategy']} — {metrics['asset']}")
    print(f"  {metrics['start_date'][:10]} → {metrics['end_date'][:10]}")
    print(f"{'─'*W}")
    print(f"  Capital:      ${metrics['initial_capital']:>10,.2f} → ${metrics['final_capital']:>10,.2f}")
    print(f"  Total Return: {metrics['total_return_pct']:>+10.2f}%")
    print(f"  Ann. Return:  {metrics['annualized_return_pct']:>+10.2f}%")
    print(f"{'─'*W}")
    print(f"  Trades:       {metrics['total_trades']:>10}")
    print(f"  Win Rate:     {metrics['win_rate_pct']:>10.1f}%")
    print(f"  Profit Factor:{metrics['profit_factor']:>10.3f}")
    print(f"  Avg Duration: {metrics['avg_duration_hours']:>10.1f}h")
    print(f"{'─'*W}")
    print(f"  Max Drawdown: {metrics['max_drawdown_pct']:>10.2f}%")
    print(f"  Sharpe:       {metrics['sharpe_ratio']:>10.4f}")
    print(f"  Sortino:      {metrics['sortino_ratio']:>10.4f}")
    print(f"  Calmar:       {metrics['calmar_ratio']:>10.4f}")
    if "warning" in metrics:
        print(f"  ⚠  {metrics['warning']}")
    print(f"{'─'*W}\n")


def save_report(result: BacktestResult, metrics: dict) -> str:
    os.makedirs(BACKTEST_REPORTS_DIR, exist_ok=True)

    timestamp  = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_strat = metrics["strategy"].replace(" ", "_")
    filename   = f"{safe_strat}_{metrics['asset']}_{timestamp}.json"
    filepath   = os.path.join(BACKTEST_REPORTS_DIR, filename)

    payload = {
        "metadata": metrics,
        "result":   result.to_dict(),
    }

    with open(filepath, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    logger.info(f"Report saved: {filepath}")
    return filepath


def compare_strategies(
    results: list[tuple[BacktestResult, dict]],
    include_benchmark: bool = True,
) -> pd.DataFrame:
    rows = []

    for result, metrics in results:
        rows.append({
            "Strategy":      metrics["strategy"],
            "Asset":         metrics["asset"],
            "Return %":      round(metrics["total_return_pct"],      2),
            "Ann. Return %": round(metrics["annualized_return_pct"],  2),
            "Sharpe":        round(metrics["sharpe_ratio"],           4),
            "Sortino":       round(metrics["sortino_ratio"],          4),
            "Max DD %":      round(metrics["max_drawdown_pct"],       2),
            "Win Rate %":    round(metrics["win_rate_pct"],           1),
            "Trades":        metrics["total_trades"],
            "Profit Factor": round(metrics["profit_factor"],          3),
            "W/L Ratio":     round(metrics.get("win_loss_ratio", 1.5), 3),
            "Warning":       metrics.get("warning", ""),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.sort_values("Sharpe", ascending=False).reset_index(drop=True)
    return df


def print_comparison_table(comparison_df: pd.DataFrame) -> None:
    if comparison_df.empty:
        print("No results to compare.")
        return

    try:
        from tabulate import tabulate
        display_df = comparison_df.copy()
        if display_df["Warning"].eq("").all():
            display_df = display_df.drop(columns=["Warning"])
        print(tabulate(display_df, headers="keys", tablefmt="rounded_grid", showindex=False))
    except ImportError:
        print(comparison_df.to_string(index=False))
