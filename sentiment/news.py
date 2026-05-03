import os
import json
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from textblob import TextBlob
from utils.logger import get_logger
from config.settings import (
    NEWSAPI_BASE_URL,
    ASSET_NEWS_KEYWORDS,
    CACHE_DIR,
    REQUEST_TIMEOUT,
    REQUEST_RETRY_ATTEMPTS,
    REQUEST_RETRY_DELAYS,
)

logger = get_logger(__name__)

RECENCY_DECAY_PER_HOUR = 0.90
NEWS_CACHE_TTL_MINUTES = 20


def _news_cache_path(asset: str) -> Path:
    os.makedirs(CACHE_DIR, exist_ok=True)
    safe_name = asset.replace("-", "_").replace("/", "_")
    return Path(CACHE_DIR) / f"news_{safe_name}.json"


def _load_news_cache(asset: str) -> dict | None:
    path = _news_cache_path(asset)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            entry = json.load(f)
        expires = datetime.fromisoformat(entry["expires_at"])
        if datetime.now(timezone.utc) > expires:
            return None
        return entry["data"]
    except Exception:
        return None


def _save_news_cache(asset: str, result: dict) -> None:
    expiry = datetime.now(timezone.utc) + timedelta(minutes=NEWS_CACHE_TTL_MINUTES)
    try:
        with open(_news_cache_path(asset), "w") as f:
            json.dump({"expires_at": expiry.isoformat(), "data": result}, f)
    except Exception as e:
        logger.warning(f"News cache write failed for {asset}: {e}")


def _fetch_articles(query: str) -> list[dict]:
    api_key = os.getenv("NEWSAPI_API_KEY", "")
    if not api_key:
        return []

    params = {
        "q":        query,
        "language": "en",
        "sortBy":   "publishedAt",
        "pageSize": 20,
        "apiKey":   api_key,
    }

    last_error = None
    for attempt in range(REQUEST_RETRY_ATTEMPTS):
        if attempt > 0:
            time.sleep(REQUEST_RETRY_DELAYS[attempt - 1])
        try:
            response = requests.get(NEWSAPI_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json().get("articles", [])
        except Exception as e:
            last_error = e
            logger.warning(f"NewsAPI request failed (attempt {attempt+1}): {e}")

    logger.error(f"NewsAPI: all retries failed for '{query}': {last_error}")
    return []


def fetch_news_sentiment(asset: str) -> dict:
    """
    Fetches and scores crypto news for an asset via NewsAPI.

    Scoring per article:
        text  = title + " " + (description or "")
        score = TextBlob(text).sentiment.polarity  -> [-1.0, +1.0]
    Recency weight:
        weight = 0.90 ** hours_since_published
    Final score = weighted mean of article scores.
    Confidence = min(1.0, article_count / 10)

    Results are file-cached for 20 minutes to stay within the 100 req/day free limit.
    Returns score=0.0, confidence=0.0 if key missing or no articles found.
    """
    cached = _load_news_cache(asset)
    if cached is not None:
        logger.debug(f"News cache hit for {asset}")
        return cached

    if not os.getenv("NEWSAPI_API_KEY", ""):
        logger.warning("NEWSAPI_API_KEY not set - skipping news sentiment")
        return _null_result(asset, "no API key")

    query = ASSET_NEWS_KEYWORDS.get(asset)
    if not query:
        return _null_result(asset, "no keyword mapping")

    articles = _fetch_articles(query)

    if not articles:
        result = _null_result(asset, "no articles returned")
        _save_news_cache(asset, result)
        return result

    now = datetime.now(timezone.utc)
    weighted_sum  = 0.0
    total_weight  = 0.0

    for article in articles:
        title       = article.get("title", "") or ""
        description = article.get("description", "") or ""
        text        = (title + " " + description).strip()

        if not text:
            continue

        try:
            polarity = TextBlob(text).sentiment.polarity
        except Exception:
            polarity = 0.0

        published_str = article.get("publishedAt", "")
        try:
            published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            hours_ago = (now - published).total_seconds() / 3600
            weight = RECENCY_DECAY_PER_HOUR ** hours_ago
        except Exception:
            weight = 0.5

        weighted_sum += polarity * weight
        total_weight += weight

    if total_weight == 0:
        result = _null_result(asset, "no scoreable articles")
        _save_news_cache(asset, result)
        return result

    score = max(-1.0, min(1.0, weighted_sum / total_weight))
    article_count = len(articles)
    confidence = min(1.0, article_count / 10)

    result = {
        "score":         round(score, 4),
        "article_count": article_count,
        "confidence":    round(confidence, 4),
        "source":        "news",
        "asset":         asset,
    }
    logger.info(f"News sentiment {asset}: {score:+.3f} ({article_count} articles)")
    _save_news_cache(asset, result)
    return result


def _null_result(asset: str, reason: str = "") -> dict:
    return {
        "score":         0.0,
        "article_count": 0,
        "confidence":    0.0,
        "source":        "news",
        "asset":         asset,
        "error":         reason,
    }
