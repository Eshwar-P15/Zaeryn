from datetime import UTC, datetime
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from config.settings import (
    ALERT_RISK_EXTREME,
    KELLY_FRACTION,
    MAX_POSITION_PCT,
    RECOMMEND_HOLD,
    RECOMMEND_REDUCE,
    RECOMMEND_TRADE,
    RISK_REWARD_RATIO,
)
from risk.alerts import check_alerts
from risk.position_sizer import (
    kelly_fraction,
    risk_adjusted_size,
    stop_loss_price,
    take_profit_price,
)
from risk.scorer import (
    _compute_momentum_component,
    _compute_sentiment_component,
    _redistribute_weights,
    compute_risk_score,
    recommendation,
    risk_label,
)

# -- Synthetic helpers ---------------------------------------------------------


def make_candles(n: int = 100, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)
    prices = 40000.0 * np.exp(np.cumsum(np.random.normal(0, 0.02, n)))
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
    return df


# -- risk_label ----------------------------------------------------------------


def test_risk_label_low():
    assert risk_label(0) == "LOW"
    assert risk_label(10) == "LOW"
    assert risk_label(24.9) == "LOW"


def test_risk_label_moderate():
    assert risk_label(25) == "MODERATE"
    assert risk_label(40) == "MODERATE"
    assert risk_label(49) == "MODERATE"


def test_risk_label_high():
    assert risk_label(50) == "HIGH"
    assert risk_label(60) == "HIGH"
    assert risk_label(74) == "HIGH"


def test_risk_label_extreme():
    assert risk_label(75) == "EXTREME"
    assert risk_label(90) == "EXTREME"
    assert risk_label(100) == "EXTREME"


# -- recommendation ------------------------------------------------------------


def test_recommendation_avoid():
    assert recommendation(RECOMMEND_REDUCE + 1, None) == "AVOID"
    assert recommendation(100, None) == "AVOID"


def test_recommendation_reduce():
    assert recommendation(RECOMMEND_HOLD + 1, None) == "REDUCE"
    assert recommendation(RECOMMEND_REDUCE - 1, None) == "REDUCE"


def test_recommendation_hold_high_risk():
    assert recommendation(RECOMMEND_TRADE + 1, None) == "HOLD"


def test_recommendation_hold_uncertain_trend():
    trend = {"direction": "UNCERTAIN", "confidence": 0.1}
    assert recommendation(RECOMMEND_TRADE - 1, trend) == "HOLD"


def test_recommendation_trade():
    trend = {"direction": "UP", "confidence": 0.4}
    assert recommendation(RECOMMEND_TRADE - 1, trend) == "TRADE"


# -- weight redistribution -----------------------------------------------------


def test_redistribute_all_available():
    components = {
        "volatility": (0.5, 1.0),
        "trend_uncertainty": (0.4, 1.0),
        "sentiment": (0.3, 1.0),
        "price_momentum": (0.2, 1.0),
        "market_regime": (0.1, 1.0),
    }
    weights = _redistribute_weights(components)
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_redistribute_missing_ml():
    components = {
        "volatility": (None, 0.0),
        "trend_uncertainty": (None, 0.0),
        "sentiment": (0.5, 0.8),
        "price_momentum": (0.3, 1.0),
        "market_regime": (0.2, 1.0),
    }
    weights = _redistribute_weights(components)
    assert "volatility" not in weights
    assert "trend_uncertainty" not in weights
    assert "sentiment" in weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_redistribute_all_missing():
    components = {
        k: (None, 0.0)
        for k in ["volatility", "trend_uncertainty", "sentiment", "price_momentum", "market_regime"]
    }
    assert _redistribute_weights(components) == {}


# -- sentiment component -------------------------------------------------------


def test_sentiment_component_bullish():
    with patch("risk.scorer.load_cached_sentiment") as mock:
        mock.return_value = {"score": 1.0, "confidence": 0.9}
        risk, conf = _compute_sentiment_component("BTC-USD")
    assert risk == pytest.approx(0.0, abs=0.01)
    assert conf == pytest.approx(0.9, abs=0.01)


def test_sentiment_component_bearish():
    with patch("risk.scorer.load_cached_sentiment") as mock:
        mock.return_value = {"score": -1.0, "confidence": 0.8}
        risk, conf = _compute_sentiment_component("BTC-USD")
    assert risk == pytest.approx(1.0, abs=0.01)


def test_sentiment_component_neutral():
    with patch("risk.scorer.load_cached_sentiment") as mock:
        mock.return_value = {"score": 0.0, "confidence": 0.5}
        risk, conf = _compute_sentiment_component("BTC-USD")
    assert risk == pytest.approx(0.5, abs=0.01)


