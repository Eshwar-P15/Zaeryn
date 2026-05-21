"""Public configuration surface for ZAERYN.

Typed configuration lives in :mod:`config._models`. This module exposes a flat,
backwards-compatible set of UPPER_CASE constants so existing
``from config.settings import X`` imports keep working.

Adding a new config value: prefer adding a field to the right Settings class in
``_models.py`` and re-exporting it here, rather than introducing a bare constant.
"""

from config._models import (
    PROJECT_ROOT,
    data_settings,
    asset_settings,
    model_settings,
    risk_settings,
    sentiment_settings,
    backtest_settings,
    birdeye_settings,
)


# -- Asset universe ------------------------------------------------------------

# Coinbase subset (legacy name retained — used by data/fetcher.py + scripts/init_data.py).
ASSETS = list(asset_settings.crypto_coinbase)

# Full multi-asset universe (22 assets: 10 crypto + 8 stocks + 4 forex).
ALL_ASSETS = asset_settings.all_assets

# Phase 7 trading universe (10 crypto assets — Coinbase + Birdeye).
# Stocks and forex stay in the repo but are excluded from active backtesting/training.
ACTIVE_ASSETS = asset_settings.active_assets

ASSET_SOURCE = asset_settings.asset_source
ASSET_CLASS = asset_settings.asset_class

STOCK_TICKERS = list(asset_settings.stocks)
FOREX_TICKERS = list(asset_settings.forex)

# Solana token mint addresses — pure data, kept as module-level dict.
SOLANA_TOKENS = {
    "JUP":  "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF":  "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "RAY":  "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
}


# -- Data / paths / HTTP -------------------------------------------------------

DB_PATH = data_settings.db_path
LOGS_DIR = data_settings.logs_dir
CACHE_DIR = data_settings.cache_dir

COINBASE_EXCHANGE_URL = data_settings.coinbase_exchange_url
COINBASE_PUBLIC_URL = data_settings.coinbase_public_url
COINBASE_MAX_CANDLES_PER_REQUEST = data_settings.coinbase_max_candles_per_request
DEFAULT_GRANULARITY = data_settings.default_granularity
HISTORY_DAYS = data_settings.history_days

REQUEST_TIMEOUT = data_settings.request_timeout
REQUEST_RETRY_ATTEMPTS = data_settings.request_retry_attempts
REQUEST_RETRY_DELAYS = data_settings.request_retry_delays
CANDLE_REQUEST_SLEEP = data_settings.candle_request_sleep

GRANULARITIES = {
    "1m":  60,
    "5m":  300,
    "15m": 900,
    "1h":  3600,
    "6h":  21600,
    "1d":  86400,
}


# -- DEX endpoints (DexScreener + GeckoTerminal) -------------------------------

DEXSCREENER_BASE_URL = "https://api.dexscreener.com/latest/dex"
GECKOTERMINAL_BASE_URL = "https://api.geckoterminal.com/api/v2"
GECKOTERMINAL_NETWORK = "solana"

GECKO_GRANULARITIES = {
    "1m":  "minute",
    "5m":  "minute",
    "15m": "minute",
    "1h":  "hour",
    "4h":  "hour",
    "1d":  "day",
}

GECKO_AGGREGATES = {
    "1m":  1,
    "5m":  5,
    "15m": 15,
    "1h":  1,
    "4h":  4,
    "1d":  1,
}

GECKO_MAX_CANDLES_PER_REQUEST = 1000

MIN_LIQUIDITY_USD = 50_000
MIN_VOLUME_24H_USD = 10_000


# -- Sentiment -----------------------------------------------------------------

SENTIMENT_WEIGHTS = sentiment_settings.weights
SENTIMENT_CACHE_TTL = sentiment_settings.cache_ttl_minutes

# Sentiment score → label bucket. Tuple-keyed dict kept as a module constant.
SENTIMENT_LABELS = {
    (-1.0, -0.6): "Very Bearish",
    (-0.6, -0.2): "Bearish",
    (-0.2,  0.2): "Neutral",
    ( 0.2,  0.6): "Bullish",
    ( 0.6,  1.0): "Very Bullish",
}


# -- Twitter registry (data table — stays here) --------------------------------

