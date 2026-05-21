import pandas as pd
import ta

from config.settings import (
    ATR_STOP_MULTIPLIER,
    FEATURE_WINDOWS,
    KELLY_FRACTION,
    KELLY_WIN_LOSS_RATIO,
    MAX_POSITION_PCT,
    RISK_REWARD_RATIO,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def kelly_fraction(
    up_probability: float,
    win_loss_ratio: float = KELLY_WIN_LOSS_RATIO,
) -> float:
    """
    Kelly Criterion: f* = (p*b - q) / b

    Rule 9: negative Kelly → 0, cap at 0.25, apply half-Kelly multiplier.
    Returns fraction in [0.0, 0.25 * KELLY_FRACTION].
    """
    if up_probability <= 0.5:
        return 0.0

    p = up_probability
    q = 1.0 - p
    b = win_loss_ratio

    raw_kelly = (p * b - q) / b
    capped = max(0.0, min(0.25, raw_kelly))
    return round(capped * KELLY_FRACTION, 6)


def risk_adjusted_size(
    portfolio_value: float,
    risk_score: float,
    up_probability: float = 0.5,
    win_loss_ratio: float = KELLY_WIN_LOSS_RATIO,
) -> dict:
    """
    Final position size = Kelly × risk_multiplier, capped at MAX_POSITION_PCT.

    risk_multiplier = 1 - risk_score/100 (high risk → smaller position).
    """
    if portfolio_value <= 0:
        return {
            "position_pct": 0.0,
            "position_usd": 0.0,
            "kelly_raw": 0.0,
            "risk_multiplier": 0.0,
            "rationale": "Invalid portfolio value",
        }

    kelly_raw = kelly_fraction(up_probability, win_loss_ratio)
    risk_multiplier = max(0.0, 1.0 - (risk_score / 100.0))
    adjusted_kelly = kelly_raw * risk_multiplier
    position_pct = min(adjusted_kelly, MAX_POSITION_PCT)
    position_usd = round(portfolio_value * position_pct, 2)

    if kelly_raw == 0.0:
        rationale = f"No position: up_prob={up_probability:.3f} ≤ 0.5 (Kelly=0)"
    elif risk_score >= 75:
        rationale = (
            f"Severely reduced: risk={risk_score:.1f}/100 (multiplier={risk_multiplier:.2f})"
        )
    elif position_pct == MAX_POSITION_PCT:
        rationale = (
            f"Capped at max {MAX_POSITION_PCT * 100:.0f}% "
            f"(Kelly={kelly_raw:.3f}, risk_mult={risk_multiplier:.2f})"
        )
    else:
        rationale = (
            f"Kelly={kelly_raw:.3f} × risk_mult={risk_multiplier:.2f} "
            f"= {position_pct * 100:.1f}% of portfolio"
        )

    return {
        "position_pct": round(position_pct, 6),
        "position_usd": position_usd,
        "kelly_raw": round(kelly_raw, 6),
        "risk_multiplier": round(risk_multiplier, 4),
        "rationale": rationale,
    }


def stop_loss_price(
    entry_price: float,
    candles: pd.DataFrame,
    multiplier: float = ATR_STOP_MULTIPLIER,
) -> float | None:
    """
    ATR-based stop loss: entry - (ATR × multiplier).
    Returns None if ATR cannot be computed.
    """
    if candles is None or candles.empty or len(candles) < FEATURE_WINDOWS["atr"] + 1:
        logger.debug("stop_loss_price: insufficient candles for ATR")
        return None

    try:
        atr_series = ta.volatility.AverageTrueRange(
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            window=FEATURE_WINDOWS["atr"],
        ).average_true_range()

        valid_atr = atr_series.dropna()
        if valid_atr.empty:
            return None

        current_atr = float(valid_atr.iloc[-1])
        stop = entry_price - (current_atr * multiplier)
        return round(max(0.0, stop), 8)

    except Exception as e:
        logger.warning(f"stop_loss_price computation failed: {e}")
        return None


def take_profit_price(
    entry_price: float,
    stop_loss: float | None,
    risk_reward_ratio: float = RISK_REWARD_RATIO,
) -> float | None:
    """
    Take profit = entry + (entry - stop_loss) × risk_reward_ratio.
    Returns None if inputs are invalid.
    """
    if stop_loss is None:
        return None
    if stop_loss >= entry_price:
        logger.warning(
            f"take_profit_price: stop_loss ({stop_loss}) >= entry ({entry_price}) — invalid"
        )
        return None

    risk_per_unit = entry_price - stop_loss
    return round(entry_price + (risk_per_unit * risk_reward_ratio), 8)


def full_position_plan(
    asset: str,
    risk_result: dict,
    portfolio_value: float,
    candles: pd.DataFrame = None,
) -> dict:
    """
    Convenience wrapper — combines all position sizing into one call.
    Returns complete plan: size, stop loss, take profit, entry price.
    """
    risk_score = risk_result.get("score", 100.0)
    trend = risk_result.get("trend") or {}
    up_probability = trend.get("up_probability", 0.5)

    position = risk_adjusted_size(
        portfolio_value=portfolio_value,
        risk_score=risk_score,
        up_probability=up_probability,
    )

    entry_price = None
    if candles is not None and not candles.empty:
        entry_price = float(candles["close"].iloc[-1])

    sl = stop_loss_price(entry_price, candles) if entry_price else None
    tp = take_profit_price(entry_price, sl) if sl else None

    return {
        "asset": asset,
        "risk_score": risk_score,
        "recommendation": risk_result.get("recommendation", "HOLD"),
        "position": position,
        "stop_loss": sl,
        "take_profit": tp,
        "entry_price": entry_price,
    }
