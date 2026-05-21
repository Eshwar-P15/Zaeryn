import os
from datetime import UTC, datetime

import pandas as pd
import ta

from config.settings import (
    ALL_ASSETS,
    FEATURE_WINDOWS,
    RECOMMEND_HOLD,
    RECOMMEND_REDUCE,
    RECOMMEND_TRADE,
    RISK_THRESHOLDS,
    RISK_WEIGHTS,
    RSI_MIN_CANDLES,
    VOL_RISK_CAP,
)
from data.cleaner import clean_ohlcv
from data.storage import init_db, load_candles
from models.trend import TrendClassifier
from models.volatility import VolatilityPredictor
from sentiment.cache import get_or_fetch_sentiment, load_cached_sentiment
from sentiment.fear_greed import fetch_fear_greed
from utils.logger import get_logger

logger = get_logger(__name__)

# Module-level Fear & Greed cache — fetched once per process run
_fg_cache: dict = {}


def _get_fear_greed() -> dict:
    global _fg_cache
    if not _fg_cache:
        _fg_cache = fetch_fear_greed()
    return _fg_cache


def _extract_rsi(candles: pd.DataFrame) -> float | None:
    """
    Extracts current RSI directly from candles without full feature pipeline.
    Rule 3: never call build_feature_matrix() for a single indicator.
    """
    if candles is None or candles.empty:
        return None

    clean = clean_ohlcv(candles)
    if len(clean) < RSI_MIN_CANDLES:
        return None

    try:
        rsi_vals = ta.momentum.RSIIndicator(
            close=clean["close"],
            window=FEATURE_WINDOWS["rsi"],
        ).rsi()
        valid = rsi_vals.dropna()
        if valid.empty:
            return None
        return float(valid.iloc[-1])
    except Exception as e:
        logger.debug(f"RSI extraction failed: {e}")
        return None


def _compute_volatility_component(asset: str, candles: pd.DataFrame) -> tuple[float | None, float]:
    """
    Rule 5: vol_risk = min(predicted_vol / VOL_RISK_CAP, 1.0)
    Returns (vol_risk, confidence) or (None, 0.0) if model unavailable.
    """
    path = VolatilityPredictor.model_path(asset)

    if not os.path.exists(path):
        logger.debug(f"[{asset}] No volatility model — skipping component")
        return None, 0.0

    if candles is None or candles.empty or len(candles) < 60:
        logger.debug(f"[{asset}] Insufficient candles for volatility prediction")
        return None, 0.0

    try:
        model = VolatilityPredictor()
        model.load(path)
        predicted_vol = model.predict(candles)
        vol_risk = min(predicted_vol / VOL_RISK_CAP, 1.0)
        return float(vol_risk), 1.0
    except Exception as e:
        logger.warning(f"[{asset}] Volatility prediction failed: {e}")
        return None, 0.0


def _compute_trend_component(asset: str, candles: pd.DataFrame) -> tuple[float | None, float]:
    """
    trend_risk = 1.0 - trend_confidence (low confidence = high uncertainty = high risk).
    Returns (trend_risk, confidence) or (None, 0.0) if model unavailable.
    """
    path = TrendClassifier.model_path(asset)

    if not os.path.exists(path):
        logger.debug(f"[{asset}] No trend model — skipping component")
        return None, 0.0

    if candles is None or candles.empty or len(candles) < 60:
        logger.debug(f"[{asset}] Insufficient candles for trend prediction")
        return None, 0.0

    try:
        model = TrendClassifier()
        model.load(path)
        result = model.predict_proba(candles)
        trend_confidence = float(result.get("confidence", 0.0))
        return 1.0 - trend_confidence, 1.0
    except Exception as e:
        logger.warning(f"[{asset}] Trend prediction failed: {e}")
        return None, 0.0


