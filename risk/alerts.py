import os
import logging
import numpy as np
from datetime import datetime, timezone
from dataclasses import dataclass, field

from utils.logger import get_logger
from config.settings import (
    LOGS_DIR,
    ALERTS_LOG_FILE,
    ALERT_RISK_EXTREME,
    ALERT_SENTIMENT_CRASH,
    ALERT_VOL_SPIKE_FACTOR,
    ALERT_PRICE_DROP_PCT,
)

logger = get_logger(__name__)

_alert_logger: logging.Logger | None = None


def _get_alert_logger() -> logging.Logger:
    global _alert_logger
    if _alert_logger is not None:
        return _alert_logger

    os.makedirs(LOGS_DIR, exist_ok=True)
    al = logging.getLogger("zaeryn.alerts")

    if not al.handlers:
        al.setLevel(logging.INFO)
        fh = logging.FileHandler(ALERTS_LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        al.addHandler(fh)
        al.propagate = False

    _alert_logger = al
    return _alert_logger


@dataclass
class Alert:
    asset:     str
    type:      str
    severity:  str
    value:     float
    threshold: float
    message:   str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "asset":     self.asset,
            "type":      self.type,
            "severity":  self.severity,
            "value":     round(self.value, 4),
            "threshold": self.threshold,
            "message":   self.message,
            "timestamp": self.timestamp.isoformat(),
        }

    def __str__(self) -> str:
        return (
            f"{self.severity:<8} {self.asset:<10} "
            f"{self.type:<20} value={self.value:.4f} "
            f"threshold={self.threshold}  \"{self.message}\""
        )


def log_alert(alert: Alert) -> None:
    """Rule 10: writes to dedicated alerts.log AND main logger."""
    _get_alert_logger().warning(str(alert))

    if alert.severity == "CRITICAL":
        logger.warning(f"🚨 ALERT [{alert.type}] {alert.asset}: {alert.message}")
    else:
        logger.warning(f"⚠  ALERT [{alert.type}] {alert.asset}: {alert.message}")


def check_alerts(
    asset: str,
    risk_data: dict,
    candles=None,
) -> list[Alert]:
    """
    Checks all four alert conditions for a single asset.
    Calls log_alert() for each triggered alert.
    """
    triggered = []

    # Alert 1: Extreme risk score
    score = risk_data.get("score", 0.0)
    if score >= ALERT_RISK_EXTREME:
        alert = Alert(
            asset=asset,
            type="RISK_EXTREME",
            severity="CRITICAL",
            value=score,
            threshold=ALERT_RISK_EXTREME,
            message=f"Risk score {score:.1f}/100 exceeds extreme threshold {ALERT_RISK_EXTREME}",
        )
        log_alert(alert)
        triggered.append(alert)

    # Alert 2: Sentiment crash
    sent_risk = risk_data.get("components", {}).get("sentiment", {}).get("risk", 0.5)
    sentiment_score = 1.0 - (2.0 * sent_risk)
    if sentiment_score <= ALERT_SENTIMENT_CRASH:
        alert = Alert(
            asset=asset,
            type="SENTIMENT_CRASH",
            severity="WARNING",
            value=sentiment_score,
            threshold=ALERT_SENTIMENT_CRASH,
            message=(
                f"Sentiment {sentiment_score:.3f} below crash threshold "
                f"{ALERT_SENTIMENT_CRASH}"
            ),
        )
        log_alert(alert)
        triggered.append(alert)

    # Alert 3: Volatility spike
    raw_vol = risk_data.get("components", {}).get("volatility", {}).get("raw_vol")
    if raw_vol is not None and candles is not None and not candles.empty and len(candles) >= 30:
        hist_log_returns = (
            candles["close"].pct_change().apply(
                lambda x: np.log1p(x) if x > -1 else 0
            )
        )
        avg_vol_30d = float(hist_log_returns.rolling(30).std().dropna().mean()) * np.sqrt(8760)
        if avg_vol_30d > 0 and raw_vol > avg_vol_30d * ALERT_VOL_SPIKE_FACTOR:
            alert = Alert(
                asset=asset,
                type="VOL_SPIKE",
                severity="WARNING",
                value=raw_vol,
                threshold=avg_vol_30d * ALERT_VOL_SPIKE_FACTOR,
                message=(
                    f"Predicted vol {raw_vol:.3f} is "
                    f"{raw_vol/avg_vol_30d:.1f}x the 30d average ({avg_vol_30d:.3f})"
                ),
            )
            log_alert(alert)
            triggered.append(alert)

    # Alert 4: Price drop in last hour
    if candles is not None and not candles.empty and len(candles) >= 2:
        latest_close   = float(candles["close"].iloc[-1])
        hour_ago_close = float(candles["close"].iloc[-2])
        if hour_ago_close > 0:
            pct_change = ((latest_close - hour_ago_close) / hour_ago_close) * 100
            if pct_change <= ALERT_PRICE_DROP_PCT:
                alert = Alert(
                    asset=asset,
                    type="PRICE_DROP",
                    severity="WARNING",
                    value=pct_change,
                    threshold=ALERT_PRICE_DROP_PCT,
                    message=(
                        f"Price dropped {pct_change:.2f}% in last hour "
                        f"(${hour_ago_close:.4f} → ${latest_close:.4f})"
                    ),
                )
                log_alert(alert)
                triggered.append(alert)

    return triggered


def check_all_assets(risk_results: dict, candles_map: dict = None) -> dict[str, list[Alert]]:
    """
    Runs check_alerts() for all assets in risk_results.
    Returns {asset: [Alert, ...]} — assets with no alerts have empty lists.
    """
    all_alerts = {}
    total = 0

    for asset, risk_data in risk_results.items():
        candles = (candles_map or {}).get(asset)
        alerts  = check_alerts(asset, risk_data, candles=candles)
        all_alerts[asset] = alerts
        total += len(alerts)

    if total > 0:
        logger.warning(f"Alerts: {total} triggered across {len(risk_results)} assets")
    else:
        logger.info("Alerts: none triggered")

    return all_alerts
