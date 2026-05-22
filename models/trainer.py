import json
import os
import time
from datetime import UTC, datetime

import joblib
import mlflow

from config.settings import (
    ALL_ASSETS,
    FEATURE_COLUMNS,
    MODEL_HORIZON,
    MODEL_SAVE_DIR,
    MODEL_TEST_SIZE,
    RF_PARAMS,
    RF_PARAMS_BY_ASSET,
    XGB_PARAMS,
    XGB_PARAMS_BY_ASSET,
)
from data.storage import load_candles
from models.features import build_feature_matrix
from models.trend import TrendClassifier
from models.volatility import VolatilityPredictor
from utils.logger import get_logger
from utils.mlflow_runner import (
    compute_dataset_hash,
    get_git_sha,
    get_library_versions,
)

logger = get_logger(__name__)

MLFLOW_EXPERIMENT = "zaeryn_training"


def _log_run_params(
    *,
    asset: str,
    horizon: int,
    days_back: int,
    dataset_hash: str,
    model_type: str,
    hyperparams: dict,
    train_rows: int,
    test_rows: int,
) -> None:
    mlflow.log_params(
        {
            "asset": asset,
            "horizon": horizon,
            "history_days": days_back,
            "train_rows": train_rows,
            "test_rows": test_rows,
            "model_type": model_type,
            "dataset_hash": dataset_hash,
            "git_sha": get_git_sha(),
            "feature_columns": json.dumps(FEATURE_COLUMNS),
            "hyperparameters": json.dumps(hyperparams, default=str),
        }
    )
    for lib, ver in get_library_versions().items():
        mlflow.log_param(f"lib_{lib}", ver)


def _log_run_metrics(metrics: dict) -> None:
    """Log every numeric field in the metrics dict. Booleans and strings are skipped."""
    for key, value in metrics.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            mlflow.log_metric(key, float(value))


def _preflight_feature_matrix(asset: str, horizon: int, days_back: int) -> tuple[str, int, int]:
    """Build the feature matrix once for dataset hash + split sizes.

    Returns (dataset_hash, train_rows, test_rows). Falls back to sentinel values
    if the matrix cannot be built — training will then raise its own RuntimeError
    and be caught by the outer skipped/failed handler.
    """
    try:
        result = build_feature_matrix(asset, horizon=horizon, days_back=days_back)
    except Exception as exc:
        logger.warning(f"[{asset}] feature matrix preflight failed: {exc}")
        return "preflight-failed", 0, 0

    if result is None:
        return "insufficient-data", 0, 0

    X, _, _ = result
    n = len(X)
    split = int(n * (1 - MODEL_TEST_SIZE))
    return compute_dataset_hash(X), split, n - split


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
    Each actually-trained model is logged as its own MLflow run (so two runs
    per asset when both models train). Models loaded from disk do not create
    a run — there is no new training pass to record.

    Returns:
        {asset: {"volatility": metrics_or_status, "trend": metrics_or_status}}
    """
    os.makedirs(MODEL_SAVE_DIR, exist_ok=True)

    if assets is None:
        assets = ALL_ASSETS

    results = {}

    for asset in assets:
        logger.info(f"\n{'─' * 50}\nTraining: {asset}\n{'─' * 50}")
        asset_result = {}
        t0 = time.time()

        dataset_hash, train_rows, test_rows = _preflight_feature_matrix(asset, horizon, days_back)

        # -- Volatility --------------------------------------------------------
        vol_path = VolatilityPredictor.model_path(asset, horizon)
        try:
            if not force_retrain and os.path.exists(vol_path):
                logger.info(f"[{asset}] VolatilityPredictor: loading from disk")
                asset_result["volatility"] = {"loaded_from_disk": True, "path": vol_path}
            else:
                with mlflow.start_run(run_name=f"{asset}_{horizon}h_volatility"):
                    _log_run_params(
                        asset=asset,
                        horizon=horizon,
                        days_back=days_back,
                        dataset_hash=dataset_hash,
                        model_type="XGB",
                        hyperparams=XGB_PARAMS_BY_ASSET.get(asset, XGB_PARAMS),
                        train_rows=train_rows,
                        test_rows=test_rows,
                    )
                    try:
                        predictor = VolatilityPredictor(horizon=horizon)
                        metrics = predictor.train(asset, days_back=days_back)
                        saved_path = predictor.save(vol_path)
                        _log_run_metrics(metrics)
                        mlflow.log_artifact(saved_path)
                        asset_result["volatility"] = metrics
                    except Exception:
                        mlflow.set_tag("status", "failed")
                        raise

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
                asset_result["trend"] = {"loaded_from_disk": True, "path": trend_path}
            else:
                with mlflow.start_run(run_name=f"{asset}_{horizon}h_trend"):
                    _log_run_params(
                        asset=asset,
                        horizon=horizon,
                        days_back=days_back,
                        dataset_hash=dataset_hash,
                        model_type="RF",
                        hyperparams=RF_PARAMS_BY_ASSET.get(asset, RF_PARAMS),
                        train_rows=train_rows,
                        test_rows=test_rows,
                    )
                    try:
                        classifier = TrendClassifier(horizon=horizon)
                        metrics = classifier.train(asset, days_back=days_back)
                        saved_path = classifier.save(trend_path)
                        _log_run_metrics(metrics)
                        mlflow.log_artifact(saved_path)
                        asset_result["trend"] = metrics
                    except Exception:
                        mlflow.set_tag("status", "failed")
                        raise

        except RuntimeError as e:
            logger.warning(f"[{asset}] TrendClassifier skipped: {e}")
            asset_result["trend"] = {"skipped": True, "reason": str(e)}
        except Exception as e:
            logger.error(f"[{asset}] TrendClassifier failed: {e}")
            asset_result["trend"] = {"failed": True, "error": str(e)}

        asset_result["elapsed_seconds"] = round(time.time() - t0, 1)
        results[asset] = asset_result

    trained = sum(
        1
        for r in results.values()
        if "mae" in r.get("volatility", {}) or r.get("volatility", {}).get("loaded_from_disk")
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
        "asset": asset,
        "models_exist": False,
        "volatility_prediction": None,
        "trend": None,
        "vol_model_age_hours": None,
        "trend_model_age_hours": None,
    }

    vol_path = VolatilityPredictor.model_path(asset)
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
            age = (datetime.now(UTC) - vol_payload["trained_at"]).total_seconds() / 3600
            result["vol_model_age_hours"] = round(age, 1)

        trend_model = TrendClassifier()
        trend_model.load(trend_path)
        result["trend"] = trend_model.predict_proba(candles)

        trend_payload = joblib.load(trend_path)
        if trend_payload.get("trained_at"):
            age = (datetime.now(UTC) - trend_payload["trained_at"]).total_seconds() / 3600
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
        payload = joblib.load(path)
        trained_at = payload.get("trained_at")
        if trained_at is None:
            return True
        return (datetime.now(UTC) - trained_at).days >= days_threshold
    except Exception:
        return True