def _compute_sentiment_component(asset: str) -> tuple[float, float]:
    """
    Rule 1: cache-first — never blocks on API if cache is warm.
    Rule 6: sentiment_risk = (1.0 - score) / 2.0
    Returns (sentiment_risk, confidence). Defaults to (0.5, 0.0) on failure.
    """
    data = load_cached_sentiment(asset)

    if data is None:
        logger.debug(f"[{asset}] Sentiment cache miss — fetching fresh")
        try:
            data = get_or_fetch_sentiment(asset)
        except Exception as e:
            logger.warning(f"[{asset}] Sentiment fetch failed: {e}")
            return 0.5, 0.0

    if data is None:
        return 0.5, 0.0

    score = float(data.get("score", 0.0))
    confidence = float(data.get("confidence", 0.0))
    sentiment_risk = max(0.0, min(1.0, (1.0 - score) / 2.0))
    return sentiment_risk, confidence


def _compute_momentum_component(candles: pd.DataFrame) -> tuple[float, float]:
    """
    Rule 7: momentum_risk = abs(rsi - 50) / 50.0
    RSI extremes in either direction increase risk.
    Returns (momentum_risk, confidence). Defaults to (0.0, 0.0) if RSI unavailable.
    """
    rsi = _extract_rsi(candles)
    if rsi is None:
        return 0.0, 0.0

    momentum_risk = max(0.0, min(1.0, abs(rsi - 50.0) / 50.0))
    return momentum_risk, 1.0


def _compute_regime_component() -> tuple[float, float]:
    """
    Rule 8: regime_risk = abs(fear_greed_normalized)
    Both extreme fear AND extreme greed increase risk.
    """
    try:
        fg = _get_fear_greed()
        norm = float(fg.get("normalized", 0.0))
        return abs(norm), 1.0
    except Exception as e:
        logger.warning(f"Fear & Greed failed: {e}")
        return 0.0, 0.0


def _redistribute_weights(components: dict[str, tuple[float | None, float]]) -> dict[str, float]:
    """
    Rule 2: redistribute weight from unavailable components proportionally
    among available ones. Returns {name: effective_weight} summing to 1.0.
    """
    available = {
        name: RISK_WEIGHTS[name] for name, (value, _) in components.items() if value is not None
    }

    if not available:
        return {}

    total = sum(available.values())
    if total == 0:
        return {}

    return {name: weight / total for name, weight in available.items()}


def risk_label(score: float) -> str:
    for label, (low, high) in RISK_THRESHOLDS.items():
        if low <= score < high:
            return label
    if score >= 100:
        return "EXTREME"
    return "LOW"


def recommendation(score: float, trend_data: dict | None) -> str:
    if score >= RECOMMEND_REDUCE:
        return "AVOID"
    if score >= RECOMMEND_HOLD:
        return "REDUCE"
    if score >= RECOMMEND_TRADE:
        return "HOLD"
    if trend_data and trend_data.get("direction") == "UNCERTAIN":
        return "HOLD"
    return "TRADE"


