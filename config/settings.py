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
    "news": 0.5,
    "reddit": 0.3,
    "fear_greed": 0.2,
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
 