TWITTER_ACCOUNTS = {
    "aeyakovenko":     {"tier": 1, "weight": 1.5, "assets": ["SOL-USD"]},
    "rajgokal":        {"tier": 1, "weight": 1.5, "assets": ["SOL-USD"]},
    "0xMert_":         {"tier": 1, "weight": 1.5, "assets": ["SOL-USD", "all"]},
    "weremeow":        {"tier": 1, "weight": 1.5, "assets": ["JUP"]},
    "therealcharlied": {"tier": 1, "weight": 1.4, "assets": ["JUP"]},
    "armaniferrante":  {"tier": 1, "weight": 1.3, "assets": ["SOL-USD", "all"]},
    "DefiIgnas":       {"tier": 2, "weight": 1.2, "assets": ["all"]},
    "HsakaTrades":     {"tier": 2, "weight": 1.2, "assets": ["all"]},
    "SmallCapScience": {"tier": 2, "weight": 1.2, "assets": ["all"]},
    "SolBigBrain":     {"tier": 2, "weight": 1.2, "assets": ["SOL-USD", "all"]},
    "punk9059":        {"tier": 2, "weight": 1.1, "assets": ["SOL-USD", "all"]},
    "blknoiz06":       {"tier": 3, "weight": 1.0, "assets": ["all"]},
    "cobie":           {"tier": 3, "weight": 1.0, "assets": ["all"]},
    "Pentosh1":        {"tier": 3, "weight": 1.0, "assets": ["SOL-USD"]},
    "CryptoDonAlt":    {"tier": 3, "weight": 1.0, "assets": ["all"]},
    "JupiterExchange": {"tier": 4, "weight": 1.3, "assets": ["JUP"]},
    "bonk_inu":        {"tier": 4, "weight": 1.3, "assets": ["BONK"]},
    "dogwifcoin":      {"tier": 4, "weight": 1.3, "assets": ["WIF"]},
    "PythNetwork":     {"tier": 4, "weight": 1.3, "assets": ["PYTH"]},
    "RaydiumProtocol": {"tier": 4, "weight": 1.3, "assets": ["RAY"]},
    "pumpdotfun":      {"tier": 4, "weight": 1.0, "assets": ["all"]},
    "MeteoraAG":       {"tier": 4, "weight": 1.1, "assets": ["RAY", "JUP"]},
}

ASSET_TWITTER_KEYWORDS = {
    "BTC-USD":  ["$BTC", "Bitcoin", "#Bitcoin"],
    "ETH-USD":  ["$ETH", "Ethereum", "#Ethereum"],
    "SOL-USD":  ["$SOL", "Solana", "#Solana"],
    "AVAX-USD": ["$AVAX", "Avalanche"],
    "LINK-USD": ["$LINK", "Chainlink"],
    "JUP":      ["$JUP", "Jupiter", "JupiterExchange"],
    "BONK":     ["$BONK", "bonkinu"],
    "WIF":      ["$WIF", "dogwifhat"],
    "PYTH":     ["$PYTH", "PythNetwork"],
    "RAY":      ["$RAY", "Raydium"],
}


# -- NewsAPI -------------------------------------------------------------------

NEWSAPI_BASE_URL = "https://newsapi.org/v2/everything"

ASSET_NEWS_KEYWORDS = {
    "BTC-USD":  "Bitcoin BTC",
    "ETH-USD":  "Ethereum ETH",
    "SOL-USD":  "Solana SOL",
    "AVAX-USD": "Avalanche AVAX",
    "LINK-USD": "Chainlink LINK",
    "JUP":      "Jupiter JUP Solana",
    "BONK":     "BONK Solana memecoin",
    "WIF":      "dogwifhat WIF Solana",
    "PYTH":     "Pyth Network PYTH",
    "RAY":      "Raydium RAY Solana",
    "AAPL":     "Apple AAPL stock earnings",
    "TSLA":     "Tesla TSLA stock",
    "AMZN":     "Amazon AMZN stock",
    "MSFT":     "Microsoft MSFT stock",
    "NVDA":     "Nvidia NVDA GPU AI",
    "GOOGL":    "Google Alphabet GOOGL",
    "META":     "Meta Facebook META stock",
    "NFLX":     "Netflix NFLX stock",
    "EUR-USD":  "Euro dollar EURUSD forex",
    "GBP-USD":  "British pound sterling GBPUSD",
    "JPY-USD":  "Japanese yen USDJPY forex",
    "AUD-USD":  "Australian dollar AUDUSD forex",
}


# -- Helius (on-chain) ---------------------------------------------------------

HELIUS_BASE_URL = "https://mainnet.helius-rpc.com"
HELIUS_API_BASE = "https://api.helius.xyz/v0"
WHALE_HOLDER_PCT_THRESHOLD = 1.0


# -- ML models -----------------------------------------------------------------

