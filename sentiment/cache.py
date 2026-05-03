import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from utils.logger import get_logger
from config.settings import CACHE_DIR, SENTIMENT_CACHE_TTL

logger = get_logger(__name__)


def _cache_path(asset: str) -> Path:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe_name = asset.replace("-", "_").replace("/", "_")
    return Path(CACHE_DIR) / f"sentiment_{safe_name}.json"


def cache_sentiment(asset: str, result: dict, ttl_minutes: int = 30) -> None:
    expiry = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    cache_entry = {
        "expires_at": expiry.isoformat(),
        "data":       _make_serializable(result),
    }
    path = _cache_path(asset)
    try:
        with open(path, "w") as f:
            json.dump(cache_entry, f, indent=2)
        logger.debug(f"Cached sentiment for {asset} (expires {expiry.strftime('%H:%M:%S')})")
    except Exception as e:
        logger.warning(f"Failed to cache sentiment for {asset}: {e}")


def load_cached_sentiment(asset: str) -> dict | None:
    path = _cache_path(asset)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            entry = json.load(f)
        expires_at = datetime.fromisoformat(entry["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            logger.debug(f"Cache expired for {asset}")
            return None
        logger.debug(f"Cache hit for {asset}")
        return entry["data"]
    except Exception as e:
        logger.warning(f"Cache read failed for {asset}: {e}")
        return None


def get_or_fetch_sentiment(asset: str, force_refresh: bool = False) -> dict:
    """
    Primary interface for getting sentiment scores.
    Returns cached composite result if valid, otherwise fetches fresh.
    TTL uses the min of all source TTLs (driven by dex_ratio at 5 min).
    Per-source caching (e.g. news.py) protects individual API rate limits
    independently of the composite cache TTL.
    """
    from sentiment.scorer import compute_sentiment_score

    if not force_refresh:
        cached = load_cached_sentiment(asset)
        if cached is not None:
            return cached

    result = compute_sentiment_score(asset)
    ttl = min(SENTIMENT_CACHE_TTL.get(src, 30) for src in SENTIMENT_CACHE_TTL)
    cache_sentiment(asset, result, ttl_minutes=ttl)
    return result


def clear_cache(asset: str = None) -> None:
    if asset:
        path = _cache_path(asset)
        if path.exists():
            path.unlink()
            logger.debug(f"Cleared cache for {asset}")
    else:
        cache_dir = Path(CACHE_DIR)
        if cache_dir.exists():
            for f in cache_dir.glob("sentiment_*.json"):
                f.unlink()
        logger.debug("Cleared all sentiment cache files")


def _make_serializable(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    return obj
