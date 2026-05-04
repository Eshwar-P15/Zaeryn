import os
import time
import joblib
from datetime import datetime, timezone

from utils.logger import get_logger
from config.settings import (
    ALL_ASSETS,
    MODEL_SAVE_DIR,
    MODEL_HORIZON,
)
from models.volatility import VolatilityPredictor
from models.trend import TrendClassifier
from data.storage import load_candles, init_db

logger = get_logger(__name__)


def train_all_models(
    assets: list = None,
    horizon: int = MODEL_HORIZON,
    days_back: int = 180,
    force_retrain: bool = False,
) -> dict:
    """
    Trains VolatilityPredictor and TrendClassifier for every asset.

    Individual asset failures do not stop the batch.
    Assets with insufficient data are skipped with a warning.

    Returns:
        {asset: {"volatility": metrics_or_status, "trend": metrics_or_status}}
    """
    os.makedirs(MODEL_SAVE_DIR, exist_ok=True)

    if assets is None:
        assets = ALL_ASSETS

    results = {}

    for asset in assets:
        logger.info(f"\n{'─'*50}\nTraining: {asset}\n{'─'*50}")
        asset_result = {}
        t0 = time.time()

        # -- Volatility --------------------------------------------------------
        vol_path = VolatilityPredictor.model_path(asset, horizon)
        try:
            if not force_retrain and os.path.exists(vol_path):
                logger.info(f"[{asset}] VolatilityPredictor: loading from disk")
                asset_result["volatility"] = {
                    "loaded_from_disk": True, "path": vol_path
                }
            else:
                predictor = VolatilityPredictor(horizon=horizon)
                metrics   = predictor.train(asset, days_back=days_back)
                predictor.save(vol_path)
                asset_result["volatility"] = metrics

        except RuntimeError as e:
            logger.warning(f"[{asset}] VolatilityPredictor skipped: {e}")
            asset_result["volatility"] = {"skipped": True, "reason": str(e)}
        except Exception as e:
            logger.error(f"[{asset}] VolatilityPredictor failed: {e}")
            asset_result["volatility"] = {"failed": True, "error": str(e)}

        # -- Trend -------------------------------------------------------------
        trend_path = TrendClassifier.model_path(asset, horizon)
        try:
            if not force_retrain and os.path.exists(trend_path):
                logger.info(f"[{asset}] TrendClassifier: loading from disk")
                asset_result["trend"] = {
                    "loaded_from_disk": True, "path": trend_path
                }
            else:
                classifier = TrendClassifier(horizon=horizon)
                metrics    = classifier.train(asset, days_back=days_back)
                classifier.save(trend_path)
                asset_result["trend"] = metrics

        except RuntimeError as e:
            logger.warning(f"[{asset}] TrendClassifier skipped: {e}")
            asset_result["trend"] = {"skipped": True, "reason": str(e)}
        except Exception as e:
            logger.error(f"[{asset}] TrendClassifier failed: {e}")
            asset_result["trend"] = {"failed": True, "error": str(e)}

        asset_result["elapsed_seconds"] = round(time.time() - t0, 1)
        results[asset] = asset_result

    trained = sum(
        1 for r in results.values()
        if "mae" in r.get("volatility", {})
        or r.get("volatility", {}).get("loaded_from_disk")
    )
    logger.info(f"Batch complete: {trained}/{len(assets)} assets have models")
    return results


def evaluate_model_health(asset: str) -> dict:
    """
    Loads saved models for an asset and runs a live prediction.
    Used by Phase 4 risk engine and the train_models validation script.

    Returns:
        {
            "asset":                   str,
            "models_exist":            bool,
            "volatility_prediction":   float | None,
            "trend":                   dict | None,
            "vol_model_age_hours":     float | None,
            "trend_model_age_hours":   float | None,
        }
    """
    result = {
        "asset":                 asset,
        "models_exist":          False,
        "volatility_prediction": None,
        "trend":                 None,
        "vol_model_age_hours":   None,
        "trend_model_age_hours": None,
    }

    vol_path   = VolatilityPredictor.model_path(asset)
    trend_path = TrendClassifier.model_path(asset)

    if not (os.path.exists(vol_path) and os.path.exists(trend_path)):
        return result

    result["models_exist"] = True

    try:
        candles = load_candles(asset, "1h", days_back=90)
        if candles.empty or len(candles) < 60:
            logger.warning(f"evaluate_model_health [{asset}]: insufficient candles")
            return result

        vol_model = VolatilityPredictor()
        vol_model.load(vol_path)
        result["volatility_prediction"] = vol_model.predict(candles)

        vol_payload = joblib.load(vol_path)
        if vol_payload.get("trained_at"):
            age = (datetime.now(timezone.utc) - vol_payload["trained_at"]).total_seconds() / 3600
            result["vol_model_age_hours"] = round(age, 1)

        trend_model = TrendClassifier()
        trend_model.load(trend_path)
        result["trend"] = trend_model.predict_proba(candles)

        trend_payload = joblib.load(trend_path)
        if trend_payload.get("trained_at"):
            age = (datetime.now(timezone.utc) - trend_payload["trained_at"]).total_seconds() / 3600
            result["trend_model_age_hours"] = round(age, 1)

    except Exception as e:
        logger.error(f"evaluate_model_health [{asset}]: {e}")

    return result


def should_retrain(asset: str, days_threshold: int = 7) -> bool:
    """
    Returns True if saved models are older than days_threshold.
    Phase 6 calls this to decide whether to retrain.
    """
    path = VolatilityPredictor.model_path(asset)
    if not os.path.exists(path):
        return True
    try:
        payload    = joblib.load(path)
        trained_at = payload.get("trained_at")
        if trained_at is None:
            return True
        return (datetime.now(timezone.utc) - trained_at).days >= days_threshold
    except Exception:
        return True
