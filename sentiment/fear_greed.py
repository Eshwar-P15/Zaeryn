import time
import requests
from datetime import datetime, timezone
from utils.logger import get_logger
from config.settings import REQUEST_TIMEOUT, REQUEST_RETRY_ATTEMPTS, REQUEST_RETRY_DELAYS

logger = get_logger(__name__)

FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"

FEAR_GREED_LABELS = {
    (0,  25): "Extreme Fear",
    (25, 45): "Fear",
    (45, 55): "Neutral",
    (55, 75): "Greed",
    (75, 100): "Extreme Greed",
}


def fetch_fear_greed() -> dict:
    """
    Fetches the Crypto Fear & Greed Index. Free, no auth, updates once per day.

    Returns normalized score: 0 -> -1.0 (extreme fear), 100 -> +1.0 (extreme greed).
    Returns neutral default if all retries fail.
    """
    last_error = None

    for attempt in range(REQUEST_RETRY_ATTEMPTS):
        if attempt > 0:
            time.sleep(REQUEST_RETRY_DELAYS[attempt - 1])
        try:
            response = requests.get(FEAR_GREED_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            entry = data["data"][0]
            value = int(entry["value"])
            normalized = (value / 50.0) - 1.0

            label = "Neutral"
            for (low, high), lbl in FEAR_GREED_LABELS.items():
                if low <= value <= high:
                    label = lbl
                    break

            result = {
                "value":      value,
                "label":      label,
                "normalized": round(normalized, 4),
                "timestamp":  datetime.now(timezone.utc),
                "source":     "fear_greed",
            }
            logger.info(f"Fear & Greed: {value}/100 ({label}) -> {normalized:+.3f}")
            return result

        except Exception as e:
            last_error = e
            logger.warning(f"Fear & Greed fetch failed (attempt {attempt + 1}): {e}")

    logger.error(f"Fear & Greed: all retries failed. Returning neutral. Error: {last_error}")
    return {
        "value":      50,
        "label":      "Neutral",
        "normalized": 0.0,
        "timestamp":  datetime.now(timezone.utc),
        "source":     "fear_greed",
        "error":      str(last_error),
    }
