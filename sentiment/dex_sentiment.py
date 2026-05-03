import time
import requests
from utils.logger import get_logger
from config.settings import (
    DEXSCREENER_BASE_URL,
    SOLANA_TOKENS,
    ASSET_SOURCE,
    REQUEST_TIMEOUT,
    REQUEST_RETRY_ATTEMPTS,
    REQUEST_RETRY_DELAYS,
)

logger = get_logger(__name__)


def _fetch_pair_stats(pair_address: str) -> dict:
    url = f"{DEXSCREENER_BASE_URL}/pairs/solana/{pair_address}"
    last_error = None
    for attempt in range(REQUEST_RETRY_ATTEMPTS):
        if attempt > 0:
            time.sleep(REQUEST_RETRY_DELAYS[attempt - 1])
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            pairs = response.json().get("pairs", [])
            return pairs[0] if pairs else {}
        except Exception as e:
            last_error = e
            logger.warning(f"DexScreener pair stats failed (attempt {attempt+1}): {e}")
    return {}


def fetch_dex_sentiment(asset: str) -> dict:
    """
    Behavioral sentiment from DexScreener buy/sell transaction ratio.

    Only applies to DEX tokens — Coinbase assets return neutral score.

    Scoring:
        ratio_1h  = buys_1h  / (buys_1h  + sells_1h  + 1)
        ratio_24h = buys_24h / (buys_24h + sells_24h + 1)
        combined  = ratio_1h * 0.6 + ratio_24h * 0.4
        score     = (combined - 0.5) * 2     -> [-1.0, +1.0]
        Price change 1h > 5%: +0.1 boost; < -5%: -0.1 drag
    Confidence based on 1h transaction count.
    """
    if ASSET_SOURCE.get(asset) != "dex":
        return {
            "score":      0.0,
            "confidence": 0.0,
            "source":     "dex_ratio",
            "asset":      asset,
            "note":       "coinbase asset - no DEX ratio available",
        }

    from data.dex_fetcher import get_pair_address
    pair_address = get_pair_address(asset)

    if not pair_address:
        logger.warning(f"No pair address for {asset} - cannot get DEX sentiment")
        return _null_result(asset)

    pair = _fetch_pair_stats(pair_address)
    if not pair:
        return _null_result(asset)

    txns = pair.get("txns", {})
    buys_1h   = int(txns.get("h1",  {}).get("buys",  0) or 0)
    sells_1h  = int(txns.get("h1",  {}).get("sells", 0) or 0)
    buys_24h  = int(txns.get("h24", {}).get("buys",  0) or 0)
    sells_24h = int(txns.get("h24", {}).get("sells", 0) or 0)

    volume_1h    = float(pair.get("volume",      {}).get("h1", 0) or 0)
    price_chg_1h = float(pair.get("priceChange", {}).get("h1", 0) or 0)

    ratio_1h  = buys_1h  / (buys_1h  + sells_1h  + 1)
    ratio_24h = buys_24h / (buys_24h + sells_24h + 1)
    combined  = ratio_1h * 0.6 + ratio_24h * 0.4
    score     = (combined - 0.5) * 2

    if price_chg_1h > 5:
        score += 0.1
    elif price_chg_1h < -5:
        score -= 0.1

    score = max(-1.0, min(1.0, score))

    total_txns = buys_1h + sells_1h
    if total_txns >= 200:
        confidence = 1.0
    elif total_txns >= 50:
        confidence = 0.7
    elif total_txns >= 10:
        confidence = 0.4
    else:
        confidence = 0.1

    result = {
        "score":        round(score, 4),
        "buys_1h":      buys_1h,
        "sells_1h":     sells_1h,
        "ratio_1h":     round(ratio_1h, 4),
        "volume_1h":    volume_1h,
        "price_chg_1h": price_chg_1h,
        "confidence":   confidence,
        "source":       "dex_ratio",
        "asset":        asset,
    }
    logger.info(
        f"DEX sentiment {asset}: {score:+.3f} "
        f"(buys={buys_1h}, sells={sells_1h}, ratio={ratio_1h:.2f})"
    )
    return result


def _null_result(asset: str) -> dict:
    return {"score": 0.0, "confidence": 0.0, "source": "dex_ratio", "asset": asset}