def test_sentiment_component_cache_miss_api_down():
    with (
        patch("risk.scorer.load_cached_sentiment", return_value=None),
        patch("risk.scorer.get_or_fetch_sentiment", side_effect=Exception("API down")),
    ):
        risk, conf = _compute_sentiment_component("BTC-USD")
    assert risk == 0.5
    assert conf == 0.0


# -- momentum component --------------------------------------------------------


def test_momentum_rsi_neutral():
    df = make_candles(100)
    with patch("risk.scorer._extract_rsi", return_value=50.0):
        risk, conf = _compute_momentum_component(df)
    assert risk == pytest.approx(0.0, abs=0.01)


def test_momentum_rsi_overbought():
    df = make_candles(100)
    with patch("risk.scorer._extract_rsi", return_value=80.0):
        risk, conf = _compute_momentum_component(df)
    assert risk == pytest.approx(0.6, abs=0.01)


def test_momentum_rsi_oversold():
    df = make_candles(100)
    with patch("risk.scorer._extract_rsi", return_value=20.0):
        risk, conf = _compute_momentum_component(df)
    assert risk == pytest.approx(0.6, abs=0.01)


def test_momentum_rsi_unavailable():
    risk, conf = _compute_momentum_component(make_candles(5))
    assert risk == 0.0
    assert conf == 0.0


# -- Kelly Criterion -----------------------------------------------------------


def test_kelly_at_coin_flip():
    assert kelly_fraction(0.5) == 0.0


def test_kelly_below_fifty():
    assert kelly_fraction(0.4) == 0.0
    assert kelly_fraction(0.0) == 0.0


def test_kelly_strong_edge():
    k = kelly_fraction(0.65, win_loss_ratio=1.5)
    assert k > 0.0
    assert k <= 0.25 * KELLY_FRACTION


def test_kelly_never_exceeds_cap():
    max_allowed = 0.25 * KELLY_FRACTION
    for up_prob in [0.6, 0.7, 0.8, 0.9, 0.99]:
        k = kelly_fraction(up_prob, win_loss_ratio=10.0)
        assert k <= max_allowed + 1e-9, f"Kelly {k} exceeds max {max_allowed} at up_prob={up_prob}"


# -- risk_adjusted_size --------------------------------------------------------


def test_position_zero_at_coin_flip():
    result = risk_adjusted_size(10000.0, risk_score=30.0, up_probability=0.5)
    assert result["position_pct"] == 0.0
    assert result["position_usd"] == 0.0


def test_position_capped_at_max():
    result = risk_adjusted_size(10000.0, risk_score=0.0, up_probability=0.99)
    assert result["position_pct"] <= MAX_POSITION_PCT + 1e-9


def test_position_reduced_by_high_risk():
    low = risk_adjusted_size(10000.0, risk_score=10.0, up_probability=0.65)
    high = risk_adjusted_size(10000.0, risk_score=80.0, up_probability=0.65)
    assert low["position_pct"] > high["position_pct"]


def test_position_zero_portfolio():
    result = risk_adjusted_size(0.0, risk_score=20.0, up_probability=0.65)
    assert result["position_usd"] == 0.0


def test_position_zero_at_extreme_risk():
    result = risk_adjusted_size(10000.0, risk_score=100.0, up_probability=0.8)
    assert result["position_pct"] == 0.0
    assert result["risk_multiplier"] == 0.0


# -- stop loss / take profit ---------------------------------------------------


def test_stop_loss_below_entry():
    df = make_candles(100)
    entry = float(df["close"].iloc[-1])
    sl = stop_loss_price(entry, df)
    if sl is not None:
        assert sl < entry


def test_stop_loss_non_negative():
    df = make_candles(100)
    entry = float(df["close"].iloc[-1])
    sl = stop_loss_price(entry, df)
    if sl is not None:
        assert sl >= 0.0


def test_stop_loss_insufficient_candles():
    assert stop_loss_price(40000.0, make_candles(5)) is None


def test_take_profit_above_entry():
    tp = take_profit_price(40000.0, 39000.0)
    assert tp > 40000.0


def test_take_profit_risk_reward():
    entry = 100.0
    sl = 90.0
    tp = take_profit_price(entry, sl, risk_reward_ratio=RISK_REWARD_RATIO)
    assert abs(tp - (entry + (entry - sl) * RISK_REWARD_RATIO)) < 1e-6


def test_take_profit_invalid_stop():
    assert take_profit_price(100.0, stop_loss=110.0) is None


