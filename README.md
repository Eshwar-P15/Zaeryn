# ZÆRYN

**AI-Powered Cryptocurrency Trading Intelligence System**

ZÆRYN is a full-stack data management and machine learning system built for cryptocurrency trading. It collects two years of historical OHLCV market data, runs multi-source sentiment analysis, trains ML models to predict volatility and price direction, scores risk per asset using a five-component engine, and validates everything through walk-forward backtesting on stored historical data.

Built from scratch as a CS 210 final project at Rutgers University.

---

## Results

| Asset | Return | Sharpe | Sortino | Max DD | Win Rate |
|-------|--------|--------|---------|--------|----------|
| AVAX-USD | +6.44% | **7.75** | 18.41 | 0.35% | 100% |
| LINK-USD | +7.24% | **7.58** | 14.46 | 0.44% | 95.2% |
| SOL-USD | +6.51% | **6.57** | 12.16 | 0.53% | 88.9% |
| BTC-USD | +4.28% | **6.36** | 14.52 | 0.22% | 100% |
| ETH-USD | +4.76% | **5.63** | 11.76 | 0.30% | 100% |
| JUP | +2.86% | 3.40 | 7.54 | 0.48% | 100% |
| RAY | +3.99% | 1.43 | 2.20 | 2.98% | 44.1% |

90-day walk-forward backtest · $10,000 starting capital · 0.1% commission per leg

MACD Cross on BTC-USD over the same period: **Sharpe -2.09**

---

## What's in the repo

ZAERYN/
├── data/
│   ├── historical.py          # Coinbase OHLCV fetcher — chunked, retry logic
│   ├── birdeye_fetcher.py     # Birdeye API — full Solana token history
│   ├── cleaner.py             # clean_ohlcv, detect_anomalies, normalize
│   ├── storage.py             # SQLite upsert, load_candles, get_db_stats
│   └── dex_fetcher.py         # DexScreener live prices
│
├── sentiment/
│   ├── composer.py            # Weighted composite scorer
│   ├── news_sentiment.py      # NewsAPI + TextBlob NLP
│   ├── dex_sentiment.py       # DexScreener buy/sell ratio
│   ├── onchain_sentiment.py   # Helius Solana RPC
│   ├── fear_greed.py          # Alternative.me Fear & Greed Index
│   └── cache.py               # File-based sentiment caching
│
├── models/
│   ├── features.py            # 29-feature engineering pipeline
│   ├── volatility.py          # XGBoost volatility predictor
│   ├── trend.py               # Random Forest trend classifier
│   └── trainer.py             # Batch training, evaluate_model_health
│
├── risk/
│   ├── scorer.py              # 5-component composite risk score
│   ├── position_sizer.py      # Kelly Criterion + ATR stop losses
│   └── alerts.py              # Alert generation, logs/alerts.log
│
├── backtest/
│   ├── engine.py              # Walk-forward single-candle simulation
│   ├── strategies.py          # MACD, RSI, Bollinger Band, ZAERYN ML
│   ├── metrics.py             # Sharpe, Sortino, Calmar, drawdown
│   └── reporter.py            # JSON reports to reports/
│
├── dashboard/
│   ├── app.py                 # Streamlit entry point
│   ├── pages/                 # Overview, Data Pipeline, Sentiment, ML, Backtest
│   ├── components/            # theme.py, charts.py (Plotly)
│   └── data_loader.py         # Cached DB + model reads
│
├── scripts/
│   ├── fetch_history.py       # Fetch Coinbase historical OHLCV
│   ├── fetch_birdeye_history.py # Backfill Solana token history
│   ├── train_models.py        # Train all assets
│   ├── train_dex_models.py    # Train DEX tokens only (730d)
│   └── run_backtest.py        # Run full strategy comparison
│
├── tests/                     # 158 unit tests, 0 failures
├── config/settings.py         # All constants and API routing
├── requirements.txt
└── .env.example

---

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/Eshwar-P15/Zaeryn.git
cd Zaeryn
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Set up environment variables**

Copy `.env.example` to `.env` and fill in your API keys:
```bash
cp .env.example .env
```

.env
COINBASE_API_KEY=
COINBASE_API_SECRET=
HELIUS_API_KEY=
NEWS_API_KEY=
BIRDEYE_API_KEY=

**Coinbase** — free at coinbase.com/developer-platform
**Helius** — free tier at helius.dev
**NewsAPI** — free tier at newsapi.org
**Birdeye** — free tier at bds.birdeye.so

---

## Running it

**Fetch historical data**
```bash
python -X utf8 scripts/fetch_history.py
python -X utf8 scripts/fetch_birdeye_history.py
```

**Train models**
```bash
python -X utf8 scripts/train_models.py
python -X utf8 scripts/train_dex_models.py
```

**Run backtest**
```bash
python scripts/run_backtest.py
```

**Run the dashboard**
```bash
python -m streamlit run dashboard/app.py
```

**Run tests**
```bash
python -m pytest tests/ -v
```

---

## How it works

### Data Pipeline
OHLCV candle data is fetched from the Coinbase Exchange API for 5 major assets and from Birdeye for 5 Solana DEX tokens. Requests are paginated backwards in 300–1000 candle chunks. Every candle goes through a three-stage cleaning pipeline — deduplication, anomaly detection on moves over 20% in one hour, and normalisation that adds returns and log-returns. Storage is SQLite with a unique constraint on (asset, granularity, timestamp) so the pipeline can re-run safely.

**Database:** 214,212 candles · 10 assets · up to 900 days

### Sentiment Engine
Four sources are combined into a weighted composite score per asset in the range [-1.0, +1.0]:

