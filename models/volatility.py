import os
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

from utils.logger import get_logger
from config.settings import (
    MODEL_SAVE_DIR,
    MODEL_HORIZON,
    MODEL_TEST_SIZE,
    FEATURE_COLUMNS,
    XGB_PARAMS,
)
from models.features import build_feature_matrix

logger = get_logger(__name__)


class VolatilityPredictor:
    """
    XGBoost-based volatility predictor.

    Predicts annualized realized vol MODEL_HORIZON candles ahead.
    Uses chronological train/test split — never shuffled (Rule 2).
    """

    def __init__(self, horizon: int = MODEL_HORIZON):
        self.horizon               = horizon
        self.model                 = None
        self.scaler                = None   # stored for Phase 7 LSTM compatibility
        self.feature_columns       = FEATURE_COLUMNS
        self.is_trained            = False
        self.asset                 = None
        self.trained_at            = None
        self.feature_importances_  = {}

    def train(
        self,
        asset: str,
        days_back: int = 180,
        test_size: float = MODEL_TEST_SIZE,
        conn=None,
    ) -> dict:
        """
        Trains on historical candles for one asset.
        Returns metrics dict. Raises RuntimeError if insufficient data.
        """
        self.asset = asset
        logger.info(f"Training VolatilityPredictor: {asset}")

        result = build_feature_matrix(
            asset, horizon=self.horizon, days_back=days_back, conn=conn
        )
        if result is None:
            raise RuntimeError(
                f"Insufficient data for {asset} — cannot train VolatilityPredictor"
            )

        X, y_vol, _ = result

        # Chronological split — NEVER shuffle (Rule 2)
        split_idx = int(len(X) * (1 - test_size))
        if split_idx < 50:
            raise RuntimeError(
                f"[{asset}] training set too small after split: {split_idx} rows"
            )

        X_train = X.iloc[:split_idx]
        X_test  = X.iloc[split_idx:]
        y_train = y_vol.iloc[:split_idx]
        y_test  = y_vol.iloc[split_idx:]

        logger.info(
            f"[{asset}] split: train={len(X_train)}, test={len(X_test)} (chronological)"
        )

        # Fit scaler on training data ONLY — stored for Phase 7 LSTM
        self.scaler = StandardScaler()
        self.scaler.fit(X_train)

        self.model = XGBRegressor(**XGB_PARAMS)
        self.model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

        y_pred = self.model.predict(X_test)

        mae  = float(mean_absolute_error(y_test, y_pred))
        rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
        r2   = float(r2_score(y_test, y_pred))

        mape = None
        if (y_test > 0).all():
            mape = float(np.mean(np.abs((y_test - y_pred) / y_test)) * 100)

        importances = dict(zip(self.feature_columns, self.model.feature_importances_))
        self.feature_importances_ = dict(
            sorted(importances.items(), key=lambda x: x[1], reverse=True)[:10]
        )

        self.is_trained = True
        self.trained_at = datetime.now(timezone.utc)

        metrics = {
            "asset":        asset,
            "model":        "VolatilityPredictor",
            "train_rows":   len(X_train),
            "test_rows":    len(X_test),
            "mae":          round(mae,  6),
            "rmse":         round(rmse, 6),
            "r2":           round(r2,   4),
            "mape":         round(mape, 2) if mape is not None else None,
            "top_features": list(self.feature_importances_.keys()),
            "trained_at":   self.trained_at.isoformat(),
        }

        logger.info(
            f"[{asset}] VolatilityPredictor: "
            f"MAE={mae:.4f}  RMSE={rmse:.4f}  R²={r2:.4f}"
        )
        return metrics

    def predict(self, df: pd.DataFrame) -> float:
        """
        Predicts volatility for the most recent candle in df.

        df must have raw OHLCV columns. The feature pipeline runs internally.
        Requires at least 60 rows for rolling indicators to be valid.

        Returns float: predicted annualized volatility (e.g. 0.85 = 85%).
        """
        if not self.is_trained:
            raise RuntimeError("Model not trained. Call .train() or .load() first.")

        from data.cleaner import clean_ohlcv, normalize_price_data
        from models.features import compute_technical_indicators

        df_proc = clean_ohlcv(df.copy())
        df_proc = normalize_price_data(df_proc)
        df_proc = compute_technical_indicators(df_proc)
        df_proc = df_proc.dropna(subset=self.feature_columns)

        if df_proc.empty:
            raise RuntimeError(
                "No valid rows after feature processing — provide more history (>=60 rows)"
            )

        latest     = df_proc[self.feature_columns].iloc[[-1]]
        prediction = float(self.model.predict(latest)[0])
        return max(0.0, prediction)

    def save(self, path: str = None) -> str:
        """Saves model, scaler, and metadata to disk. Returns path."""
        if not self.is_trained:
            raise RuntimeError("Cannot save — model not trained")

        if path is None:
            os.makedirs(MODEL_SAVE_DIR, exist_ok=True)
            safe = self.asset.replace("-", "_")
            path = os.path.join(MODEL_SAVE_DIR, f"volatility_{safe}_{self.horizon}h.pkl")

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        joblib.dump({
            "model":               self.model,
            "scaler":              self.scaler,
            "feature_columns":     self.feature_columns,
            "horizon":             self.horizon,
            "asset":               self.asset,
            "trained_at":          self.trained_at,
            "feature_importances": self.feature_importances_,
        }, path)

        logger.info(f"VolatilityPredictor saved → {path}")
        return path

    def load(self, path: str) -> None:
        """Loads model from disk."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model not found: {path}")

        p = joblib.load(path)
        self.model                = p["model"]
        self.scaler               = p.get("scaler")
        self.feature_columns      = p["feature_columns"]
        self.horizon              = p["horizon"]
        self.asset                = p["asset"]
        self.trained_at           = p.get("trained_at")
        self.feature_importances_ = p.get("feature_importances", {})
        self.is_trained           = True
        logger.info(f"VolatilityPredictor loaded → {path}")

    @classmethod
    def load_or_train(
        cls,
        asset: str,
        horizon: int = MODEL_HORIZON,
        force_retrain: bool = False,
    ) -> "VolatilityPredictor":
        path = cls.model_path(asset, horizon)
        obj  = cls(horizon=horizon)
        if not force_retrain and os.path.exists(path):
            obj.load(path)
        else:
            obj.train(asset)
            obj.save(path)
        return obj

    @staticmethod
    def model_path(asset: str, horizon: int = MODEL_HORIZON) -> str:
        safe = asset.replace("-", "_")
        return os.path.join(MODEL_SAVE_DIR, f"volatility_{safe}_{horizon}h.pkl")
