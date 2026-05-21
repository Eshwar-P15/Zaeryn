import asyncio
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from textblob import TextBlob

from config.settings import (
    ASSET_TWITTER_KEYWORDS,
    CACHE_DIR,
    TWITTER_ACCOUNTS,
)
from utils.logger import get_logger

logger = get_logger(__name__)

COOKIE_PATH = Path(CACHE_DIR) / "twitter_cookies.json"
MAX_TWEETS_PER_ACCOUNT = 10
MAX_SEARCH_TWEETS = 50
TWEET_LOOKBACK_HOURS = 24


def _score_tweet_text(text: str) -> float:
    try:
        return round(TextBlob(text).sentiment.polarity, 4)
    except Exception:
        return 0.0


async def _get_client():
    try:
        from twikit import Client
    except ImportError:
        raise ImportError("twikit not installed. Run: pip install twikit")  # noqa: B904

    os.makedirs(CACHE_DIR, exist_ok=True)
    client = Client("en-US")

    username = os.getenv("TWITTER_USERNAME", "")
    email = os.getenv("TWITTER_EMAIL", "")
    password = os.getenv("TWITTER_PASSWORD", "")

    if not all([username, email, password]):
        raise ValueError("TWITTER_USERNAME, TWITTER_EMAIL, TWITTER_PASSWORD must be set in .env")

    if COOKIE_PATH.exists():
        try:
            client.load_cookies(str(COOKIE_PATH))
            logger.debug("Loaded Twitter cookies from cache")
            return client
        except Exception as e:
            logger.warning(f"Cookie load failed, re-logging in: {e}")

    logger.info("Logging in to Twitter (fresh session)...")
    await client.login(
        auth_info_1=username,
        auth_info_2=email,
        password=password,
    )
    client.save_cookies(str(COOKIE_PATH))
    logger.info("Twitter login successful, cookies saved")
    return client


async def _fetch_account_tweets(client, username: str) -> list[dict]:
    """
    Fetches recent tweets from an account.
    twikit 2.x: user.get_tweets(), NOT client.get_user_tweets().
    """
    try:
        user = await client.get_user_by_screen_name(username)
        tweets = await user.get_tweets("Tweets", count=MAX_TWEETS_PER_ACCOUNT)
        results = []
        cutoff = datetime.now(UTC) - timedelta(hours=TWEET_LOOKBACK_HOURS)

        for tweet in tweets:
            try:
                created = datetime.strptime(tweet.created_at, "%a %b %d %H:%M:%S %z %Y")
                if created < cutoff:
                    continue
                results.append(
                    {
                        "text": tweet.full_text or tweet.text or "",
                        "created_at": created,
                        "like_count": tweet.favorite_count or 0,
                        "retweet_count": tweet.retweet_count or 0,
                        "username": username,
                    }
                )
            except Exception:
                continue
        return results
    except Exception as e:
        logger.warning(f"Failed to fetch tweets from @{username}: {e}")
        return []


async def _search_tweets(client, keywords: list[str]) -> list[dict]:
    results = []
    for keyword in keywords[:2]:
        try:
            tweets = await client.search_tweet(
                keyword, product="Latest", count=MAX_SEARCH_TWEETS // len(keywords[:2])
            )
            cutoff = datetime.now(UTC) - timedelta(hours=TWEET_LOOKBACK_HOURS)
            for tweet in tweets:
                try:
                    created = datetime.strptime(tweet.created_at, "%a %b %d %H:%M:%S %z %Y")
                    if created < cutoff:
                        continue
                    results.append(
                        {
                            "text": tweet.full_text or tweet.text or "",
                            "created_at": created,
                            "like_count": tweet.favorite_count or 0,
                            "retweet_count": tweet.retweet_count or 0,
                            "username": tweet.user.screen_name if tweet.user else "unknown",
                        }
                    )
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Tweet search failed for '{keyword}': {e}")
    return results


def _is_relevant_to_asset(text: str, asset: str) -> bool:
    keywords = ASSET_TWITTER_KEYWORDS.get(asset, [])
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


async def _fetch_twitter_sentiment_async(asset: str) -> dict:
    try:
        client = await _get_client()
    except ValueError as e:
        logger.warning(
            f"Twitter skipped for {asset}: {e}. "
            f"Set TWITTER_USERNAME/EMAIL/PASSWORD in .env to enable."
        )
        return _null_result(asset, str(e))
    except Exception as e:
        logger.error(f"Twitter client init failed: {e}")
        return _null_result(asset, str(e))

    all_tweets = []

    for username, meta in TWITTER_ACCOUNTS.items():
        account_assets = meta.get("assets", [])
        if asset not in account_assets and "all" not in account_assets:
            continue
        tweets = await _fetch_account_tweets(client, username)
        relevant = [t for t in tweets if _is_relevant_to_asset(t["text"], asset)]
        for tweet in relevant:
            tweet["account_weight"] = meta.get("weight", 1.0)
        all_tweets.extend(relevant)
        await asyncio.sleep(1.0)

    keywords = ASSET_TWITTER_KEYWORDS.get(asset, [])
    if keywords:
        search_tweets = await _search_tweets(client, keywords)
        for tweet in search_tweets:
            tweet["account_weight"] = 1.0
        all_tweets.extend(search_tweets)

    if not all_tweets:
        logger.debug(f"No relevant tweets found for {asset}")
        return _null_result(asset, "no tweets found")

    weighted_sum = 0.0
    total_weight = 0.0

    for tweet in all_tweets:
        text_score = _score_tweet_text(tweet["text"])
        engagement = tweet.get("like_count", 0) + tweet.get("retweet_count", 0) * 2
        eng_boost = min(2.0, math.log1p(engagement) / 10)
        weight = tweet.get("account_weight", 1.0) * (1.0 + eng_boost)
        weighted_sum += text_score * weight
        total_weight += weight

    score = max(-1.0, min(1.0, weighted_sum / total_weight if total_weight > 0 else 0.0))
    confidence = min(1.0, len(all_tweets) / 20.0)

    result = {
        "score": round(score, 4),
        "tweet_count": len(all_tweets),
        "confidence": round(confidence, 4),
        "source": "twitter",
        "asset": asset,
    }
    logger.info(f"Twitter sentiment {asset}: {score:+.3f} ({len(all_tweets)} tweets)")
    return result


def fetch_twitter_sentiment(asset: str) -> dict:
    """Synchronous wrapper for async Twitter sentiment fetching."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_fetch_twitter_sentiment_async(asset))
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Twitter sentiment failed for {asset}: {e}")
        return _null_result(asset, str(e))


def _null_result(asset: str, reason: str = "") -> dict:
    return {
        "score": 0.0,
        "tweet_count": 0,
        "confidence": 0.0,
        "source": "twitter",
        "asset": asset,
        "error": reason,
    }