def compute_risk_score(
    asset: str,
    candles: pd.DataFrame = None,
    conn=None,
) -> dict:
    """
    Computes the full composite risk score (0-100) for a single asset.

    Returns dict with score, label, recommendation, component breakdown,
    models_available flag, trend data, and timestamp.
    """
    logger.info(f"Computing risk score: {asset}")

    # Load candles if not provided
    if candles is None:
        close_conn = False
        if conn is None:
            conn = init_db()
            close_conn = True
        try:
            candles = load_candles(asset, "1h", days_back=30, conn=conn)
        except Exception as e:
            logger.error(f"[{asset}] Failed to load candles: {e}")
            candles = pd.DataFrame()
        finally:
            if close_conn and conn:
                conn.close()

    # Compute each component
    vol_risk, vol_conf = _compute_volatility_component(asset, candles)

    # Trend — compute once, reuse for both the component risk and recommendation
    trend_path = TrendClassifier.model_path(asset)
    trend_data = None
    if os.path.exists(trend_path) and candles is not None and len(candles) >= 60:
        try:
            trend_model = TrendClassifier()
            trend_model.load(trend_path)
            trend_data = trend_model.predict_proba(candles)
        except Exception as e:
            logger.warning(f"[{asset}] Trend predict_proba failed: {e}")

    if trend_data is not None:
        trend_risk = 1.0 - float(trend_data.get("confidence", 0.0))
        trend_conf = 1.0
    else:
        trend_risk = None
        trend_conf = 0.0

    sent_risk, sent_conf = _compute_sentiment_component(asset)
    mom_risk, mom_conf = _compute_momentum_component(candles)
    reg_risk, reg_conf = _compute_regime_component()

    components_raw = {
        "volatility": (vol_risk, vol_conf),
        "trend_uncertainty": (trend_risk, trend_conf),
        "sentiment": (sent_risk, sent_conf),
        "price_momentum": (mom_risk, mom_conf),
        "market_regime": (reg_risk, reg_conf),
    }

    effective_weights = _redistribute_weights(components_raw)

    # Rule 4: weighted sum * 100, clamped to [0, 100]
    weighted_sum = sum(
        components_raw[name][0] * w
        for name, w in effective_weights.items()
        if components_raw[name][0] is not None
    )
    final_score = max(0.0, min(100.0, weighted_sum * 100.0))

    rsi_val = _extract_rsi(candles) if candles is not None and not candles.empty else None
    fg_val = _fg_cache.get("normalized") if _fg_cache else None

    components_detail = {
        "volatility": {
            "risk": vol_risk,
            "weight": effective_weights.get("volatility", 0.0),
            "raw_vol": float(vol_risk * VOL_RISK_CAP) if vol_risk is not None else None,
        },
        "trend_uncertainty": {
            "risk": trend_risk,
            "weight": effective_weights.get("trend_uncertainty", 0.0),
            "direction": trend_data.get("direction") if trend_data else None,
            "confidence": trend_data.get("confidence") if trend_data else None,
        },
        "sentiment": {
            "risk": sent_risk,
            "weight": effective_weights.get("sentiment", 0.0),
            "confidence": sent_conf,
        },
        "price_momentum": {
            "risk": mom_risk,
            "weight": effective_weights.get("price_momentum", 0.0),
            "rsi": rsi_val,
        },
        "market_regime": {
            "risk": reg_risk,
            "weight": effective_weights.get("market_regime", 0.0),
            "fear_greed": fg_val,
        },
    }

    result = {
        "asset": asset,
        "score": round(final_score, 2),
        "label": risk_label(final_score),
        "recommendation": recommendation(final_score, trend_data),
        "components": components_detail,
        "models_available": vol_risk is not None,
        "trend": trend_data,
        "timestamp": datetime.now(UTC),
    }

    logger.info(
        f"[{asset}] Risk: {final_score:.1f}/100 ({result['label']}) "
        f"→ {result['recommendation']} "
        f"[models={'✓' if result['models_available'] else '✗'}]"
    )
    return result


def score_all_assets(conn=None) -> dict[str, dict]:
    """
    Scores all assets. Reuses one DB connection and one Fear & Greed fetch.
    Individual failures do not stop the batch.
    """
    global _fg_cache
    _fg_cache = {}

    try:
        _fg_cache = fetch_fear_greed()
    except Exception as e:
        logger.warning(f"Fear & Greed pre-fetch failed: {e}")

    close_conn = False
    if conn is None:
        conn = init_db()
        close_conn = True

    results = {}
    try:
        for asset in ALL_ASSETS:
            try:
                candles = load_candles(asset, "1h", days_back=30, conn=conn)
                results[asset] = compute_risk_score(asset, candles=candles, conn=conn)
            except Exception as e:
                logger.error(f"[{asset}] score_all_assets failed: {e}")
    finally:
        if close_conn and conn:
            conn.close()

    logger.info(f"Risk scoring complete: {len(results)}/{len(ALL_ASSETS)} assets")
    return results
