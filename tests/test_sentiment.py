import pytest
import nltk
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

for _corpus in ["punkt", "punkt_tab"]:
    try:
        nltk.data.find(f"tokenizers/{_corpus}")
    except LookupError:
        nltk.download(_corpus, quiet=True)

from sentiment.fear_greed    import fetch_fear_greed
from sentiment.scorer        import score_label, compute_sentiment_score
from sentiment.dex_sentiment import fetch_dex_sentiment
from sentiment.news          import fetch_news_sentiment
from sentiment.cache         import cache_sentiment, load_cached_sentiment, clear_cache
from sentiment.onchain       import compute_whale_concentration



# --- score_label tests ---

def test_score_label_very_bearish():
    assert score_label(-0.8) == "Very Bearish"

def test_score_label_bearish():
    assert score_label(-0.4) == "Bearish"

def test_score_label_neutral():
    assert score_label(0.0)  == "Neutral"
    assert score_label(0.1)  == "Neutral"

def test_score_label_bullish():
    assert score_label(0.4) == "Bullish"

def test_score_label_very_bullish():
    assert score_label(0.8) == "Very Bullish"

def test_score_label_boundary_at_0_2():
    # 0.2 should fall into Bullish (0.2 <= 0.2 < 0.6), not Neutral
    assert score_label(0.2) == "Bullish"

def test_score_label_max():
    assert score_label(1.0) == "Very Bullish"


# --- fear_greed tests ---

def _mock_fg_get(value_str):
    mock = MagicMock(status_code=200)
    mock.raise_for_status = lambda: None
    mock.json = lambda: {"data": [{"value": value_str, "timestamp": "0"}]}
    return mock

def test_fear_greed_normalization():
    with patch("requests.get", return_value=_mock_fg_get("50")):
        result = fetch_fear_greed()
    assert result["normalized"] == pytest.approx(0.0, abs=0.01)

def test_fear_greed_extreme_fear():
    with patch("requests.get", return_value=_mock_fg_get("0")):
        result = fetch_fear_greed()
    assert result["normalized"] == pytest.approx(-1.0, abs=0.01)

def test_fear_greed_extreme_greed():
    with patch("requests.get", return_value=_mock_fg_get("100")):
        result = fetch_fear_greed()
    assert result["normalized"] == pytest.approx(1.0, abs=0.01)


# --- dex_sentiment tests ---

def test_dex_sentiment_coinbase_asset_returns_neutral():
    result = fetch_dex_sentiment("BTC-USD")
    assert result["score"] == 0.0
    assert result["confidence"] == 0.0
    assert "non-DEX" in result.get("note", "")

def test_dex_sentiment_buy_dominated():
    mock_pair = {
        "txns": {
            "h1":  {"buys": 200, "sells": 20},
            "h24": {"buys": 1500, "sells": 200},
        },
        "volume":      {"h1": 50000},
        "priceChange": {"h1": 3.0},
    }
    with patch("sentiment.dex_sentiment._fetch_pair_stats", return_value=mock_pair), \
         patch("data.dex_fetcher.get_pair_address", return_value="fake_addr"):
        result = fetch_dex_sentiment("JUP")
    assert result["score"] > 0.3

def test_dex_sentiment_sell_dominated():
    mock_pair = {
        "txns": {
            "h1":  {"buys": 20, "sells": 200},
            "h24": {"buys": 200, "sells": 1500},
        },
        "volume":      {"h1": 30000},
        "priceChange": {"h1": -4.0},
    }
    with patch("sentiment.dex_sentiment._fetch_pair_stats", return_value=mock_pair), \
         patch("data.dex_fetcher.get_pair_address", return_value="fake_addr"):
        result = fetch_dex_sentiment("JUP")
    assert result["score"] < -0.3

def test_dex_sentiment_score_clamped():
    mock_pair = {
        "txns": {
            "h1":  {"buys": 10000, "sells": 0},
            "h24": {"buys": 50000, "sells": 0},
        },
        "volume":      {"h1": 999999},
        "priceChange": {"h1": 100.0},
    }
    with patch("sentiment.dex_sentiment._fetch_pair_stats", return_value=mock_pair), \
         patch("data.dex_fetcher.get_pair_address", return_value="fake_addr"):
        result = fetch_dex_sentiment("JUP")
    assert -1.0 <= result["score"] <= 1.0


# --- news tests (NewsAPI) ---