def test_take_profit_none_stop():
    assert take_profit_price(100.0, None) is None


# -- Alerts -------------------------------------------------------------------


def test_alert_risk_extreme_triggered():
    risk_data = {
        "score": ALERT_RISK_EXTREME + 5,
        "components": {
            "sentiment": {"risk": 0.5},
            "volatility": {"raw_vol": None},
        },
    }
    with patch("risk.alerts.log_alert"):
        alerts = check_alerts("BTC-USD", risk_data, candles=None)
    assert any(a.type == "RISK_EXTREME" for a in alerts)


def test_alert_risk_not_triggered_below_threshold():
    risk_data = {
        "score": ALERT_RISK_EXTREME - 5,
        "components": {
            "sentiment": {"risk": 0.5},
            "volatility": {"raw_vol": None},
        },
    }
    with patch("risk.alerts.log_alert"):
        alerts = check_alerts("BTC-USD", risk_data, candles=None)
    assert not any(a.type == "RISK_EXTREME" for a in alerts)


def test_alert_sentiment_crash():
    # sent_risk=0.9 → score = 1 - (2*0.9) = -0.8 (below -0.7 threshold)
    risk_data = {
        "score": 40,
        "components": {
            "sentiment": {"risk": 0.9},
            "volatility": {"raw_vol": None},
        },
    }
    with patch("risk.alerts.log_alert"):
        alerts = check_alerts("BTC-USD", risk_data, candles=None)
    assert any(a.type == "SENTIMENT_CRASH" for a in alerts)


def test_alert_price_drop():
    df = make_candles(10).copy()
    df.loc[df.index[-2], "close"] = 1000.0
    df.loc[df.index[-1], "close"] = 900.0  # 10% drop → exceeds -5% threshold

    risk_data = {
        "score": 40,
        "components": {
            "sentiment": {"risk": 0.5},
            "volatility": {"raw_vol": None},
        },
    }
    with patch("risk.alerts.log_alert"):
        alerts = check_alerts("BTC-USD", risk_data, candles=df)
    assert any(a.type == "PRICE_DROP" for a in alerts)


def test_risk_score_always_in_range():
    with (
        patch("risk.scorer.load_candles", return_value=make_candles(100)),
        patch("risk.scorer._compute_volatility_component", return_value=(None, 0.0)),
        patch("risk.scorer.TrendClassifier.model_path", return_value="nonexistent.pkl"),
        patch("risk.scorer._compute_sentiment_component", return_value=(0.5, 0.5)),
        patch("risk.scorer._compute_momentum_component", return_value=(0.3, 1.0)),
        patch("risk.scorer._get_fear_greed", return_value={"normalized": 0.2}),
    ):
        result = compute_risk_score("BTC-USD")
    assert 0.0 <= result["score"] <= 100.0


# -- Integration tests ---------------------------------------------------------


@pytest.mark.integration
def test_compute_risk_score_btc_live():
    result = compute_risk_score("BTC-USD")
    assert 0.0 <= result["score"] <= 100.0
    assert result["label"] in ("LOW", "MODERATE", "HIGH", "EXTREME")
    assert result["recommendation"] in ("TRADE", "HOLD", "REDUCE", "AVOID")
    print(
        f"\nBTC-USD risk: {result['score']:.1f}/100 ({result['label']}) → {result['recommendation']}"
    )


@pytest.mark.integration
def test_score_all_assets_live():
    from risk.scorer import score_all_assets

    results = score_all_assets()
    assert len(results) > 0
    for asset, r in results.items():
        assert 0.0 <= r["score"] <= 100.0, f"{asset} score out of range"
        print(f"  {asset:<12} {r['score']:>6.1f}/100  {r['label']:<10}  {r['recommendation']}")


@pytest.mark.integration
def test_full_position_plan_live():
    from data.storage import load_candles
    from risk.position_sizer import full_position_plan
    from risk.scorer import compute_risk_score

    result = compute_risk_score("BTC-USD")
    candles = load_candles("BTC-USD", "1h", days_back=5)
    plan = full_position_plan("BTC-USD", result, 10000.0, candles)

    print("\nBTC-USD position plan:")
    print(f"  Risk:        {plan['risk_score']:.1f}/100")
    print(f"  Recommend:   {plan['recommendation']}")
    print(
        f"  Position:    {plan['position']['position_pct'] * 100:.2f}% (${plan['position']['position_usd']:.2f})"
    )
    print(f"  Stop loss:   ${plan['stop_loss']}")
    print(f"  Take profit: ${plan['take_profit']}")
