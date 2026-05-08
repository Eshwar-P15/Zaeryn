import os
import numpy as np
import pandas as pd
from dataclasses import dataclass
from abc import ABC, abstractmethod

from utils.logger import get_logger
from config.settings import MODEL_HORIZON

logger = get_logger(__name__)


@dataclass
class Signal:
    action:     str     # "BUY" | "SELL" | "HOLD"
    confidence: float
    reason:     str


class BaseStrategy(ABC):
    name: str = "BaseStrategy"

    @abstractmethod
    def generate_signal(self, window: pd.DataFrame) -> Signal:
        raise NotImplementedError


class MACDCrossStrategy(BaseStrategy):
    name = "MACD Cross"

    def generate_signal(self, window: pd.DataFrame) -> Signal:
        if len(window) < 2:
            return Signal("HOLD", 0.0, "insufficient data")

        prev = window.iloc[-2]
        curr = window.iloc[-1]

        for col in ["macd", "macd_signal"]:
            if pd.isna(curr.get(col)) or pd.isna(prev.get(col)):
                return Signal("HOLD", 0.0, f"NaN in {col}")

        was_below = prev["macd"] < prev["macd_signal"]
        now_above = curr["macd"] > curr["macd_signal"]
        was_above = prev["macd"] > prev["macd_signal"]
        now_below = curr["macd"] < curr["macd_signal"]

        if was_below and now_above:
            gap = abs(curr["macd"] - curr["macd_signal"])
            confidence = min(1.0, gap / (abs(curr["macd"]) + 1e-8))
            return Signal("BUY", confidence, "MACD bullish crossover")

        if was_above and now_below:
            return Signal("SELL", 1.0, "MACD bearish crossover")

        return Signal("HOLD", 0.0, "no crossover")


class RSIMeanReversionStrategy(BaseStrategy):
    name = "RSI Mean Reversion"

    def __init__(self, oversold: float = 30.0, overbought: float = 70.0):
        self.oversold   = oversold
        self.overbought = overbought

    def generate_signal(self, window: pd.DataFrame) -> Signal:
        if window.empty:
            return Signal("HOLD", 0.0, "empty window")

        rsi = window["rsi_14"].iloc[-1]
        if pd.isna(rsi):
            return Signal("HOLD", 0.0, "RSI not available")

        if rsi < self.oversold:
            confidence = (self.oversold - rsi) / self.oversold
            return Signal("BUY", confidence, f"RSI={rsi:.1f} oversold (<{self.oversold})")

        if rsi > self.overbought:
            return Signal("SELL", 1.0, f"RSI={rsi:.1f} overbought (>{self.overbought})")

        return Signal("HOLD", 0.0, f"RSI={rsi:.1f} neutral")


class BollingerBandStrategy(BaseStrategy):
    name = "Bollinger Band"

    def __init__(self, lower_threshold: float = 0.05, upper_threshold: float = 0.95):
        self.lower = lower_threshold
        self.upper = upper_threshold

    def generate_signal(self, window: pd.DataFrame) -> Signal:
        if window.empty:
            return Signal("HOLD", 0.0, "empty window")

        bb_pos = window["bb_position"].iloc[-1]
        if pd.isna(bb_pos):
            return Signal("HOLD", 0.0, "Bollinger position not available")

        if bb_pos < self.lower:
            confidence = (self.lower - bb_pos) / self.lower
            return Signal("BUY", min(1.0, confidence), f"BB position={bb_pos:.3f} at lower band")

        if bb_pos > self.upper:
            return Signal("SELL", 1.0, f"BB position={bb_pos:.3f} at upper band")

        return Signal("HOLD", 0.0, f"BB position={bb_pos:.3f} neutral")


class ZAERYNMLStrategy(BaseStrategy):
    name = "ZAERYN ML Composite"

    def __init__(
        self,
        asset: str,
        confidence_threshold: float = 0.30,
        buy_risk_threshold:   float = 50.0,
        sell_risk_threshold:  float = 65.0,
    ):
        self.asset                = asset
        self.confidence_threshold = confidence_threshold
        self.buy_risk_threshold   = buy_risk_threshold
        self.sell_risk_threshold  = sell_risk_threshold
        self._trend_model         = None
        self._fallback            = MACDCrossStrategy()
        self._model_loaded        = False
        self._use_fallback        = False

        self._load_model()

    def _load_model(self) -> None:
        from models.trend import TrendClassifier

        path = TrendClassifier.model_path(self.asset)
        if not os.path.exists(path):
            logger.warning(
                f"ZAERYNMLStrategy: No model for {self.asset} — falling back to MACD Cross"
            )
            self._use_fallback = True
            return

        try:
            self._trend_model = TrendClassifier()
            self._trend_model.load(path)
            self._model_loaded = True
            logger.info(f"ZAERYNMLStrategy: Loaded TrendClassifier for {self.asset}")
        except Exception as e:
            logger.warning(
                f"ZAERYNMLStrategy: Failed to load model for {self.asset}: {e} "
                f"— falling back to MACD Cross"
            )
            self._use_fallback = True

    @staticmethod
    def _backtest_risk_score(trend_confidence: float, rsi: float | None) -> float:
        trend_uncertainty = 1.0 - trend_confidence
        if rsi is not None and not np.isnan(rsi):
            momentum_risk = abs(rsi - 50.0) / 50.0
        else:
            momentum_risk = 0.0

        raw = trend_uncertainty * 0.6 + momentum_risk * 0.4
        return round(max(0.0, min(100.0, raw * 100.0)), 2)

    def generate_signal(self, window: pd.DataFrame) -> Signal:
        if self._use_fallback:
            return self._fallback.generate_signal(window)

        if not self._model_loaded or window.empty:
            return Signal("HOLD", 0.0, "model not loaded or empty window")

        if len(window) < 60:
            return Signal("HOLD", 0.0, "insufficient history for ML features")

        rsi = None
        rsi_val = window["rsi_14"].iloc[-1]
        if not pd.isna(rsi_val):
            rsi = float(rsi_val)

        try:
            trend_result = self._trend_model.predict_proba(window)
        except Exception as e:
            logger.debug(f"ZAERYNMLStrategy predict_proba failed: {e}")
            return Signal("HOLD", 0.0, f"prediction failed: {e}")

        direction  = trend_result.get("direction", "UNCERTAIN")
        confidence = float(trend_result.get("confidence", 0.0))
        risk_score = self._backtest_risk_score(confidence, rsi)

        if (
            direction == "UP"
            and confidence >= self.confidence_threshold
            and risk_score < self.buy_risk_threshold
        ):
            return Signal(
                "BUY",
                confidence,
                f"ML UP conf={confidence:.3f} risk={risk_score:.1f} rsi={rsi}",
            )

        if direction == "DOWN" or risk_score > self.sell_risk_threshold:
            reason = (
                "ML DOWN" if direction == "DOWN"
                else f"risk={risk_score:.1f}>{self.sell_risk_threshold}"
            )
            return Signal("SELL", confidence, reason)

        return Signal(
            "HOLD",
            confidence,
            f"ML {direction} conf={confidence:.3f} risk={risk_score:.1f}",
        )