MODEL_HORIZON = model_settings.horizon
MODEL_MIN_ROWS = model_settings.min_rows
MODEL_TEST_SIZE = model_settings.test_size
MODEL_HISTORY_DAYS = model_settings.history_days
MODEL_SAVE_DIR = model_settings.save_dir
ANNUALIZATION_FACTOR = model_settings.annualization_factor

XGB_PARAMS = model_settings.xgb_default
RF_PARAMS = model_settings.rf_default

# TODO(phase-7-step-4): Per-asset hyperparameter overrides were removed because
# they were tuned via scripts/optimize_models.py (gitignored, not reproducible)
# on the same data they were reported on. Step 4 will reintroduce them via
# nested cross-validation with a true out-of-sample holdout. See
# docs/repo_audit.md section 6 for context.
RF_PARAMS_BY_ASSET: dict[str, dict] = {}
XGB_PARAMS_BY_ASSET: dict[str, dict] = {}

FEATURE_WINDOWS = model_settings.feature_windows
FEATURE_COLUMNS = model_settings.feature_columns


# -- Risk scoring --------------------------------------------------------------

RISK_WEIGHTS = risk_settings.weights
RISK_THRESHOLDS = risk_settings.thresholds
RECOMMEND_TRADE = risk_settings.recommend_trade
RECOMMEND_HOLD = risk_settings.recommend_hold
RECOMMEND_REDUCE = risk_settings.recommend_reduce

MAX_POSITION_PCT = risk_settings.max_position_pct
DEFAULT_STOP_LOSS_PCT = risk_settings.default_stop_loss_pct
KELLY_WIN_LOSS_RATIO = risk_settings.kelly_win_loss_ratio
KELLY_FRACTION = risk_settings.kelly_fraction

ATR_STOP_MULTIPLIER = risk_settings.atr_stop_multiplier
RISK_REWARD_RATIO = risk_settings.risk_reward_ratio

ALERT_RISK_EXTREME = risk_settings.alert_risk_extreme
ALERT_SENTIMENT_CRASH = risk_settings.alert_sentiment_crash
ALERT_VOL_SPIKE_FACTOR = risk_settings.alert_vol_spike_factor
ALERT_PRICE_DROP_PCT = risk_settings.alert_price_drop_pct

ALERTS_LOG_FILE = risk_settings.alerts_log_file
VOL_RISK_CAP = risk_settings.vol_risk_cap
RSI_MIN_CANDLES = risk_settings.rsi_min_candles


# -- Backtesting ---------------------------------------------------------------

BACKTEST_COMMISSION_PCT = backtest_settings.commission_pct
BACKTEST_INITIAL_CAPITAL = backtest_settings.initial_capital
BACKTEST_POSITION_PCT = backtest_settings.position_pct
BACKTEST_STOP_LOSS_PCT = backtest_settings.stop_loss_pct
BACKTEST_TAKE_PROFIT_PCT = backtest_settings.take_profit_pct
BACKTEST_DAYS = backtest_settings.days
INDICATOR_WARMUP = backtest_settings.indicator_warmup
MIN_TRADES_FOR_METRICS = backtest_settings.min_trades_for_metrics
RISK_FREE_RATE_ANNUAL = backtest_settings.risk_free_rate_annual
BACKTEST_REPORTS_DIR = backtest_settings.reports_dir
BACKTEST_ANNUALIZATION = backtest_settings.annualization


# -- Birdeye -------------------------------------------------------------------

BIRDEYE_API_KEY = birdeye_settings.api_key
BIRDEYE_BASE_URL = birdeye_settings.base_url
BIRDEYE_CHAIN = birdeye_settings.chain
BIRDEYE_CHUNK_SIZE = birdeye_settings.chunk_size
BIRDEYE_RATE_LIMIT_SLEEP = birdeye_settings.rate_limit_sleep
BIRDEYE_HISTORY_DAYS = birdeye_settings.history_days


# -- yfinance (stocks + forex) -------------------------------------------------

YFINANCE_TICKER_MAP = {
    "AAPL":    "AAPL",
    "TSLA":    "TSLA",
    "AMZN":    "AMZN",
    "MSFT":    "MSFT",
    "NVDA":    "NVDA",
    "GOOGL":   "GOOGL",
    "META":    "META",
    "NFLX":    "NFLX",
    "EUR-USD": "EURUSD=X",
    "GBP-USD": "GBPUSD=X",
    "JPY-USD": "JPYUSD=X",
    "AUD-USD": "AUDUSD=X",
}

YFINANCE_MAX_DAYS_1H = 729