| Source | Weight | Signal |
|--------|--------|--------|
| DexScreener Buy/Sell Ratio | 30% | Actual transaction flow on DEX pools |
| NewsAPI Headlines | 25% | TextBlob NLP on crypto news |
| Helius On-Chain | 25% | Whale concentration, token velocity |
| Fear & Greed Index | 15% | Alternative.me daily macro index |

Results are cached to disk. The risk engine reads from cache so it never blocks on API calls.

### Machine Learning
Two models are trained per asset on historical candle data using a strict chronological 80/20 split — no shuffling.

**VolatilityPredictor** (XGBoost Regressor) — predicts annualised realised volatility 12 hours ahead. R² = 0.56–0.71.

**TrendClassifier** (Random Forest) — predicts probability of price being higher in 12 hours. AUC = 0.48–0.54.

Both use exponential recency weighting (recent candles matter more). Training on 730 days of Coinbase history was a deliberate choice — extending to 900 days pulled in 2022 bear market data that broke current-regime predictions.

**29 features:** moving averages, MACD, RSI, ATR, Bollinger Bands, volume ratios, z-score normalised OBV, VWAP ratio, time of day, day of week, volatility regime, ADX, and more.

### Risk Engine
Five components combine into a composite score from 0 to 100 per asset:

| Component | Weight |
|-----------|--------|
| Predicted Volatility | 30% |
| Trend Uncertainty | 25% |
| Sentiment Score | 20% |
| RSI Momentum | 15% |
| Market Regime | 10% |

Position sizing uses half-Kelly Criterion scaled by the risk score. High risk means position gets sized down even if the model signal is strong. Kelly W/L ratio = 2.00, derived from backtesting.

### Backtesting
Walk-forward simulation replays stored historical data one candle at a time. At each step the strategy only sees data up to that point. Stop losses trigger on candle LOW, take profits on candle HIGH, 0.1% commission on both legs. Sharpe ratio is computed from candle-level returns with 5% risk-free rate.

Four strategies compete: MACD Cross, RSI Mean Reversion, Bollinger Band, ZAERYN ML Composite.

---

## Assets

| Asset | Type | Source | Candles |
|-------|------|--------|---------|
| BTC-USD | Crypto | Coinbase | 21,596 |
| ETH-USD | Crypto | Coinbase | 21,596 |
| SOL-USD | Crypto | Coinbase | 21,596 |
| AVAX-USD | Crypto | Coinbase | 21,596 |
| LINK-USD | Crypto | Coinbase | 21,596 |
| JUP | Solana DEX | Birdeye | 19,859 |
| BONK | Solana DEX | Birdeye | 21,601 |
| WIF | Solana DEX | Birdeye | 21,582 |
| PYTH | Solana DEX | Birdeye | 21,589 |
| RAY | Solana DEX | Birdeye | 21,601 |

---

## Build phases

| Phase | What got built |
|-------|---------------|
| 0 | Environment, modular structure, Coinbase live price fetcher |
| 1 | Historical OHLCV pipeline, SQLite schema, cleaning + validation, 33 tests |
| 1.5 | Solana DEX integration (DexScreener, GeckoTerminal, Birdeye backfill) |
| 2 | Sentiment engine — 4 sources, caching, 62 tests |
| 3 | ML models — 29 features, XGBoost + RF, recency weighting, 84 tests |
| 4 | Risk scoring engine, Kelly sizing, ATR stops, 125 tests |
| 5 | Walk-forward backtesting, 4 strategies, full metrics suite, 158 tests |
| 8 | Streamlit dashboard — Overview, Data Pipeline, Sentiment, ML, Backtesting |

---

## Known limitations

- All results are validated on historical data. Phase 6 (live execution via Coinbase Advanced Trade API) has not been built yet.
- WIF is excluded from Phase 6 planning — the model over-trades it (64 trades, Sharpe -1.33) due to extreme volatility.
- JUP, BONK, and PYTH have fewer than 10 trades in the 90-day backtest window — statistically limited.
- Sentiment is used in real-time risk scoring but not as an ML training feature because no historical sentiment cache exists yet.

### Survivorship bias

All ZAERYN performance numbers are computed on the surviving subset of each data source's universe: only assets still listed on Coinbase, still indexed by Birdeye, or still queryable on yfinance at the time we fetched are represented. Tokens that rug-pulled, equities that delisted, and pairs that exited their venue between the start of their history and the fetch date are absent from the dataset and therefore from every Sharpe, Sortino, win rate, and per-asset accuracy figure reported. This omission is systematic, not random — it inflates every backward-looking metric by an unknown amount proportional to each asset class's true historical failure rate, and the inflation grows once universe-relative features (cross-sectional rank, dispersion, beta) enter the pipeline in Phase 10. Survivorship correction via point-in-time listings data is a Phase 10 deliverable; until that lands, treat the present numbers as a ceiling, not an expectation.

Full details: `docs/data_integrity_audit.md` → "Survivorship bias (T4)".

---

## What's next

**Phase 6** — Live execution via Coinbase Advanced Trade API. DRY_RUN mode, MAX_DAILY_LOSS_USD kill switch, asset eligibility filter by minimum model AUC.

**Phase 7** — PyTorch LSTM ensembled with XGBoost (40/60) to capture sequential patterns. Expected Sharpe improvement of +1 to +2.

**Phase 8** — Live dashboard with real-time data feed, equity curves, and live risk scores.

---

## Tech stack

Python · SQLite · XGBoost · scikit-learn · pandas · ta (Technical Analysis) · Streamlit · Plotly · pytest · requests · python-dotenv

APIs: Coinbase Exchange · Birdeye · GeckoTerminal · DexScreener · Helius · NewsAPI · Alternative.me

---

## License

MIT
