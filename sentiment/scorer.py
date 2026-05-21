from datetime import UTC, datetime

from config.settings import (
    ALL_ASSETS,
    SENTIMENT_LABELS,
    SENTIMENT_WEIGHTS,
)
from sentiment.dex_sentiment import fetch_dex_sentiment
from sentiment.fear_greed import fetch_fear_greed
from sentiment.news import fetch_news_sentiment
from sentiment.onchain import fetch_onchain_sentiment
from sentiment.twitter_scraper import fetch_twitter_sentiment
from utils.logger import get_logger

logger = get_logger(__name__)

# Fear & Greed is market-wide — fetched once per batch run, reused across all assets.
# Reset at start of score_all_assets() so each batch run gets a fresh reading.
_fear_greed_cache: dict = {}


def _get_fear_greed() -> dict:
    global _fear_greed_cache
    if not _fear_greed_cache:
        _fear_greed_cache = fetch_fear_greed()
    return _fear_greed_cache


def score_label(score: float) -> str:
    """
    Maps score to sentiment label using strict upper bound (low <= score < high).
    Handles the maximum value 1.0 as a special case.
    """
    if score >= 1.0:
        return "Very Bullish"
    for (low, high), label in SENTIMENT_LABELS.items():
        if low <= score < high:
            return label
    return "Neutral"


def compute_sentiment_score(asset: str, include_twitter: bool = False) -> dict:
    """
    Computes weighted composite sentiment score for a single asset.

    Aggregation: effective_weight = base_weight * confidence
    Final score = sum(score * eff_weight) / sum(eff_weights)
    Low-confidence sources auto-downweight; failed sources contribute nothing.

    Twitter defaults to False (dormant until credentials confirmed).
    Twitter weight is 0.00 in SENTIMENT_WEIGHTS so it contributes nothing
    even when include_twitter=True unless the weight is raised.
    """
    logger.info(f"Computing sentiment for {asset}...")
    components = {}

    try:
        components["onchain"] = fetch_onchain_sentiment(asset)
    except Exception as e:
        logger.error(f"On-chain failed for {asset}: {e}")
        components["onchain"] = {"score": 0.0, "confidence": 0.0}

    try:
        components["dex_ratio"] = fetch_dex_sentiment(asset)
    except Exception as e:
        logger.error(f"DEX sentiment failed for {asset}: {e}")
        components["dex_ratio"] = {"score": 0.0, "confidence": 0.0}

    try:
        components["news"] = fetch_news_sentiment(asset)
    except Exception as e:
        logger.error(f"News failed for {asset}: {e}")
        components["news"] = {"score": 0.0, "confidence": 0.0}

    try:
        fg = _get_fear_greed()
        components["fear_greed"] = {"score": fg["normalized"], "confidence": 1.0}
    except Exception as e:
        logger.error(f"Fear & Greed failed: {e}")
        components["fear_greed"] = {"score": 0.0, "confidence": 0.0}

    if include_twitter:
        try:
            components["twitter"] = fetch_twitter_sentiment(asset)
        except Exception as e:
            logger.error(f"Twitter failed for {asset}: {e}")
            components["twitter"] = {"score": 0.0, "confidence": 0.0}
    else:
        components["twitter"] = {"score": 0.0, "confidence": 0.0}

    # Weighted aggregation
    weighted_sum = 0.0
    total_weight = 0.0
    component_detail = {}

    for source, base_weight in SENTIMENT_WEIGHTS.items():
        component = components.get(source, {})
        source_score = float(component.get("score", 0.0))
        source_conf = float(component.get("confidence", 0.0))
        effective_weight = base_weight * source_conf

        weighted_sum += source_score * effective_weight
        total_weight += effective_weight

        component_detail[source] = {
            "score": round(source_score, 4),
            "confidence": round(source_conf, 4),
            "base_weight": base_weight,
            "weight_used": round(effective_weight, 4),
        }

    final_score = max(-1.0, min(1.0, weighted_sum / total_weight if total_weight > 0 else 0.0))

    source_confs = [c.get("confidence", 0.0) for c in components.values()]
    overall_conf = sum(source_confs) / len(source_confs) if source_confs else 0.0

    result = {
        "asset": asset,
        "score": round(final_score, 4),
        "label": score_label(final_score),
        "confidence": round(overall_conf, 4),
        "components": component_detail,
        "timestamp": datetime.now(UTC),
    }
    logger.info(
        f"Sentiment {asset}: {final_score:+.4f} ({result['label']}) [confidence={overall_conf:.2f}]"
    )
    return result


def score_all_assets(include_twitter: bool = False) -> dict[str, dict]:
    """Scores all assets in ALL_ASSETS. Resets Fear & Greed cache at batch start."""
    global _fear_greed_cache
    _fear_greed_cache = {}

    results = {}
    for asset in ALL_ASSETS:
        try:
            results[asset] = compute_sentiment_score(asset, include_twitter=include_twitter)
        except Exception as e:
            logger.error(f"score_all_assets failed for {asset}: {e}")

    logger.info(f"Sentiment scoring complete: {len(results)}/{len(ALL_ASSETS)} assets")
    return results


def get_market_sentiment() -> dict:
    """
    Macro market sentiment — averaged across all assets.
    Used by the Phase 4 risk engine as a regime signal.
    """
    fg = _get_fear_greed()
    all_scores = score_all_assets(include_twitter=False)

    asset_scores = {a: r["score"] for a, r in all_scores.items()}
    market_score = sum(asset_scores.values()) / len(asset_scores) if asset_scores else 0.0

    return {
        "market_score": round(market_score, 4),
        "market_label": score_label(market_score),
        "fear_greed": fg,
        "asset_scores": asset_scores,
        "timestamp": datetime.now(UTC),
    }
