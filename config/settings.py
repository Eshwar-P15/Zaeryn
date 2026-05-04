ASSETS = ["BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD"]

# -- Solana Token Registry ----------------------------------------------------
SOLANA_TOKENS = {
    "JUP":  "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF":  "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    "RAY":  "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
}

# -- Asset Source Routing -----------------------------------------------------
ASSET_SOURCE = {
    "BTC-USD":  "coinbase",
    "ETH-USD":  "coinbase",
    "SOL-USD":  "coinbase",
    "AVAX-USD": "coinbase",
    "LINK-USD": "coinbase",
    "JUP":      "dex",
    "BONK":     "dex",
    "WIF":      "dex",
    "PYTH":     "dex",
    "RAY":      "dex",
}

ALL_ASSETS = list(ASSET_SOURCE.keys())

COINBASE_EXCHANGE_URL = "https://api.exchange.coinbase.com"
COINBASE_PUBLIC_URL = "https://api.coinbase.com/v2"

GRANULARITIES = {
    "1m":  60,
    "5m":  300,
    "15m": 900,
    "1h":  3600,
    "6h":  21600,
    "1d":  86400,
}

COINBASE_MAX_CANDLES_PER_REQUEST = 300
DEFAULT_GRANULARITY = "1h"
HISTORY_DAYS = 365

DB_PATH = "zaeryn.db"
LOGS_DIR = "logs"
CACHE_DIR = "cache"

MAX_POSITION_PCT = 0.10
DEFAULT_STOP_LOSS_PCT = 0.05

SENTIMENT_WEIGHTS = {
    "onchain":    0.25,
    "dex_ratio":  0.30,
    "news":       0.25,
    "fear_greed": 0.20,
    "twitter":    0.00,
}

REQUEST_TIMEOUT = 10
REQUEST_RETRY_ATTEMPTS = 3
REQUEST_RETRY_DELAYS = [1, 2, 4]
CANDLE_REQUEST_SLEEP = 0.35

# -- DEX API Endpoints --------------------------------------------------------
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

# -- Sentiment Configuration --------------------------------------------------
SENTIMENT_CACHE_TTL = {
    "fear_greed":  60,
    "news":        20,
    "twitter":     15,
    "dex_ratio":   5,
    "onchain":     60,
}

# -- Twitter Account Registry -------------------------------------------------
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

# -- NewsAPI Config -----------------------------------------------------------
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
}

# -- Helius Config ------------------------------------------------------------
HELIUS_BASE_URL = "https://mainnet.helius-rpc.com"
HELIUS_API_BASE  = "https://api.helius.xyz/v0"
WHALE_HOLDER_PCT_THRESHOLD = 1.0

# -- Sentiment Score Labels ---------------------------------------------------
SENTIMENT_LABELS = {
    (-1.0, -0.6): "Very Bearish",
    (-0.6, -0.2): "Bearish",
    (-0.2,  0.2): "Neutral",
    ( 0.2,  0.6): "Bullish",
    ( 0.6,  1.0): "Very Bullish",
}

# -- ML Model Configuration ---------------------------------------------------

# Prediction horizon in candles (12h at 1h granularity)
MODEL_HORIZON = 12

# Minimum clean rows after feature engineering to attempt training
# SMA-50 burns 50 rows, forward target burns 12 — need buffer above that
MODEL_MIN_ROWS = 300

# Chronological train/test split — last fraction held out
MODEL_TEST_SIZE = 0.20

# Days of history to use when building feature matrix
MODEL_HISTORY_DAYS = 180

# Where trained model files are saved
MODEL_SAVE_DIR = "models/saved"

# Annualization factor for 1h candles: 24 hours * 365 days
ANNUALIZATION_FACTOR = 8760

# XGBoost hyperparameters for volatility regression
XGB_PARAMS = {
    "n_estimators":     300,
    "max_depth":        6,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "random_state":     42,
    "n_jobs":           -1,
    "verbosity":        0,
}

# Random Forest hyperparameters for trend classification
RF_PARAMS = {
    "n_estimators":     200,
    "max_depth":        8,
    "min_samples_leaf": 5,
    "class_weight":     "balanced",
    "random_state":     42,
    "n_jobs":           -1,
}

# Technical indicator windows — single source of truth
FEATURE_WINDOWS = {
    "sma_short":    20,
    "sma_long":     50,
    "ema_fast":     12,
    "ema_slow":     26,
    "macd_signal":  9,
    "rsi":          14,
    "atr":          14,
    "bb":           20,
    "roc":          10,
    "williams_r":   14,
    "realized_vol": 20,
    "vwap":         20,
    "obv_norm":     50,
}

# Feature columns fed to both ML models — ORDER MATTERS
# "returns", "log_returns", "price_range" come from normalize_price_data()
# "volume_ma20" is used to compute "volume_ratio" but is NOT a feature itself
FEATURE_COLUMNS = [
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
]

# -- Risk Scoring Engine -------------------------------------------------------

RISK_WEIGHTS = {
    "volatility":        0.30,
    "trend_uncertainty": 0.25,
    "sentiment":         0.20,
    "price_momentum":    0.15,
    "market_regime":     0.10,
}

RISK_THRESHOLDS = {
    "LOW":      (0,   25),
    "MODERATE": (25,  50),
    "HIGH":     (50,  75),
    "EXTREME":  (75, 100),
}

RECOMMEND_TRADE  = 35
RECOMMEND_HOLD   = 55
RECOMMEND_REDUCE = 70

MAX_POSITION_PCT     = 0.10
KELLY_WIN_LOSS_RATIO = 1.5
KELLY_FRACTION       = 0.5

ATR_STOP_MULTIPLIER = 2.0
RISK_REWARD_RATIO   = 2.0

ALERT_RISK_EXTREME     = 80.0
ALERT_SENTIMENT_CRASH  = -0.7
ALERT_VOL_SPIKE_FACTOR = 2.0
ALERT_PRICE_DROP_PCT   = -5.0

ALERTS_LOG_FILE = "logs/alerts.log"

VOL_RISK_CAP    = 2.0
RSI_MIN_CANDLES = 20
