"""Typed configuration models for ZAERYN.

Internal module. Public API lives in :mod:`config.settings`, which instantiates
the classes defined here and re-exports their values under the legacy flat names
the rest of the codebase imports.

Env-var loading is intentionally locked down via a `ZAERYN_` prefix so unrelated
process env vars (`DB_PATH`, `LOGS_DIR`, ...) cannot accidentally override config.
The single exception is :class:`BirdeyeSettings`, which explicitly reads
`BIRDEYE_API_KEY` via a validation alias to preserve the original behaviour.
"""

from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# Inert config: env_prefix that won't collide with anything real, no .env file.
_INERT = SettingsConfigDict(env_prefix="ZAERYN_", env_file=None, extra="ignore")


# -- Data / paths / HTTP -------------------------------------------------------


class DataSettings(BaseSettings):
    model_config = _INERT

    project_root: Path = PROJECT_ROOT
    db_path: Path = PROJECT_ROOT / "zaeryn.db"
    logs_dir: Path = PROJECT_ROOT / "logs"
    cache_dir: Path = PROJECT_ROOT / "cache"

    coinbase_exchange_url: str = "https://api.exchange.coinbase.com"
    coinbase_public_url: str = "https://api.coinbase.com/v2"
    coinbase_max_candles_per_request: int = 300
    default_granularity: str = "1h"
    history_days: int = 365

    request_timeout: int = 10
    request_retry_attempts: int = 3
    request_retry_delays: list[int] = Field(default_factory=lambda: [1, 2, 4])
    candle_request_sleep: float = 0.35


# -- Asset universe ------------------------------------------------------------


