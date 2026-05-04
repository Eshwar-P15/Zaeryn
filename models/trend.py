import os
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, log_loss,
)

from utils.logger import get_logger
from config.settings import (
    MODEL_SAVE_DIR,
    MODEL_HORIZON,
    MODEL_TEST_SIZE,
    FEATURE_COLUMNS,
    RF_PARAMS,
)
from models.features import build_feature_matrix

logger = get_logger(__name__)


class TrendClassifier:
    """
    Random Forest trend direction classifier.

    Predicts probability of price being higher MODEL_HORIZON candles from now.
    Always call predict_proba() — never predict() directly in production.
    The probability output is what Phase 4 uses for position sizing.
    """

    # How far from 0.5 the probability must be to take a directional position
    UNCERTAINTY_THRESHOLD = 0.15

    def __init__(self, horizon: int = MODEL_HORIZON):
        self.horizon               = horizon
        self.model                 = None
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
        logger.info(f"Training TrendClassifier: {asset}")

        result = build_feature_matrix(
            asset, horizon=self.horizon, days_back=days_back, conn=conn
        )
        if result is None:
            raise RuntimeError(f"Insufficient data for {asset}")

        X, _, y_dir = result

        # Drop any remaining NaN in target — defensive
        valid = y_dir.notna()
        X     = X[valid].reset_index(drop=True)
        y_dir = y_dir[valid].reset_index(drop=True)

        # Chronological split — NEVER shuffle (Rule 2)
        split_idx = int(len(X) * (1 - test_size))
        if split_idx < 50:
            raise RuntimeError(
                f"[{asset}] training set too small after split: {split_idx} rows"
            )

        X_train = X.iloc[:split_idx]
        X_test  = X.iloc[split_idx:]
        y_train = y_dir.iloc[:split_idx]
        y_test  = y_dir.iloc[split_idx:]

        up_pct = float(y_train.mean() * 100)
        logger.info(
            f"[{asset}] split: train={len(X_train)}, test={len(X_test)}, "
            f"UP%={up_pct:.1f}% in training set"
        )

        self.model = RandomForestClassifier(**RF_PARAMS)
        self.model.fit(X_train, y_train.astype(int))

        y_pred      = self.model.predict(X_test)
        y_pred_prob = self.model.predict_proba(X_test)[:, 1]

        accuracy  = float(accuracy_score(y_test.astype(int), y_pred))
        precision = float(precision_score(y_test.astype(int), y_pred, zero_division=0))
        recall    = float(recall_score(y_test.astype(int), y_pred, zero_division=0))
        f1        = float(f1_score(y_test.astype(int), y_pred, zero_division=0))
        auc       = float(roc_auc_score(y_test.astype(int), y_pred_prob))
        logloss   = float(log_loss(y_test.astype(int), y_pred_prob))

        importances = dict(zip(self.feature_columns, self.model.feature_importances_))
        self.feature_importances_ = dict(
            sorted(importances.items(), key=lambda x: x[1], reverse=True)[:10]
        )

        self.is_trained = True
        self.trained_at = datetime.now(timezone.utc)

        metrics = {
            "asset":          asset,
            "model":          "TrendClassifier",
            "train_rows":     len(X_train),
            "test_rows":      len(X_test),
            "accuracy":       round(accuracy,  4),
            "precision":      round(precision, 4),
            "recall":         round(recall,    4),
            "f1":             round(f1,        4),
            "auc":            round(auc,       4),
            "log_loss":       round(logloss,   4),
            "train_up_pct":   round(up_pct,    1),
            "top_features":   list(self.feature_importances_.keys()),
            "trained_at":     self.trained_at.isoformat(),
        }

        logger.info(
            f"[{asset}] TrendClassifier: "
            f"ACC={accuracy:.3f}  F1={f1:.3f}  AUC={auc:.3f}"
        )
        return metrics

    def predict_proba(self, df: pd.DataFrame) -> dict:
        """
        Returns probability of UP and DOWN for the latest candle.

        Args:
            df: recent OHLCV DataFrame (at least 60 rows for valid features)

        Returns:
            {
                "up_probability":   float,  # 0-1
                "down_probability": float,  # 0-1
                "direction":        str,    # "UP" | "DOWN" | "UNCERTAIN"
                "confidence":       float,  # 0=coin flip, 1=maximum certainty
            }
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
            raise RuntimeError("No valid rows after feature processing")

        latest = df_proc[self.feature_columns].iloc[[-1]]
        probs  = self.model.predict_proba(latest)[0]

        # Guard: RF trained on single class returns only one probability column
        if len(probs) >= 2:
            up_prob = float(probs[1])
        else:
            up_prob = float(probs[0]) if self.model.classes_[0] == 1 else 1.0 - float(probs[0])

        down_prob  = 1.0 - up_prob
        confidence = min(1.0, abs(up_prob - 0.5) * 2)

        if abs(up_prob - 0.5) < self.UNCERTAINTY_THRESHOLD:
            direction = "UNCERTAIN"
        elif up_prob > 0.5:
            direction = "UP"
        else:
            direction = "DOWN"

        return {
            "up_probability":   round(up_prob,    4),
            "down_probability": round(down_prob,  4),
            "direction":        direction,
            "confidence":       round(confidence, 4),
        }

    def save(self, path: str = None) -> str:
        if not self.is_trained:
            raise RuntimeError("Cannot save — model not trained")

        if path is None:
            os.makedirs(MODEL_SAVE_DIR, exist_ok=True)
            safe = self.asset.replace("-", "_")
            path = os.path.join(MODEL_SAVE_DIR, f"trend_{safe}_{self.horizon}h.pkl")

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        joblib.dump({
            "model":               self.model,
            "feature_columns":     self.feature_columns,
            "horizon":             self.horizon,
            "asset":               self.asset,
            "trained_at":          self.trained_at,
            "feature_importances": self.feature_importances_,
        }, path)

        logger.info(f"TrendClassifier saved → {path}")
        return path

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model not found: {path}")

        p = joblib.load(path)
        self.model                = p["model"]
        self.feature_columns      = p["feature_columns"]
        self.horizon              = p["horizon"]
        self.asset                = p["asset"]
        self.trained_at           = p.get("trained_at")
        self.feature_importances_ = p.get("feature_importances", {})
        self.is_trained           = True
        logger.info(f"TrendClassifier loaded → {path}")

    @classmethod
    def load_or_train(
        cls,
        asset: str,
        horizon: int = MODEL_HORIZON,
        force_retrain: bool = False,
    ) -> "TrendClassifier":
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
        return os.path.join(MODEL_SAVE_DIR, f"trend_{safe}_{horizon}h.pkl")