def _mock_newsapi_get(articles):
    mock = MagicMock(status_code=200)
    mock.raise_for_status = lambda: None
    mock.json = lambda: {"status": "ok", "articles": articles}
    return mock

def test_news_no_api_key_returns_null(monkeypatch, tmp_path):
    monkeypatch.delenv("NEWSAPI_API_KEY", raising=False)
    monkeypatch.setattr("sentiment.news.CACHE_DIR", str(tmp_path))
    result = fetch_news_sentiment("BTC-USD")
    assert result["score"] == 0.0
    assert result["confidence"] == 0.0
    assert result["source"] == "news"

def test_news_positive_headlines(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWSAPI_API_KEY", "test_key")
    monkeypatch.setattr("sentiment.news.CACHE_DIR", str(tmp_path))
    articles = [
        {
            "title":       "Bitcoin surges to all-time high, investors celebrate massive gains",
            "description": "Great bullish momentum across crypto markets",
            "publishedAt": "2026-01-01T00:00:00Z",
        },
        {
            "title":       "Crypto market soars, excellent performance across the board",
            "description": "Investors profit as prices rally strongly",
            "publishedAt": "2026-01-01T00:00:00Z",
        },
    ]
    with patch("requests.get", return_value=_mock_newsapi_get(articles)):
        result = fetch_news_sentiment("BTC-USD")
    assert result["score"] > 0.0
    assert result["article_count"] == 2
    assert result["source"] == "news"

def test_news_none_description_handled(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWSAPI_API_KEY", "test_key")
    monkeypatch.setattr("sentiment.news.CACHE_DIR", str(tmp_path))
    articles = [
        {"title": "Bitcoin news", "description": None, "publishedAt": "2026-01-01T00:00:00Z"},
    ]
    with patch("requests.get", return_value=_mock_newsapi_get(articles)):
        result = fetch_news_sentiment("BTC-USD")
    assert isinstance(result["score"], float)

def test_news_confidence_scales_with_count(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWSAPI_API_KEY", "test_key")
    monkeypatch.setattr("sentiment.news.CACHE_DIR", str(tmp_path))
    articles = [
        {"title": f"Article {i}", "description": "news", "publishedAt": "2026-01-01T00:00:00Z"}
        for i in range(5)
    ]
    with patch("requests.get", return_value=_mock_newsapi_get(articles)):
        result = fetch_news_sentiment("BTC-USD")
    assert result["confidence"] == pytest.approx(0.5)

def test_news_confidence_caps_at_1(monkeypatch, tmp_path):
    monkeypatch.setenv("NEWSAPI_API_KEY", "test_key")
    monkeypatch.setattr("sentiment.news.CACHE_DIR", str(tmp_path))
    articles = [
        {"title": f"Crypto news {i}", "description": "update", "publishedAt": "2026-01-01T00:00:00Z"}
        for i in range(20)
    ]
    with patch("requests.get", return_value=_mock_newsapi_get(articles)):
        result = fetch_news_sentiment("BTC-USD")
    assert result["confidence"] == pytest.approx(1.0)


# --- whale concentration tests ---

def test_whale_concentration_basic():
    holders = [{"uiAmount": 100}, {"uiAmount": 50}]
    pct = compute_whale_concentration(holders, total_supply=1000)
    assert pct == pytest.approx(15.0)

def test_whale_concentration_no_supply():
    holders = [{"uiAmount": 100}]
    pct = compute_whale_concentration(holders, total_supply=0)
    assert pct == 0.0

def test_whale_concentration_empty_holders():
    pct = compute_whale_concentration([], total_supply=1000)
    assert pct == 0.0

def test_whale_concentration_none_ui_amount():
    # Falls back to amount/decimals arithmetic
    holders = [{"uiAmount": None, "amount": "1000000", "decimals": 6}]
    pct = compute_whale_concentration(holders, total_supply=1.0)
    assert pct == pytest.approx(100.0)


# --- cache tests ---

def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("sentiment.cache.CACHE_DIR", str(tmp_path))
    fake_result = {
        "asset":     "JUP",
        "score":     0.42,
        "label":     "Bullish",
        "timestamp": datetime.now(timezone.utc),
    }
    cache_sentiment("JUP", fake_result, ttl_minutes=60)
    loaded = load_cached_sentiment("JUP")
    assert loaded is not None
    assert loaded["score"] == 0.42

def test_cache_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr("sentiment.cache.CACHE_DIR", str(tmp_path))
    fake = {"asset": "JUP", "score": 0.1, "timestamp": datetime.now(timezone.utc)}
    cache_sentiment("JUP", fake, ttl_minutes=-1)
    assert load_cached_sentiment("JUP") is None

def test_cache_clear(tmp_path, monkeypatch):
    monkeypatch.setattr("sentiment.cache.CACHE_DIR", str(tmp_path))
    fake = {"asset": "BTC-USD", "score": 0.2, "timestamp": datetime.now(timezone.utc)}
    cache_sentiment("BTC-USD", fake, ttl_minutes=60)
    clear_cache("BTC-USD")
    assert load_cached_sentiment("BTC-USD") is None


# --- compute_sentiment_score tests ---

_MOCK_RESULT = {"score": 0.25, "confidence": 0.7}

def test_compute_sentiment_score_structure():
    with patch("sentiment.scorer.fetch_onchain_sentiment",    return_value=_MOCK_RESULT), \
         patch("sentiment.scorer.fetch_dex_sentiment",        return_value=_MOCK_RESULT), \
         patch("sentiment.scorer.fetch_news_sentiment",       return_value=_MOCK_RESULT), \
         patch("sentiment.scorer.fetch_twitter_sentiment",    return_value=_MOCK_RESULT), \
         patch("sentiment.scorer._get_fear_greed", return_value={"normalized": 0.2}):
        result = compute_sentiment_score("JUP", include_twitter=True)

    assert "asset"      in result
    assert "score"      in result
    assert "label"      in result
    assert "confidence" in result
    assert "components" in result
    assert "timestamp"  in result
    assert -1.0 <= result["score"] <= 1.0

def test_compute_sentiment_score_all_zeros():
    null = {"score": 0.0, "confidence": 0.5}
    with patch("sentiment.scorer.fetch_onchain_sentiment",    return_value=null), \
         patch("sentiment.scorer.fetch_dex_sentiment",        return_value=null), \
         patch("sentiment.scorer.fetch_news_sentiment",       return_value=null), \
         patch("sentiment.scorer.fetch_twitter_sentiment",    return_value=null), \
         patch("sentiment.scorer._get_fear_greed", return_value={"normalized": 0.0}):
        result = compute_sentiment_score("BTC-USD", include_twitter=True)
    assert result["score"] == pytest.approx(0.0, abs=0.01)

def test_twitter_excluded_by_default():
    null = {"score": 0.0, "confidence": 0.5}
    with patch("sentiment.scorer.fetch_onchain_sentiment",    return_value=null), \
         patch("sentiment.scorer.fetch_dex_sentiment",        return_value=null), \
         patch("sentiment.scorer.fetch_news_sentiment",       return_value=null), \
         patch("sentiment.scorer._get_fear_greed", return_value={"normalized": 0.0}), \
         patch("sentiment.scorer.fetch_twitter_sentiment") as mock_tw:
        compute_sentiment_score("BTC-USD")   # include_twitter defaults to False
    mock_tw.assert_not_called()


# --- Integration tests (live APIs) ---

@pytest.mark.integration
def test_fear_greed_live():
    result = fetch_fear_greed()
    assert 0 <= result["value"] <= 100
    assert -1.0 <= result["normalized"] <= 1.0
    print(f"\nFear & Greed: {result['value']}/100 ({result['label']})")

@pytest.mark.integration
def test_dex_sentiment_live():
    result = fetch_dex_sentiment("JUP")
    assert -1.0 <= result["score"] <= 1.0
    print(f"\nDEX JUP: {result['score']:+.3f} (buys={result.get('buys_1h')}, sells={result.get('sells_1h')})")

@pytest.mark.integration
def test_news_live():
    result = fetch_news_sentiment("BTC-USD")
    assert -1.0 <= result["score"] <= 1.0
    print(f"\nNews BTC: {result['score']:+.3f} ({result['article_count']} articles)")

@pytest.mark.integration
def test_full_score_live():
    result = compute_sentiment_score("SOL-USD", include_twitter=False)
    assert -1.0 <= result["score"] <= 1.0
    print(f"\nFull sentiment SOL: {result['score']:+.3f} ({result['label']})")
    for src, detail in result["components"].items():
        print(f"  {src:<15} score={detail['score']:+.3f}  conf={detail['confidence']:.2f}  weight={detail['weight_used']:.3f}")