class AssetSettings(BaseSettings):
    model_config = _INERT

    crypto_coinbase: list[str] = Field(
        default_factory=lambda: ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD"]
    )
    crypto_birdeye: list[str] = Field(default_factory=lambda: ["JUP", "BONK", "WIF", "PYTH", "RAY"])
    stocks: list[str] = Field(
        default_factory=lambda: ["AAPL", "TSLA", "AMZN", "MSFT", "NVDA", "GOOGL", "META", "NFLX"]
    )
    forex: list[str] = Field(default_factory=lambda: ["EUR-USD", "GBP-USD", "JPY-USD", "AUD-USD"])

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_assets(self) -> list[str]:
        return (
            list(self.crypto_coinbase)
            + list(self.crypto_birdeye)
            + list(self.stocks)
            + list(self.forex)
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def active_assets(self) -> list[str]:
        # Phase 7: crypto only (Coinbase + Birdeye). Stocks/forex are excluded
        # from the active universe but remain wired up for later phases.
        return list(self.crypto_coinbase) + list(self.crypto_birdeye)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def asset_class(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for a in self.crypto_coinbase:
            out[a] = "crypto"
        for a in self.crypto_birdeye:
            out[a] = "crypto"
        for t in self.stocks:
            out[t] = "stock"
        for t in self.forex:
            out[t] = "forex"
        return out

    @computed_field  # type: ignore[prop-decorator]
    @property
    def asset_source(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for a in self.crypto_coinbase:
            out[a] = "coinbase"
        for a in self.crypto_birdeye:
            out[a] = "birdeye"
        for t in self.stocks:
            out[t] = "yfinance"
        for t in self.forex:
            out[t] = "yfinance"
        return out


# -- ML models -----------------------------------------------------------------


class ModelSettings(BaseSettings):
    model_config = _INERT

    horizon: int = 12
    min_rows: int = 300
    test_size: float = 0.20
    history_days: int = 180
    save_dir: Path = PROJECT_ROOT / "models" / "saved"
    annualization_factor: int = 8760

    rf_default: dict = Field(
        default_factory=lambda: {
            "n_estimators": 200,
            "max_depth": 8,
            "min_samples_leaf": 5,
            "class_weight": "balanced",
            "random_state": 42,
            "n_jobs": -1,
        }
    )

    xgb_default: dict = Field(
        default_factory=lambda: {
            "n_estimators": 300,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": 42,
            "n_jobs": -1,
            "verbosity": 0,
        }
    )

    feature_windows: dict[str, int] = Field(
        default_factory=lambda: {
            "sma_short": 20,
            "sma_long": 50,
            "ema_fast": 12,
            "ema_slow": 26,
            "macd_signal": 9,
            "rsi": 14,
            "atr": 14,
            "bb": 20,
            "roc": 10,
            "williams_r": 14,
            "realized_vol": 20,
            "vwap": 20,
            "obv_norm": 50,
        }
    )

    # ORDER MATTERS — joblib pickles of RF/XGB depend on this exact column order.
    feature_columns: list[str] = Field(
        default_factory=lambda: [
            "returns",
            "log_returns",
            "price_range",
            "volume_ratio",
            "sma_20",
            "sma_50",
            "ema_12",
            "ema_26",
            "macd",
            "macd_signal",
            "macd_hist",
            "price_vs_sma20",
            "rsi_14",
            "roc_10",
            "williams_r_14",
            "atr_14",
            "bb_width",
            "bb_position",
            "realized_vol_20",
            "obv",
            "vwap_ratio",
            "hour_of_day",
            "day_of_week",
            "is_weekend",
            "vol_regime",
            "adx_14",
            "volume_trend",
            "yearly_position",
            "macd_hist_momentum",
        ]
    )


# -- Risk scoring --------------------------------------------------------------


class RiskSettings(BaseSettings):
    model_config = _INERT

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "volatility": 0.30,
            "trend_uncertainty": 0.25,
            "sentiment": 0.20,
            "price_momentum": 0.15,
            "market_regime": 0.10,
        }
    )

    thresholds: dict[str, tuple[int, int]] = Field(
        default_factory=lambda: {
            "LOW": (0, 25),
            "MODERATE": (25, 50),
            "HIGH": (50, 75),
            "EXTREME": (75, 100),
        }
    )

    recommend_trade: int = 35
    recommend_hold: int = 55
    recommend_reduce: int = 70

    max_position_pct: float = 0.10
    default_stop_loss_pct: float = 0.05
    kelly_win_loss_ratio: float = 2.00
    kelly_fraction: float = 0.5

    atr_stop_multiplier: float = 2.0
    risk_reward_ratio: float = 2.0

    alert_risk_extreme: float = 80.0
    alert_sentiment_crash: float = -0.7
    alert_vol_spike_factor: float = 2.0
    alert_price_drop_pct: float = -5.0

    vol_risk_cap: float = 2.0
    rsi_min_candles: int = 20
    alerts_log_file: Path = PROJECT_ROOT / "logs" / "alerts.log"


# -- Sentiment -----------------------------------------------------------------


class SentimentSettings(BaseSettings):
    model_config = _INERT

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "onchain": 0.25,
            "dex_ratio": 0.30,
            "news": 0.25,
            "fear_greed": 0.20,
            "twitter": 0.00,
        }
    )

    cache_ttl_minutes: dict[str, int] = Field(
        default_factory=lambda: {
            "fear_greed": 60,
            "news": 20,
            "twitter": 15,
            "dex_ratio": 5,
            "onchain": 60,
        }
    )


# -- Backtesting ---------------------------------------------------------------


class BacktestSettings(BaseSettings):
    model_config = _INERT

    commission_pct: float = 0.001  # 0.1% — Coinbase taker fee
    initial_capital: float = 10_000.0
    position_pct: float = 0.10
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    days: int = 90
    indicator_warmup: int = 60
    min_trades_for_metrics: int = 10
    risk_free_rate_annual: float = 0.05
    reports_dir: Path = PROJECT_ROOT / "reports"
    annualization: int = 8760


# -- Birdeye (the ONE place env vars matter) -----------------------------------


class BirdeyeSettings(BaseSettings):
    # Reads BIRDEYE_API_KEY from process env to preserve pre-refactor behaviour.
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    api_key: str = Field(default="", validation_alias="BIRDEYE_API_KEY")
    base_url: str = "https://public-api.birdeye.so"
    chain: str = "solana"
    chunk_size: int = 1000
    rate_limit_sleep: float = 1.1
    history_days: int = 900


# -- Singletons ----------------------------------------------------------------

data_settings = DataSettings()
asset_settings = AssetSettings()
model_settings = ModelSettings()
risk_settings = RiskSettings()
sentiment_settings = SentimentSettings()
backtest_settings = BacktestSettings()
birdeye_settings = BirdeyeSettings()
