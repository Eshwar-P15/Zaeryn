# ZAERYN Repository Audit — Phase 7 Step 0

_Date: 2026-05-20 · Branch: main · HEAD: be11194_

This audit is a read-only navigation map and gap list for Phase 7. Every section below names specific files, lines, and behaviors. Subsequent Phase 7 tickets should reference back to this document so we never re-derive the same context.

---

## 1. Executive summary

ZAERYN sits at a well-tested but architecturally fragile post-Phase-6 baseline. The repo has 22 assets in `config/settings.py`, 22 assets in the SQLite database (291,127 candles), an RF + XGBoost modeling pipeline with 29 engineered features, a five-source sentiment engine, a four-strategy walk-forward backtest engine, and 216 collected pytest tests. The conventions described in CLAUDE.md (chronological splits, `predict_proba()` dict shape, cache-first sentiment, idempotent `init_db()`) are real and faithfully implemented in code.

The biggest risks are silent correctness risks rather than visible bugs. Transaction-cost modeling is naive (0.1% Coinbase taker fee applied uniformly to crypto, stocks, and forex — see `config/settings.py:420` and `backtest/engine.py:260,293`); there is no slippage, no spread, no funding rate. Validation is single-split chronological hold-out — there is no walk-forward harness, no regime-stratified evaluation, and no untouched out-of-sample reserve beyond the standard 80/20 train/test split inside `train()`. The `yearly_position` feature uses a 52-week (8,760-candle) rolling window with `min_periods=100` (`models/features.py:184-191`), which is a legitimate look-ahead vector — older candles see a window that does not exist for newer ones. There is no MLflow, no experiment tracking, no per-asset survivorship-bias check, and the asset universe is stored as a hardcoded Python literal rather than a point-in-time snapshot.

The single most urgent gap is **infrastructure scaffolding**: there is no `pyproject.toml`, no centralized pydantic-settings config (settings are 500 lines of Python with side-effects at import time), no ruff/black/mypy, no MLflow, and no `models/saved/` directory exists on disk despite all of risk scoring, backtesting, and the dashboard assuming model files are present. Anything we do in Phase 7 Steps 2–5 needs a real config layer and reproducibility logging underneath it; without those, every audit finding below becomes hard to validate or revert.

---

## 2. File-by-file map

### `backtest/` (4 files)
- **`engine.py`** (321 lines) — `BacktestEngine.run()` replays stored candles; checks stop loss on `candle_low`, take profit on `candle_high`, computes equity curve every candle. Defines `TradeRecord` and `BacktestResult` dataclasses. No look-ahead risk in the loop itself (window = `df.iloc[:i+1]`).
- **`metrics.py`** (186 lines) — Sharpe, Sortino, Calmar, max drawdown, win/loss ratio, profit factor, annualized return, full `compute_metrics()` aggregator.
- **`strategies.py`** (211 lines) — `BaseStrategy` ABC + four concrete strategies: `MACDCrossStrategy`, `RSIMeanReversionStrategy`, `BollingerBandStrategy`, `ZAERYNMLStrategy`. The ML strategy falls back to `MACDCrossStrategy` if no model file exists (line 134-138).
- **`reporter.py`** (102 lines) — `print_summary()`, `save_report()` (writes JSON to `reports/`), `compare_strategies()`, `print_comparison_table()`.

Findings: nothing imports a non-existent module here, no commented-out code blocks. Naming is consistent.

### `config/` (1 active file)
- **`settings.py`** (500 lines) — single monolithic config: asset universe, API endpoints, granularities, sentiment weights, sentiment cache TTLs, Twitter account registry, NewsAPI keyword maps, Helius/Birdeye config, model hyperparameters (including per-asset overrides for the 5 Coinbase crypto assets), feature columns, feature windows, risk weights & thresholds, alert thresholds, backtest constants, yfinance ticker map.

Findings:
- `settings.py:1` and `settings.py:26` both define `ASSETS` and then rebuild `ALL_ASSETS` again at line 485 after adding yfinance tickers — that pattern is fragile (any reader who imports `ALL_ASSETS` before line 485 sees only the first 10 assets). The comment at line 484 acknowledges this.
- `MAX_POSITION_PCT` is defined twice (line 48 and line 401). Both set 0.10 so behavior is correct, but it's a foot-gun.
- `BIRDEYE_API_KEY` is read at import time via `os.getenv` (line 435). If `.env` is loaded later in a script, this snapshot is empty and Birdeye fetches fail; this is the bug the scripts work around by calling `load_dotenv()` before importing `config.settings` (every script in `scripts/` does this at the top — see `fetch_birdeye_history.py:20-21`).
- `ASSET_SOURCE` is mutated post-declaration (lines 444-448 re-route DEX tokens from "dex" to "birdeye"; lines 481-482 add yfinance entries). Anyone importing `ASSET_SOURCE` before that import side-effect completes would see the wrong routing.

### `dashboard/` (1 app file + 5 pages + 2 components)
- **`app.py`** (88 lines) — Streamlit entry, sidebar nav, JS hack to force the sidebar open after page transitions.
- **`data_loader.py`** (136 lines) — `@st.cache_data` wrappers for DB, candles, model health, sentiment cache, fear & greed, backtest reports, equity curves, feature importances. **This is the supposed single-entry point for dashboard reads** (per CLAUDE.md guidance).
- **`pages/overview.py`** (167 lines) — landing page. Imports joblib and reads model files directly at `overview.py:136` (`joblib.load(VolatilityPredictor.model_path(a))`), bypassing `data_loader.feature_importances()`.
- **`pages/ml_models.py`** (156 lines) — direct `joblib.load()` calls at lines 28, 51, 52 (also bypasses `data_loader.py`). Hardcodes `"{len(trained)}/10"` at line 36 — this is wrong: the active universe is 22, not 10.
- **`pages/sentiment.py`** (120 lines) — uses `data_loader.sentiment_all()` and `fear_greed()`. Clean.
- **`pages/data_pipeline.py`** (121 lines) — uses `data_loader.db_stats()` and `candles()`. Clean.
- **`pages/backtesting.py`** (150 lines) — uses `data_loader.strategy_comparison()` and `equity_curves_for()`. Clean.
- **`components/charts.py`** (290 lines) — Plotly chart factories.
- **`components/theme.py`** (318 lines) — CSS + UI helpers.

Findings:
- `pages/ml_models.py:36` displays "X / 10 Models Active" — stale label, should be `/{len(ALL_ASSETS)}` or removed entirely.
- The CLAUDE.md invariant "go through `data_loader.py`" is violated in `overview.py` and `ml_models.py`. Either tighten the rule or expose a helper.

### `data/` (8 files)
- **`fetcher.py`** (67 lines) — live spot price polling. **Still imports the legacy `ASSETS` symbol** (line 2), which only contains the 5 Coinbase assets. `fetch_prices()` only fetches Coinbase prices + DEX prices; no yfinance live polling.
- **`birdeye_fetcher.py`** (223 lines) — paginated backward fetch from Birdeye OHLCV endpoint.
- **`cleaner.py`** (113 lines) — `validate_ohlcv()`, `clean_ohlcv()` with `gap_fill` toggle, `detect_anomalies()` (flags >20% candle-over-candle moves), `normalize_price_data()` (adds `returns`, `log_returns`, `price_range`, `volume_ma20`).
- **`dex_fetcher.py`** (176 lines) — DexScreener live price + pair address lookup. Still used by `gecko_fetcher` for pair address resolution.
- **`gecko_fetcher.py`** (189 lines) — historical OHLCV via GeckoTerminal (DEX fallback before Birdeye).
- **`historical.py`** (185 lines) — `fetch_candles()` source router; dispatches by `ASSET_SOURCE` to coinbase/dex/birdeye/yfinance.
- **`storage.py`** (196 lines) — SQLite schema + `init_db()` (idempotent), `upsert_candles()` (INSERT OR REPLACE on UNIQUE(asset, granularity, timestamp)), `load_candles()`, `upsert_price_snapshot()`, `load_price_snapshots()`, `get_db_stats()`.
- **`yfinance_fetcher.py`** (103 lines) — yfinance adapter, normalizes column case, flattens MultiIndex, handles forex zero-volume.

Findings:
- `data/fetcher.py:2` still imports `ASSETS` (the 5-asset legacy list). Live polling will silently miss the other 17 assets.
- `dex_fetcher.py:18` keeps a module-level `_pair_address_cache: dict[str, str]` that never expires (line 138-148). Long-running processes can drift if a pair migrates.

### `models/` (5 files — _no LSTM, no ensemble, no FinBERT_)
- **`features.py`** (334 lines) — `compute_technical_indicators()`, `compute_targets()`, `build_feature_matrix()` — single entry point from DB → training-ready (X, y_vol, y_dir).
- **`trend.py`** (262 lines) — `TrendClassifier` (RF). `predict_proba()` returns the documented dict shape with `up_probability`/`down_probability`/`direction`/`confidence` (lines 191-196). `UNCERTAIN` band = ±0.15 around 0.5 (line 37).
- **`volatility.py`** (235 lines) — `VolatilityPredictor` (XGBoost regressor). `predict()` returns a single float, floor-clamped to 0 (line 166). Stores a fitted `StandardScaler` for "Phase 7 LSTM compatibility" (lines 36, 83) — dead code today, but intentional forward hook.
- **`trainer.py`** (177 lines) — `train_all_models()`, `evaluate_model_health()`, `should_retrain()`. Per-asset failures are caught; the batch continues.
- **`__init__.py`** — empty.

Findings:
- `models/saved/` directory **does not exist on disk** (verified via `ls`). Every consumer (`risk/scorer.py`, `backtest/strategies.py`, `dashboard/pages/ml_models.py`) silently falls back when model files are missing. Nothing in the live state currently produces ML output — backtests using `ZAERYNMLStrategy` will all fall through to MACD Cross.
- `models/volatility.py:36,83` references a "Phase 7 LSTM compatibility" scaler — keep this in mind during Step 5; this is the only forward hook in the current models.
- No LSTM, no ensemble, no FinBERT anywhere in `models/` or `sentiment/`. Verified by grep — only `models/volatility.py` mentions LSTM, and only in comments.

### `risk/` (4 files)
- **`scorer.py`** (369 lines) — `compute_risk_score(asset)` + `score_all_assets()`. Five components, weight redistribution, cache-first sentiment, RSI extracted inline (not via full feature pipeline).
- **`position_sizer.py`** (181 lines) — Kelly criterion, risk-adjusted sizing, ATR stop loss, take profit, `full_position_plan()` aggregator.
- **`alerts.py`** (195 lines) — `Alert` dataclass, `check_alerts()` with four trigger types, dedicated alert log file.
- **`__init__.py`** — empty.

Findings: clean. Comments reference "Rule N" sigils that don't appear in any consolidated rule sheet; they're folklore.

### `scripts/` (11 files)
- **`fetch_history.py`** (88 lines) — 730-day Coinbase + DEX backfill loop.
- **`fetch_birdeye_history.py`** (146 lines) — Birdeye-only backfill for 5 Solana tokens.
- **`fetch_stock_forex_history.py`** (136 lines) — yfinance backfill for 12 stocks/forex tickers.
- **`init_data.py`** (92 lines) — 7-day initial pipeline test (Phase 1 validation script). Imports the legacy `ASSETS` symbol.
- **`init_dex_data.py`** (109 lines) — 7-day DEX validation script (Phase 1.5).
- **`risk_report.py`** (127 lines) — runs `score_all_assets()`, prints table, computes position plans, runs alerts.
- **`run_backtest.py`** (142 lines) — runs four strategies × `ALL_ASSETS`; saves JSON reports.
- **`run_sentiment.py`** (110 lines) — exercises every sentiment source.
- **`train_models.py`** (101 lines) — `train_all_models()` driver. Has `--retrain` flag.
- **`train_dex_models.py`** (45 lines) — DEX-only training driver. **Hardcodes `DEX_ASSETS = ["BONK", "WIF", "PYTH", "RAY"]`** (line 14) — note JUP is excluded. Comment at line 1-3 explains it.
- **`__init__.py`** — empty.

Findings:
- `scripts/init_data.py` is a stale Phase 1 validation runner that imports `ASSETS` instead of `ALL_ASSETS`. It is documentation-as-history rather than something we still call. Consider archiving.
- `scripts/init_dex_data.py` is similarly Phase 1.5 history.
- `scripts/train_dex_models.py` excludes JUP without an inline justification beyond "previous workspace" context.
- `.gitignore` excludes `scripts/optimize_models.py`, `scripts/patch_model_metrics.py`, and `scripts/best_params.json` — those were used to generate the per-asset hyperparameters in `RF_PARAMS_BY_ASSET` / `XGB_PARAMS_BY_ASSET` but the generator is not committed. That's a reproducibility hole.

### `sentiment/` (7 files)
- **`cache.py`** (93 lines) — file-based JSON cache, TTL gating, `get_or_fetch_sentiment()` (cache-first read path).
- **`dex_sentiment.py`** (118 lines) — DexScreener 1h/24h buy/sell ratio → score.
- **`fear_greed.py`** (70 lines) — alternative.me index → normalized [-1, +1].
- **`news.py`** (176 lines) — NewsAPI + TextBlob polarity. **No FinBERT.** Confidence = `min(1.0, article_count/10)`.
- **`onchain.py`** (164 lines) — Helius RPC, top-20 holder concentration → score. Only fires for `ASSET_SOURCE[asset] == "dex"` (line 107); after the post-import re-routing to "birdeye", DEX tokens never trigger this branch.
- **`scorer.py`** (165 lines) — `compute_sentiment_score()` weighted aggregator + `score_all_assets()` + `get_market_sentiment()`.
- **`twitter_scraper.py`** (217 lines) — twikit-based scraper. Dormant: weight is 0.00 in `SENTIMENT_WEIGHTS` and `include_twitter=False` by default everywhere.

Findings:
- **`sentiment/onchain.py:107` is broken in practice.** It gates on `ASSET_SOURCE[asset] == "dex"`, but the post-import side-effect in `config/settings.py:444-448` re-routes JUP/BONK/WIF/PYTH/RAY to `"birdeye"`. So the on-chain component is currently dead for every asset. The risk scorer will get `score=0, confidence=0` for every call and the `onchain` weight redistributes away.
- `sentiment/twitter_scraper.py` imports `twikit` lazily (line 31-34); it cannot be used without setting `TWITTER_USERNAME/EMAIL/PASSWORD` in `.env`. Acceptable.

### `tests/` (8 test files)
- **`test_backtest.py`** — engine, strategies, metrics, drawdown/Sharpe/Sortino/Calmar, win/loss ratio, profit factor, serialization. 36 tests including 3 integration.
- **`test_birdeye.py`** — items → DataFrame, headers, 401/404 handling, pagination stop conditions, dedup. 15 tests including 2 integration.
- **`test_data.py`** — math utils, time utils, cleaner, storage. 24 tests including 1 integration.
- **`test_dex.py`** — config sanity, pair selection, GeckoTerminal parse, routing. 14 tests including 3 integration.
- **`test_models.py`** — feature pipeline, leakage check (`test_no_future_leakage_in_features`), targets, VolatilityPredictor, TrendClassifier. 22 tests including 3 integration.
- **`test_risk.py`** — labels, recommendation, weight redistribution, sentiment/momentum components, Kelly, position sizing, stop loss / take profit, alerts. 41 tests including 3 integration.
- **`test_sentiment.py`** — score_label, fear & greed, dex sentiment, news, whale concentration, cache, composite scorer. 33 tests including 4 integration.
- **`test_yfinance.py`** — fetcher, multi-index flattening, ticker map, gap_fill toggle, routing, dex sentiment skip. 21 tests including 2 integration.

**Total: 216 tests collected.** Pytest discovery succeeds (`pytest --collect-only -q` exits clean in 1s).

### `utils/` (3 files)
- **`logger.py`** (33 lines) — file + console handler factory.
- **`math_utils.py`** (53 lines) — `pct_change`, `rolling_mean`, `rolling_std`, `normalize_minmax`, `clamp`, `safe_log`.
- **`time_utils.py`** (48 lines) — `now_utc()`, `to_unix()`, `from_unix()`, `to_iso()`, `date_range()`, `chunk_date_range()`. UTC convention enforced here (`to_unix` and `to_iso` both replace naive datetimes with UTC).

---

## 3. Asset universe

### Declared (`config/settings.py`)
The active universe is built across multiple side-effect statements. Final state:

| Asset | Class | Source | Defined at |
|---|---|---|---|
| BTC-USD, ETH-USD, SOL-USD, AVAX-USD, LINK-USD | crypto | coinbase | `settings.py:14-18` |
| JUP, BONK, WIF, PYTH, RAY | crypto | birdeye | `settings.py:444-448` (post-import re-route from `"dex"`) |
| AAPL, TSLA, AMZN, MSFT, NVDA, GOOGL, META, NFLX | stock | yfinance | `settings.py:452, 481-482` |
| EUR-USD, GBP-USD, JPY-USD, AUD-USD | forex | yfinance | `settings.py:453, 481-482` |

**Total: 22 assets** — confirmed by `tests/test_yfinance.py:201` (`assert len(ALL_ASSETS) == 22`).

### Inconsistencies

1. **`ASSETS` vs `ALL_ASSETS`.** The legacy 5-asset list still exists at `settings.py:1` and is imported by `data/fetcher.py:2` and `scripts/init_data.py:6`. Anything that imports `ASSETS` only sees crypto.
2. **`ALL_ASSETS` is rebuilt twice** — once at `settings.py:26` (10 assets) and again at `settings.py:485` (22 assets). Any module that imports it before the side-effect at line 485 will see the wrong list. This works today because Python module imports run top-to-bottom, but it is silently dependent on import order.
3. **`ASSET_SOURCE` re-routing is hidden in module-load side-effects** (lines 444-448 and 481-482). This is why `sentiment/onchain.py:107` is broken — it was written when DEX tokens routed to `"dex"`, before the Birdeye re-route landed.
4. **`SOLANA_TOKENS` (settings.py:4-10)** and the asset-class mapping (`ASSET_CLASS`, settings.py:470-477) both treat JUP/BONK/WIF/PYTH/RAY as Solana crypto. Consistent with each other.
5. **The DB has all 22 assets present** (see Section 4) — `train_models.py:27` and `risk_report.py:46` both iterate `ALL_ASSETS`, so the entire universe is currently in use despite the Phase 7 directive to stay crypto-only.

### Phase 7 framing mismatch
The CLAUDE.md says "Crypto only for backtesting and training" during Phase 7. Today the code, the DB, the scripts, and the dashboard all treat the universe as 22 assets. There is no flag that distinguishes "active for training" from "present in repo". Step 1 should introduce one (e.g. `ACTIVE_ASSETS = [crypto only]` and have all training/backtest scripts iterate that, while leaving the yfinance fetchers untouched).

---

## 4. Data layer

### Schema (defined in `data/storage.py:12-39`)

```sql
CREATE TABLE candles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset       TEXT    NOT NULL,
    granularity TEXT    NOT NULL,
    timestamp   INTEGER NOT NULL,             -- unix seconds, UTC
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      REAL    NOT NULL,
    is_anomaly  INTEGER DEFAULT 0,
    UNIQUE(asset, granularity, timestamp)
);

CREATE TABLE price_snapshots (
    asset      TEXT    PRIMARY KEY,
    price      REAL    NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX idx_candles_asset_time ON candles (asset, granularity, timestamp);
```

### Tables in `zaeryn.db` (live query)
- `candles` — 291,127 rows
- `price_snapshots` — 0 rows
- `sqlite_sequence` — internal (AUTOINCREMENT bookkeeping)

### Ingestion paths
Each fetcher returns a `DataFrame[timestamp, open, high, low, close, volume]`, which is then `clean_ohlcv()` → `validate_ohlcv()` → `detect_anomalies()` → `normalize_price_data()` → `upsert_candles()`.

- **`data/fetcher.py`** — live spot prices (Coinbase + DEX) → `upsert_price_snapshot()`.
- **`data/historical.py:117 fetch_candles()`** — universal router; dispatches by `ASSET_SOURCE` to:
  - `_fetch_from_coinbase()` (line 70) — chunked Coinbase Exchange API
  - `_fetch_from_dex()` (line 108) — GeckoTerminal via DexScreener pair address
  - `data/birdeye_fetcher.fetch_birdeye_ohlcv()` — Birdeye OHLCV
  - `data/yfinance_fetcher.fetch_yfinance_ohlcv()` — yfinance
- **`data/birdeye_fetcher.py`** — backwards-paginated fetch; stops on `< CHUNK_SIZE` items or target date.
- **`data/gecko_fetcher.py`** — forward-paginated fetch with `before_timestamp`.
- **`data/dex_fetcher.py`** — pair-address resolution + live DEX prices.
- **`data/yfinance_fetcher.py`** — single `yf.download()` call; 1h capped at 730 days.

### Consumers
- **`data/storage.py:103 load_candles(asset, granularity, days_back, conn)`** — single read path. Called by:
  - `risk/scorer.py:235, 359` (risk scoring)
  - `models/trainer.py:133` (model health check)
  - `models/features.py:275` (feature matrix build)
  - `backtest/engine.py:132` (backtest replay)
  - `scripts/run_backtest.py` (indirectly via engine)
  - `scripts/risk_report.py:81, 102`
  - `dashboard/data_loader.py:26` (cached for UI)
  - `scripts/init_data.py:58` (validation)

### Timestamp handling
- **UTC convention** enforced in `utils/time_utils.py:9-22` (`to_unix`, `from_unix`, `to_iso` all use `tzinfo=timezone.utc`).
- DB stores `INTEGER` unix seconds (`storage.py:17`).
- `load_candles()` rehydrates to `datetime` via `from_unix` (`storage.py:136`).
- yfinance / Birdeye / Coinbase / Gecko all normalize to UTC in their adapter layers.
- **Risk**: there is no explicit assertion that an asset's stored timestamps are unique modulo `(asset, granularity)` beyond the UNIQUE constraint, and no test for whether stock/forex timestamps are stored at the same hour boundaries as crypto. Different sources produce slightly different intra-hour offsets (yfinance returns market-clock-aligned bars, Coinbase aligns to UTC hour). This shows up below — stocks have 13:30 minute-marked timestamps, crypto has clean :00.

### Asset coverage (live query of `zaeryn.db`)
22 distinct assets, all 1h granularity:

| asset    | rows   | earliest          | latest            |
|---|---|---|---|
| AAPL     | 3,467  | 2024-05-13 13:30  | 2026-05-11 19:30  |
| AMZN     | 3,467  | 2024-05-13 13:30  | 2026-05-11 19:30  |
| AUD-USD  | 12,361 | 2024-05-12 23:00  | 2026-05-11 22:00  |
| AVAX-USD | 21,596 | 2023-11-20 00:00  | 2026-05-08 00:00  |
| BONK     | 21,601 | 2023-11-20 00:00  | 2026-05-08 00:00  |
| BTC-USD  | 21,596 | 2023-11-20 00:00  | 2026-05-08 00:00  |
| ETH-USD  | 21,596 | 2023-11-20 00:00  | 2026-05-08 00:00  |
| EUR-USD  | 12,296 | 2024-05-12 23:00  | 2026-05-11 22:00  |
| GBP-USD  | 12,298 | 2024-05-12 23:00  | 2026-05-11 22:00  |
| GOOGL    | 3,467  | 2024-05-13 13:30  | 2026-05-11 19:30  |
| JPY-USD  | 12,224 | 2024-05-12 23:00  | 2026-05-11 22:00  |
| JUP      | 19,859 | 2024-01-31 14:00  | 2026-05-08 00:00  |
| LINK-USD | 21,596 | 2023-11-20 00:00  | 2026-05-08 00:00  |
| META     | 3,467  | 2024-05-13 13:30  | 2026-05-11 19:30  |
| MSFT     | 3,467  | 2024-05-13 13:30  | 2026-05-11 19:30  |
| NFLX     | 3,467  | 2024-05-13 13:30  | 2026-05-11 19:30  |
| NVDA     | 3,467  | 2024-05-13 13:30  | 2026-05-11 19:30  |
| PYTH     | 21,589 | 2023-11-20 12:00  | 2026-05-08 00:00  |
| RAY      | 21,601 | 2023-11-20 00:00  | 2026-05-08 00:00  |
| SOL-USD  | 21,596 | 2023-11-20 00:00  | 2026-05-08 00:00  |
| TSLA     | 3,467  | 2024-05-13 13:30  | 2026-05-11 19:30  |
| WIF      | 21,582 | 2023-11-20 19:00  | 2026-05-08 00:00  |

Observations:
- All 22 declared assets are present in the DB.
- Crypto + DEX assets are last-updated 2026-05-08; yfinance assets are last-updated 2026-05-11 (3 days fresher).
- Stocks have ~3,467 rows / 2 years which is consistent with US-cash-hour-only trading. Forex has ~12,300 rows / 2 years.
- DEX tokens span 2023-11-20 → 2026-05-08 (≈900 days) which matches `BIRDEYE_HISTORY_DAYS = 900`.
- `price_snapshots` is empty — live polling was never run, or its DB was cleared.

---

## 5. Feature engineering

### Entry point
`models/features.py:246 build_feature_matrix(asset, granularity, days_back, horizon, conn)` returns `(X, y_vol, y_dir)` or `None`. Pipeline:

1. `load_candles()` (storage)
2. `clean_ohlcv()` (cleaner)
3. `normalize_price_data()` (cleaner — adds `returns`, `log_returns`, `price_range`, `volume_ma20`)
4. `compute_technical_indicators()` (features:20)
5. `compute_targets()` (features:202 — adds `target_volatility`, `target_direction`, `target_return_pct`)
6. Drop NaN rows from `FEATURE_COLUMNS + [target_volatility, target_direction]` (features:299)
7. Require `len(df) >= MODEL_MIN_ROWS (300)`; else return `None`
8. Final NaN check on X; else return `None`

### Train/test split
Implemented identically in `models/trend.py:75-85` and `models/volatility.py:67-77`:
```python
split_idx = int(len(X) * (1 - test_size))   # MODEL_TEST_SIZE = 0.20
X_train = X.iloc[:split_idx]
X_test  = X.iloc[split_idx:]
y_train = y_dir.iloc[:split_idx]
y_test  = y_dir.iloc[split_idx:]
```
Single chronological split, no `shuffle=True`, no `TimeSeriesSplit`, no walk-forward. Recency weighting via `np.exp(np.linspace(0, 1, n))` is applied to `sample_weight` (trend.py:94, volatility.py:88).

### The 29 features in `FEATURE_COLUMNS` order (`config/settings.py:348-378`)

| # | Feature | Source | Window / formula | Look-ahead risk |
|---|---|---|---|---|
| 1 | `returns` | `cleaner.normalize_price_data` | `close.pct_change()` | safe (lag 1) |
| 2 | `log_returns` | cleaner | `log(close / close.shift(1))` | safe |
| 3 | `price_range` | cleaner | `(high - low) / close` of current bar | safe (intrabar only) |
| 4 | `volume_ratio` | `features.py:121` | `volume / volume_ma20` (volume_ma20 from `normalize_price_data`, window=20, `min_periods=1`) | safe |
| 5 | `sma_20` | `ta.trend.SMAIndicator`, window=20 | trailing | safe |
| 6 | `sma_50` | window=50 | trailing | safe |
| 7 | `ema_12` | window=12 | trailing exponential | safe |
| 8 | `ema_26` | window=26 | trailing exponential | safe |
| 9 | `macd` | `ta.trend.MACD` | EMA12 − EMA26 | safe |
| 10 | `macd_signal` | from `MACD()` | EMA9 of macd | safe |
| 11 | `macd_hist` | from `MACD()` | macd − macd_signal | safe |
| 12 | `price_vs_sma20` | `features.py:65` | `(close − sma_20) / sma_20` | safe |
| 13 | `rsi_14` | `ta.momentum.RSIIndicator`, window=14 | trailing | safe |
| 14 | `roc_10` | `ta.momentum.ROCIndicator`, window=10 | `(close[t] / close[t−10]) − 1` | safe |
| 15 | `williams_r_14` | `ta.momentum.WilliamsRIndicator`, lbp=14 | trailing | safe |
| 16 | `atr_14` | `ta.volatility.AverageTrueRange`, window=14 | trailing | safe |
| 17 | `bb_width` | `ta.volatility.BollingerBands`, window=20, dev=2 | trailing | safe |
| 18 | `bb_position` | Bollinger %B | trailing | safe |
| 19 | `realized_vol_20` | `features.py:110` | `log_returns.rolling(20).std() * sqrt(8760)` | safe |
| 20 | `obv` | `features.py:128` | OBV z-scored over 50-bar rolling mean/std | safe |
| 21 | `vwap_ratio` | `features.py:142` | `close / rolling_vwap_20` | safe |
| 22 | `hour_of_day` | `features.py:153` | `timestamp.dt.hour` | safe |
| 23 | `day_of_week` | `features.py:154` | 0–6 | safe |
| 24 | `is_weekend` | `features.py:155` | `day_of_week >= 5` | safe |
| 25 | `vol_regime` | `features.py:160` | `realized_vol_20 / realized_vol_20.rolling(60).mean()` | safe |
| 26 | `adx_14` | `ta.trend.ADXIndicator`, window=14 | trailing | safe |
| 27 | `volume_trend` | `features.py:175` | `vol_ma_10 / vol_ma_30` | safe |
| 28 | `yearly_position` | `features.py:184-191` | `(close − rolling_min_8760) / (rolling_max_8760 − rolling_min_8760)` with `min_periods=100` | **⚠ leakage-shaped risk** — see below |
| 29 | `macd_hist_momentum` | `features.py:194` | `macd_hist.diff()` | safe |

### Leakage findings — flagged for Phase 7 Step 4

1. **`yearly_position` (features.py:184-191)** — uses `rolling(8760, min_periods=100)`. This is technically backward-looking (only past data is in the window), so it's not classical look-ahead. The risk is more subtle:
   - The first 100 candles get a position computed over their own narrow history (effectively a "from start of available data" position), while later candles get a full-year window. The same `close` price will receive a different `yearly_position` value depending on how much history precedes it. During training, the early portion of the train set sees a different distribution of this feature than the test set does. This is a **stationarity violation**, not a leak, but it can mask itself as either training-set memorization or as a regime signal that doesn't generalize.
   - On DEX tokens that haven't reached 8,760 candles of age (JUP has 19,859 — fine; WIF has 21,582 — fine), this is non-issue. But if any new asset enters with fewer than ~365 days of history, the feature is unstable for most of its training window.
   - **Recommendation**: in Step 4, either (a) drop the first ~8,760 rows from training when this feature is active, or (b) replace with a fixed-window equivalent (e.g. 90 days).

2. **`vol_regime` (features.py:160)** — uses `rolling(60).mean()` divisor without `min_periods`. First 60 candles produce NaN (gets dropped in `build_feature_matrix`), so behaviorally safe.

3. **`obv` (features.py:128-138)** — z-scored using a 50-bar rolling mean and std. Both are trailing. No leak.

4. **`compute_targets` (features.py:202-243)** — `target_volatility` uses `log_returns.shift(-1).rolling(horizon).std()` and `target_direction` uses `close.shift(-horizon)`. These are intentional forward-looking targets, and the last `horizon` rows are correctly NaN. `tests/test_models.py:141 test_last_horizon_rows_are_nan` covers this.

5. **Cross-feature timing** — every indicator above relies only on `close`, `high`, `low`, `volume` from past or current bars. The `test_no_future_leakage_in_features` test (`test_models.py:76`) modifies only `row[-1]` and asserts that `rsi_14`, `sma_20`, `macd` at `row[-2]` are unchanged. This guard is good but only covers three features — Step 4 should extend it to all 29.

**Bottom line: 1 yellow flag (`yearly_position`)**, 28 features confirmed clean for look-ahead. The flag is stationarity rather than leakage, but it lives at the same address.

### Other observations on the feature pipeline
- `compute_technical_indicators` is called twice per asset during training (once inside `build_feature_matrix`, never re-called on cached state). Inference path (`TrendClassifier.predict_proba`, `trend.py:164-167`) re-runs the cleaner + normalizer + indicators on the raw input candle window. Acceptable, but slow.
- No feature scaling on the RF / XGBoost path. The `StandardScaler` in `volatility.py:84` is fit but only stored, never applied (xgboost is tree-based, so it doesn't matter — but the dormant scaler suggests intent to switch).

---

## 6. Models

### Classes
- **`TrendClassifier`** (`models/trend.py:27`) — Random Forest classifier.
- **`VolatilityPredictor`** (`models/volatility.py:25`) — XGBoost regressor.
- **No `LSTMTrendClassifier`, no `EnsembleTrendClassifier`** — confirmed via `find models -type f -name "*.py"` and grep for class definitions.

### `predict_proba()` interface
From `models/trend.py:143-196`:
```python
return {
    "up_probability":   round(up_prob,    4),     # float ∈ [0,1]
    "down_probability": round(down_prob,  4),
    "direction":        direction,                # "UP" | "DOWN" | "UNCERTAIN"
    "confidence":       round(confidence, 4),     # 0=coin flip, 1=max
}
```
✅ Matches the CLAUDE.md contract exactly.

Consumers verified to depend on this shape:
- `risk/scorer.py:111` → `result.get("confidence", 0.0)`
- `risk/scorer.py:258, 298, 299` → `trend_data.get("direction")`, `get("confidence")`
- `backtest/strategies.py:184-186` → `trend_result.get("direction", "UNCERTAIN")`, `get("confidence", 0.0)`
- `risk/position_sizer.py:157` → `trend.get("up_probability", 0.5)`
- `models/trainer.py:149` → returned dict from `predict_proba`
- `dashboard/pages/overview.py` — uses model_health output (indirect)

### Model artifact storage

- Defined in `config/settings.py:186` as `MODEL_SAVE_DIR = "models/saved"`.
- `TrendClassifier.model_path(asset)` (`trend.py:259`) → `models/saved/trend_{ASSET}_{HORIZON}h.pkl`
- `VolatilityPredictor.model_path(asset)` (`volatility.py:232`) → `models/saved/volatility_{ASSET}_{HORIZON}h.pkl`
- Save/load uses `joblib` (`trend.py:209-223`, `volatility.py:180-194`). Persisted fields include the trained model, feature column order, asset name, trained_at, importances, and metrics (auc/f1/acc/precision/recall/mae/rmse/r2/mape/train_rows).

### Files on disk **right now**
**None.** `models/saved/` directory does not exist. `models/saved_lstm/` does not exist. Verified via `find /home/epala/dev/Zaeryn/models -type f`.

Implication: every dashboard, backtest, and risk-scoring call currently runs in fallback mode. `ZAERYNMLStrategy` falls back to `MACDCrossStrategy` (`strategies.py:134-138`). Risk scoring redistributes the 30% volatility + 25% trend weights onto sentiment/momentum/regime (`risk/scorer.py:171-191`). The fallbacks are silent — no warning surfaces to the UI when the user is looking at a "ML model performance" page.

### Hyperparameters

Declared in `config/settings.py`:

- **Default RF** (line 204-211): n_estimators=200, max_depth=8, min_samples_leaf=5, class_weight=balanced.
- **Per-asset RF overrides** (line 215-261): only for BTC, ETH, SOL, AVAX, LINK. DEX tokens fall back to default. Comment at line 213 says "scripts/optimize_models.py, TimeSeriesSplit CV" — but that file is gitignored (`.gitignore:22`). The optimizer is not reproducible.
- **Default XGB** (line 192-201): n_estimators=300, max_depth=6, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8.
- **Per-asset XGB overrides** (line 265-326): only for BTC, ETH, SOL, AVAX, LINK. DEX/stock/forex fall back to default.
- `MODEL_HORIZON = 12` (12h ahead)
- `MODEL_TEST_SIZE = 0.20`
- `MODEL_HISTORY_DAYS = 180` (default in `build_feature_matrix`, but training scripts override to 730)
- `MODEL_MIN_ROWS = 300`
- `ANNUALIZATION_FACTOR = 8760`

### LSTM/ensemble — not yet implemented
Confirmed. No `models/lstm.py`, no `models/ensemble.py`. The only forward-looking hooks are the `StandardScaler` field in `VolatilityPredictor` (lines 36, 83 — "stored for Phase 7 LSTM compatibility") and the empty `ENSEMBLE_LSTM_WEIGHT` / `ENSEMBLE_RF_WEIGHT` references in CLAUDE.md (which are also not in `config/settings.py` yet).

---

## 7. Risk scoring

### `compute_risk_score()` — `risk/scorer.py:215`

### Components (`config/settings.py:382-388`)
| Component | Weight | Source | Implementation |
|---|---|---|---|
| volatility | 0.30 | `VolatilityPredictor.predict()` | `scorer.py:66 _compute_volatility_component()`; risk = `min(predicted_vol / VOL_RISK_CAP, 1.0)` where `VOL_RISK_CAP = 2.0` (settings:415) |
| trend_uncertainty | 0.25 | `TrendClassifier.predict_proba()` | `scorer.py:247-256` (inline) → `1.0 − confidence` |
| sentiment | 0.20 | `sentiment/cache.load_cached_sentiment` (cache-first), fallback `get_or_fetch_sentiment` | `scorer.py:118 _compute_sentiment_component()`; risk = `(1.0 − score) / 2.0` |
| price_momentum | 0.15 | RSI computed inline via `ta` | `scorer.py:143 _compute_momentum_component()`; risk = `abs(rsi − 50) / 50` |
| market_regime | 0.10 | `fear_greed.fetch_fear_greed`, cached for the batch | `scorer.py:157 _compute_regime_component()`; risk = `abs(fg_normalized)` |

### Failure handling
- Each `_compute_*_component()` returns `(value | None, confidence)`. If the component returns `None`, `_redistribute_weights()` (line 171) drops it and renormalizes the remaining weights to sum to 1.
- Model file missing → component returns `None`, redistributed.
- Sentiment cache miss + live API failure → returns `(0.5, 0.0)`, treated as available but uninformative — **note this is not the same as `None`**, so the weight is NOT redistributed. The score contributes 0.5 × 0.20 = 0.10 to the final score, which is the most "polite" failure mode but also the least visible.
- Component exception → caught with `logger.warning`, returns `(None, 0.0)` (volatility/trend) or `(0.5, 0.0)` (sentiment). The user-facing dashboard does NOT distinguish "model unavailable" from "model said this".

### Thresholds (`config/settings.py:397-399`)
- `RECOMMEND_TRADE  = 35` → below this = TRADE
- `RECOMMEND_HOLD   = 55` → 35-55 = HOLD
- `RECOMMEND_REDUCE = 70` → 55-70 = REDUCE; above = AVOID
- `RISK_THRESHOLDS` for label (LOW/MODERATE/HIGH/EXTREME): 0/25/50/75/100

All hardcoded in Python; no env override.

### Silent failure spots
1. **`_compute_sentiment_component` (scorer.py:139)** — returns `(0.5, conf)` even when `score=0, confidence=0` from the cache. The neutral 0.5 risk feeds into the weighted sum without `None`-flagging. A bogus 50/100 sentiment-component risk is treated identically to a legitimate centered sentiment.
2. **`_compute_volatility_component` (scorer.py:82-86)** — if the model file exists but `model.load()` throws, the warning is logged but the user sees `models_available=True` swept away to `False` via the missing return. Actually looking at lines 87-89, the except returns `(None, 0.0)` — that's the same as no file, and the dashboard shows it as "no model". OK.
3. **`_get_fear_greed()` (scorer.py:33)** — caches first call into a module global `_fg_cache`. If the first call fails and returns an `error` dict, subsequent calls return the cached error dict without retrying for the rest of the process lifetime.
4. **`risk/alerts.py:128-149` volatility spike check** — uses `np.log1p(x)` over `pct_change()`. If `x ≤ -1` (price went to zero) the lambda returns 0, silently dropping the signal. Edge case, but unhandled.

---

## 8. Sentiment engine

### Source files and their behavior

| File | Function | Returns | Weight (`SENTIMENT_WEIGHTS`) | Cache TTL (`SENTIMENT_CACHE_TTL`, minutes) |
|---|---|---|---|---|
| `sentiment/fear_greed.py:20` | `fetch_fear_greed()` | `{value, label, normalized ∈ [-1,1], timestamp, source}` | 0.20 (used directly in scorer for both regime and sentiment_score) | 60 |
| `sentiment/dex_sentiment.py:33` | `fetch_dex_sentiment(asset)` | `{score, confidence, buys_1h, sells_1h, ratio_1h, ...}` — neutral for non-DEX | 0.30 | 5 |
| `sentiment/news.py:83` | `fetch_news_sentiment(asset)` | `{score, article_count, confidence, source, asset}` | 0.25 | 20 |
| `sentiment/onchain.py:95` | `fetch_onchain_sentiment(asset)` | `{score, whale_concentration, holder_count, confidence, ...}` — neutral for non-DEX | 0.25 | 60 |
| `sentiment/twitter_scraper.py:195` | `fetch_twitter_sentiment(asset)` (async wrapper) | `{score, tweet_count, confidence}` | **0.00** (dormant) | 15 |

The composite-cache TTL is set to `min(all_source_TTLs) = 5 min` in `sentiment/cache.py:66`. Per-source caches (e.g. news at 20 min in `news.py:21`) protect individual API rate limits independently.

### Cache file locations
- Composite: `cache/sentiment_{asset}.json` (`sentiment/cache.py:14`)
- News per-source: `cache/news_{asset}.json` (`sentiment/news.py:27`)
- Twitter cookies: `cache/twitter_cookies.json` (`twitter_scraper.py:17`)

Live state: `cache/` directory is empty (verified via `ls`).

### FinBERT integration
**Not present.** `sentiment/news.py:7` imports only `from textblob import TextBlob`. There is no `transformers` import anywhere, no `_finbert_pipeline` symbol, no lazy-loader. Per the Phase 6 baseline, this is expected.

### Failed-source fallback (`sentiment/scorer.py:54-89`)
Each source is wrapped in a `try/except`; on failure, the component is set to `{"score": 0.0, "confidence": 0.0}` (lines 60, 66, 72, 79, 86). The aggregator uses `effective_weight = base_weight * confidence`, so a failed source contributes nothing (zero-weighted) rather than zero-padding the score. This is the "zero-padding" rule that CLAUDE.md cites — implementation matches.

### Issue: dead on-chain branch
`sentiment/onchain.py:107` only fires if `ASSET_SOURCE[asset] == "dex"`. After the side-effect re-route in `config/settings.py:444-448`, no asset has source `"dex"` anymore. The on-chain component is **silently neutral for every asset** today. This is a real defect masked by the zero-padding fallback.

---

## 9. Backtesting

### `BacktestEngine` (`backtest/engine.py:98`)

### Commission, slippage, stops
- **Commission**: `BACKTEST_COMMISSION_PCT = 0.001` (settings:420), applied on both entry (engine.py:261) and exit (engine.py:293). 0.1% per side = 0.2% round-trip.
- **Slippage**: **none.** Entry executes at the candle's close; exit executes at the exact stop/take-profit price (engine.py:175-179) or candle close (line 197).
- **Stop loss**: `entry_price * (1 - 0.05)` (engine.py:269), checked on `candle_low <= stop_loss` (line 174). Test `test_engine_stop_loss_uses_low_not_close` (test_backtest.py:274-303) verifies this.
- **Take profit**: `entry_price * (1 + 0.10)` (engine.py:270), checked on `candle_high >= take_profit` (line 177).
- **Order of checks** (line 174-179): stop loss checked before take profit. If both `candle_low <= stop_loss` and `candle_high >= take_profit` are true in the same candle, the stop wins. Conservative.

### Strategies (`backtest/strategies.py`)
- `MACDCrossStrategy` (line 28) — bullish crossover = BUY; bearish = SELL.
- `RSIMeanReversionStrategy` (line 58) — RSI<30 = BUY; RSI>70 = SELL.
- `BollingerBandStrategy` (line 83) — bb_position<0.05 = BUY; >0.95 = SELL.
- `ZAERYNMLStrategy` (line 108) — loads `TrendClassifier`, computes a stripped-down inline "backtest_risk_score" = `trend_uncertainty * 0.6 + momentum_risk * 0.4` (line 152-161). Falls back to MACD if no model file exists (line 134-138).

### Transaction cost reality check
The 0.1% commission is **Coinbase taker-fee specific** (settings:420 comment).
- Crypto on Coinbase: 0.1% taker is approximately right for high-tier users; retail tiers are 0.4-0.6%. So even for the intended domain it's optimistic.
- Stocks: Modern US equity brokers (IBKR, Schwab, Fidelity) are 0%–$0.005/share. A flat 0.1% commission is meaningless and probably high.
- Forex: Commission is essentially zero, but spreads are 1-5 pips and slippage at 1h granularity is real. Modeling it as 0.1% commission silently understates costs at retail size.
- DEX tokens: Birdeye/Jupiter swap fees are 0.20-0.30% plus 0.3-3% slippage depending on liquidity. **For these tokens the current model is materially optimistic by a factor of 3-30x.**

Specific Phase 7 Step 3 file/line targets:
- `config/settings.py:420 BACKTEST_COMMISSION_PCT = 0.001` — replace with a per-asset-class dict.
- `backtest/engine.py:261 entry_cost = position_usd * self.commission_pct` — needs slippage.
- `backtest/engine.py:293 exit_commission = gross_exit_val * self.commission_pct` — same.
- `backtest/engine.py:174-179` — exit-price model assumes perfect fills at the stop/TP price; in reality stop fills tend to slip past the trigger.

---

## 10. Configuration

### Where values live
- **`config/settings.py`** (500 lines) — the only first-class config module.
- **`pytest.ini`** — only `markers` for the `integration` mark.
- **`.env`** (gitignored; `.env.example` shows the keys) — runtime secrets.
- **`requirements.txt`** — dependency pins (no upper bounds, no lockfile).
- **`.gitignore`** — also documents that `scripts/optimize_models.py` and `scripts/best_params.json` are intentionally not tracked.

### Hardcoded values that should be in config
- **`tests/test_yfinance.py:201`** — `assert len(ALL_ASSETS) == 22`. This bakes the universe size into the test suite; if Step 1 introduces an `ACTIVE_ASSETS` flag the test will need updating.
- **`models/features.py:184`** — `rolling(8760, min_periods=100)` for `yearly_position`. 8760 = `ANNUALIZATION_FACTOR` from settings; the `100` minimum is a magic literal.
- **`models/features.py:175-180`** — `vol_ma_10 = volume.rolling(10).mean()`, `vol_ma_30 = volume.rolling(30).mean()`. 10 and 30 are not in `FEATURE_WINDOWS`.
- **`risk/alerts.py:135`** — `* np.sqrt(8760)` literal annualization; should reuse `ANNUALIZATION_FACTOR`.
- **`backtest/engine.py:269-270`** — stop/TP arithmetic uses `self.stop_loss_pct` and `self.take_profit_pct` (good), but the defaults at line 105-106 come from `BACKTEST_STOP_LOSS_PCT`/`BACKTEST_TAKE_PROFIT_PCT` — those are global; no per-asset override exists.
- **`backtest/strategies.py:152-161`** — `_backtest_risk_score` weights `0.6` and `0.4` are hardcoded magic numbers. Should be config-driven (or at minimum named constants).
- **`sentiment/news.py:20-21`** — `RECENCY_DECAY_PER_HOUR = 0.90` and `NEWS_CACHE_TTL_MINUTES = 20` are module-level constants. The TTL is already in `SENTIMENT_CACHE_TTL["news"]`; the duplication is a foot-gun (which one wins?).
- **`sentiment/twitter_scraper.py:18-20`** — `MAX_TWEETS_PER_ACCOUNT = 10`, `MAX_SEARCH_TWEETS = 50`, `TWEET_LOOKBACK_HOURS = 24`. Should be config-driven for tuning.
- **`backtest/metrics.py:85`** — `compute_win_loss_ratio` returns `1.5` as a magic "default" when there are no winners or losers. Hidden assumption (this gets read by `scripts/run_backtest.py:131` and used as the suggested `KELLY_WIN_LOSS_RATIO`).
- **`dashboard/pages/ml_models.py:36`** — `f"{len(trained)}/10"` hardcodes the old 10-asset count.
- **`models/trend.py:37`** — `UNCERTAINTY_THRESHOLD = 0.15` is a class constant; CLAUDE.md treats this as a knob.

### `.env`-dependent values without safe defaults
- **`BIRDEYE_API_KEY`** — `config/settings.py:435` uses `os.getenv("BIRDEYE_API_KEY", "")`. Default empty string. The Birdeye fetcher (`data/birdeye_fetcher.py:38-43`) raises `RuntimeError` if empty. **Will crash any Birdeye fetch if `.env` not loaded.**
- **`HELIUS_API_KEY`** — `sentiment/onchain.py:19` raises `ValueError("HELIUS_API_KEY not set")`. Caught silently in `fetch_onchain_sentiment` (line 120-122) — returns `_null_result`.
- **`NEWSAPI_API_KEY`** — `sentiment/news.py:103-105` returns null result with a warning. Safe.
- **`COINBASE_API_KEY` / `COINBASE_API_SECRET`** — Not actually used in code (verified via grep). They appear in `.env.example` via CLAUDE.md historical reference, but Coinbase's public Exchange API requires no auth for OHLCV. **They're documentation-only env vars** — consider removing from `.env.example`.
- **`TWITTER_USERNAME` / `TWITTER_EMAIL` / `TWITTER_PASSWORD`** — `twitter_scraper.py:39-45` raises `ValueError` if any missing; caught silently in `fetch_twitter_sentiment` (returns `_null_result`). Twitter is currently weight-0 so doesn't matter.

### .env.example
File content (`.env.example`):
```
BIRDEYE_API_KEY=
HELIUS_API_KEY=
NEWSAPI_API_KEY=
TWITTER_USERNAME=
TWITTER_EMAIL=
TWITTER_PASSWORD=
```
Note: `COINBASE_API_KEY`/`COINBASE_API_SECRET` are NOT in `.env.example`. The CLAUDE.md you regenerated lists them as expected env vars — that's stale, they aren't actually needed.

---

## 11. Tests

### Files (8) and rough scope
| File | Tests | Integration tests | Coverage focus |
|---|---|---|---|
| `test_backtest.py` | 36 | 3 | Engine loop, strategies, metrics math (drawdown/Sharpe/Sortino/Calmar/win-loss/profit-factor), serialization |
| `test_birdeye.py` | 15 | 2 | Birdeye fetcher: parsing, pagination stop, dedup, HTTP error handling |
| `test_data.py` | 24 | 1 | Math/time utils, cleaner (validate/clean/anomalies/normalize), storage (upsert/load/snapshots) |
| `test_dex.py` | 14 | 3 | Config sanity, DexScreener pair selection, GeckoTerminal parse, fetch routing |
| `test_models.py` | 22 | 3 | Feature pipeline, leakage smoke test (3 features), targets, VolatilityPredictor + TrendClassifier (train/predict/save/load) |
| `test_risk.py` | 41 | 3 | Risk labels, recommendation thresholds, weight redistribution, Kelly math, position sizing, stop/TP, alerts |
| `test_sentiment.py` | 33 | 4 | score_label, fear & greed, DEX sentiment, news scoring, whale concentration, cache roundtrip, composite scorer |
| `test_yfinance.py` | 21 | 2 | yfinance fetcher quirks, gap_fill toggle, routing, dex-skip-for-yf-assets |

**Total: 216 tests, ~23 integration**. Pytest discovery (`pytest --collect-only -q`) succeeds in 1.01s.

### Coverage of key math (audit checklist)
| Behavior | Test present? | Where |
|---|---|---|
| Kelly criterion correctness at p=0.5, p<0.5, p>0.5, p=0.99 cap | ✅ | `test_risk.py:179-196` |
| Sharpe ratio (zero variance, positive returns, negative returns, insufficient data) | ✅ | `test_risk.py` … actually in `test_backtest.py:105-120` |
| Sortino ratio | ⚠ direct unit test missing; `compute_sortino` is exercised by `test_compute_metrics_keys` (test_backtest.py:308) |
| Max drawdown (no DD, full loss, known DD, edge cases) | ✅ | `test_backtest.py:82-100` |
| Calmar | ⚠ no direct unit test; only via `compute_metrics` |
| Annualized return | ✅ | `test_backtest.py:125-133` |
| Win/loss ratio | ✅ | `test_backtest.py:138-153` |
| Profit factor (all winners → 999 sentinel) | ✅ | `test_backtest.py:350` |
| Feature engineering — all 29 columns present | ✅ | `test_models.py:59` |
| Feature engineering — no look-ahead (3 features sampled) | ✅ (incomplete) | `test_models.py:76` |
| Train/test split is chronological | ✅ | `test_models.py:200` |
| `predict_proba` returns the documented dict | ✅ | `test_models.py:284` |
| Backtest engine — stop loss triggers on candle low | ✅ | `test_backtest.py:274` |
| Backtest engine — commission reduces capital | ✅ | `test_backtest.py:245` |
| Backtest engine — equity curve length | ✅ | `test_backtest.py:233` |
| Risk score within [0, 100] | ✅ | `test_risk.py:316` |
| Risk score weight redistribution | ✅ | `test_risk.py:90-119` |
| Alert triggers (4 types) | ✅ | `test_risk.py:263-314` |
| Sentiment composite — failed source zero-weighted | ⚠ partial (`test_compute_sentiment_score_all_zeros`) |
| Sentiment cache roundtrip / expiry | ✅ | `test_sentiment.py:217-241` |
| News scoring — no API key returns null | ✅ | `test_sentiment.py:130` |
| Whale concentration math (including uiAmount=None fallback) | ✅ | `test_sentiment.py:194-212` |

### Missing or thin spots
1. **Sortino + Calmar have no direct unit tests** — only exercised through `compute_metrics`.
2. **The leakage test only samples 3 of 29 features** (`rsi_14`, `sma_20`, `macd`). Should sweep all 29.
3. **No test that exercises the `yearly_position` feature stability** flagged in Section 5.
4. **No test for `_redistribute_weights` when *every* source fails** sets `total = 0` (line 188-189 returns `{}`); the scorer then weighted-sums to 0 silently — covered by `test_redistribute_all_missing` (test_risk.py:115), good.
5. **No backtest test for transaction-cost accuracy** — the commission test only checks "final capital decreased after a buy+sell"; it doesn't check the exact bps charged.
6. **No survivorship-bias test** for the asset universe.
7. **No regime-stratified evaluation test** for any model.

### Discoverability
Pytest collection succeeds with no errors. Imports are clean.

---

## 12. Scripts

| Script | Purpose | Depends on | Produces | CLI args |
|---|---|---|---|---|
| `fetch_history.py` | 730-day backfill across all `ALL_ASSETS` via the source router | `data.historical.fetch_candles`, `data.cleaner`, `data.storage` | DB rows in `candles` | none |
| `fetch_birdeye_history.py` | Birdeye-only backfill of 5 Solana tokens (900 days) | `data.birdeye_fetcher`, `config.BIRDEYE_API_KEY` | DB rows | none |
| `fetch_stock_forex_history.py` | yfinance backfill of stocks + forex (730 days max) | `data.yfinance_fetcher` | DB rows | none |
| `init_data.py` | Phase 1 validation (7-day pipeline test on 5 Coinbase assets) | imports legacy `ASSETS` | DB rows | none |
| `init_dex_data.py` | Phase 1.5 validation (7-day DEX test, 5 tokens) | `data.gecko_fetcher` | DB rows | none |
| `risk_report.py` | Live risk + position sizing + alert table | `risk.scorer`, `risk.position_sizer`, `risk.alerts` | stdout table, alerts.log | none |
| `run_backtest.py` | Walk-forward backtests (4 strategies × all assets, 90 days) | `backtest.engine`, `backtest.strategies`, `backtest.metrics`, `backtest.reporter` | JSON files in `reports/` | `[asset]` `[strategy]` positional |
| `run_sentiment.py` | Sentiment engine validation (all sources × `SOLANA_TOKENS`/`ALL_ASSETS[:3]`) | every `sentiment/*` module, NLTK auto-download | stdout, `cache/sentiment_*.json` | none |
| `train_models.py` | Train RF+XGB for `ALL_ASSETS` (730 days) | `models.trainer`, `models.volatility`, `models.trend` | `.pkl` files in `models/saved/` | `--retrain` flag |
| `train_dex_models.py` | Train RF+XGB for `[BONK, WIF, PYTH, RAY]` (730 days) — JUP excluded | `models.trainer` | `.pkl` files | none |

### Abandoned / stale
- **`init_data.py`** and **`init_dex_data.py`** are Phase 1 / 1.5 validation runners. They still import the legacy `ASSETS` and don't cover the current universe. Probably should be moved to a `scripts/legacy/` subdir or deleted.
- **`train_dex_models.py`** exists because of one-off retraining of 4 DEX tokens after a refit. Functionally redundant with `train_models.py` if you pass `--retrain` and use the per-asset list. Could be deleted.
- **`scripts/optimize_models.py`** is `.gitignore`d but referenced by comments in `config/settings.py:213` and `:264` as the source of the per-asset hyperparameters. Real reproducibility hole: anyone who wants to re-run the optimizer or audit the search space cannot.

### Common patterns to standardize in Step 1
- Every script does `sys.path.insert(0, ...)` + `load_dotenv()` at the top. Should be replaced with a single `scripts/_bootstrap.py` or solved by making the project a proper installable package (pyproject.toml + console_scripts).
- Every script prints with `print()` + hardcoded `█/─/✓` glyphs. No structured logging output, no MLflow run handle.
- Every script ends with "Commit: git add . && git commit -m 'vX.Y.Z'" — leftover from earlier phases.

---

## 13. Known holes from the strategic roadmap

### 13.1 Transaction cost / slippage modeling
- **Lives at**: `config/settings.py:420` (`BACKTEST_COMMISSION_PCT = 0.001`), `backtest/engine.py:261, 293` (entry/exit commission application).
- **Gap**: single global commission, no slippage, no spread, no per-asset-class differentiation. Stocks, forex, crypto, and DEX all charged 0.1% per side.
- **Specific reality checks**: Section 9 above.

### 13.2 Data leakage audit of 29 features
- **Lives at**: `models/features.py:20-199` (`compute_technical_indicators`), `models/features.py:202-243` (`compute_targets`), `config/settings.py:348-378` (`FEATURE_COLUMNS`).
- **Highest-risk features** (Phase 7 Step 4 should investigate first):
  1. `yearly_position` (features.py:184-191) — 52-week rolling window with `min_periods=100`. Yellow flag for non-stationarity (not pure leakage).
  2. `vol_regime` (features.py:160-164) — divides current vol by 60-bar mean. Could be sensitive if `rolling(60).mean()` produces near-zero divisor for very stable assets (e.g. forex), although the `np.where` guard returns 1.0 in that case (line 163).
  3. `volume_trend` (features.py:175-180) — 10/30 volume ratio. Safe but the magic windows (10, 30) are not in `FEATURE_WINDOWS`.
  4. `vwap_ratio` (features.py:142-149) — 20-bar rolling VWAP. Safe.
  5. `obv` (features.py:128-138) — 50-bar z-score. Safe, but z-score uses past data with no `min_periods` (so first 50 rows produce NaN and get dropped — OK).
- **Test coverage**: `tests/test_models.py:76 test_no_future_leakage_in_features` covers only `rsi_14`, `sma_20`, `macd`. Step 4 should expand to all 29.

### 13.3 Survivorship bias check
- **Asset universe is defined statically** in `config/settings.py`. No point-in-time membership table; no record of which assets were active at a given historical date.
- **Specifically**: BONK was launched late 2022, WIF in late 2023, PYTH in mid-2023, JUP launched January 2024. The DB has data going back to 2023-11-20 for most assets (because that's when ingestion ran), but the model training implicitly assumes these tokens existed during the training window. If you train on Jan 2024 data for JUP, fine — but if you train BONK on Dec 2023 data, you're claiming to have known about BONK before it had a 100-bar history.
- **The DB confirms**: JUP earliest = 2024-01-31, WIF earliest = 2023-11-20. So in practice the storage layer is already point-in-time per-asset, but the universe definition is not.
- **No survivorship test exists.**

### 13.4 Regime-stratified evaluation
- **Does not exist in any form.** Model evaluation is a single chronological 80/20 split (`models/trend.py:75-110`, `models/volatility.py:67-99`). No bull/bear/sideways labeling, no high-vol/low-vol regime split, no Fear & Greed quintile breakdown.
- The closest thing: `vol_regime` is a *feature* (line 160), but it's never used as an *evaluation slice*.

### 13.5 True out-of-sample holdout
- **There is none.** The "test set" in `train()` (the chronological last 20%) is reused as the validation set and is the only out-of-sample evaluation. Hyperparameter search (per the `.gitignore`d `optimize_models.py`) used the same data via `TimeSeriesSplit` — so the published per-asset hyperparameters in `RF_PARAMS_BY_ASSET` / `XGB_PARAMS_BY_ASSET` were tuned on the same data they're now reported on.
- **Recommendation**: Step 4 should carve a final 10–20% slice that no script ever reads until Step 5's final evaluation.

### 13.6 MLflow / reproducibility logging
- **Not present.** Confirmed via grep: no `mlflow` import anywhere in the codebase, no `requirements.txt` entry, no `.mlruns/` directory.
- **Existing logging**: `utils/logger.py` writes to `logs/zaeryn.log`. `risk/alerts.py` writes to `logs/alerts.log`. Backtest reports go to `reports/*.json`. Sentiment cache to `cache/`. There is no central run-id, no parameter capture, no metric history.

### 13.7 Pytest math coverage
- See Section 11 for the per-function checklist.
- Confirmed gaps: direct tests for **Sortino** and **Calmar** are missing. Feature leakage test covers only 3 of 29 features. No transaction-cost-accuracy test. No survivorship test.

---

## 14. Other risks observed

### 14.1 Silent failures
- **On-chain sentiment dead branch** (`sentiment/onchain.py:107`) — gates on `ASSET_SOURCE == "dex"`, but every DEX token routes to `"birdeye"` post-import. On-chain is silently neutral for the entire universe.
- **Sentiment-cache failure returns neutral** (`risk/scorer.py:139`) — `(0.5, 0.0)` flows into the weighted average instead of being `None` and dropped. The user can't tell from the dashboard whether they're looking at a real sentiment reading or a neutralized failure.
- **`_get_fear_greed()` caches first call into a process-global**, including error responses (`risk/scorer.py:36-37`). If the first call fails, every subsequent risk score for the lifetime of the process uses `normalized=0` regardless of whether the API is back up.
- **`scripts/train_dex_models.py:44`** — claims to print "Done. BONK/WIF/PYTH/RAY models saved to models/saved/" even if no model was actually saved.
- **`backtest/strategies.py:134-138`** — `ZAERYNMLStrategy` silently falls back to `MACDCrossStrategy` when no model file is found. This is the right behavior but should at minimum surface a warning to the dashboard, not just a single log line at instantiation.

### 14.2 Missing input validation
- **`risk/position_sizer.py:90 stop_loss_price`** — accepts any `entry_price` without bounds. If a buggy candle gives `entry_price = 0`, returns 0 (after `max(0.0, stop)`).
- **`models/trend.py:179 predict_proba`** — handles single-class RF (only one column in `predict_proba` output) but the heuristic `1.0 - float(probs[0]) if classes_[0]==1 else float(probs[0])` is confusing and untested.

### 14.3 Hardcoded paths
- **`config/settings.py:44-46`** — `DB_PATH = "zaeryn.db"`, `LOGS_DIR = "logs"`, `CACHE_DIR = "cache"` are all relative paths. Anything that runs from a different working directory writes to the wrong location.
- **`config/settings.py:186, 429`** — `MODEL_SAVE_DIR = "models/saved"`, `BACKTEST_REPORTS_DIR = "reports"` also relative.
- **`config/settings.py:413`** — `ALERTS_LOG_FILE = "logs/alerts.log"` relative.

### 14.4 Race conditions
- **`sentiment/cache.py`** — file writes are not atomic (write-in-place at line 25-26). A reader hitting the file mid-write gets a JSON decode error → cache miss → live fetch. The damage is bounded, but it's worth noting.
- **`risk/scorer.py`** — `_fg_cache` is a module global with no lock. Streamlit runs everything single-threaded so this is fine today; not safe under any future multi-process invocation.

### 14.5 Deprecated dependencies
- **`requirements.txt:13`** — `matplotlib` and `seaborn` are listed but I see no import of either in the source tree. Could be drift.
- **`requirements.txt:6`** — `twikit>=2.2.0` — Twitter is dormant; the dependency is large and pulls aiohttp.
- **`requirements.txt:16`** — `optuna>=3.4.0` is only used by the gitignored `optimize_models.py`. Currently dead weight in installs.
- No version upper bounds anywhere → any major-version break in pandas or numpy will silently break the pipeline.

### 14.6 Dead code / drift
- **`data/fetcher.py:2`** still imports `ASSETS` (the 5-asset legacy list).
- **`scripts/init_data.py:6`** same legacy import.
- **`utils/math_utils.py`** — `rolling_mean` and `rolling_std` are pure-Python re-implementations of pandas operations. Used only in `tests/test_data.py`. They duplicate code that's already in pandas; consider deleting.
- **`sentiment/twitter_scraper.py`** — full implementation kept alive at weight 0. 217 lines of code for a dormant feature.
- **`models/volatility.py:36, 83`** — `StandardScaler` field fit + stored but never used (because XGBoost is tree-based). Forward hook for LSTM Step 5 per inline comment.

### 14.7 Suspicious magic numbers
- **`backtest/metrics.py:85`** — `compute_win_loss_ratio` returns `1.5` as a "no data" sentinel. This value is then read by `run_backtest.py:131` and used as a Kelly suggestion. So a strategy with zero trades silently suggests `KELLY_WIN_LOSS_RATIO = 1.5`.
- **`backtest/metrics.py:167`** — `999.0` as the `profit_factor` ceiling when `gross_loss == 0`. Sentinel masquerading as a number.
- **`risk/scorer.py:182`** — RSI `UNCERTAINTY_THRESHOLD = 0.15` per `trend.py:37`. Tunable knob with no obvious provenance.
- **`backtest/strategies.py:160`** — `raw = trend_uncertainty * 0.6 + momentum_risk * 0.4` — 0.6/0.4 magic split.

### 14.8 Behavior that could be wrong silently rather than failing loudly
- **`risk/alerts.py:130-135`** — `lambda x: np.log1p(x) if x > -1 else 0`. Total wipeout (`x = -1`) silently returns 0, which then suppresses the volatility-spike alert exactly when it should fire hardest.
- **`backtest/engine.py:174-179`** — when both stop and take-profit hit in the same candle, stop wins. That's a conservative assumption; for a tight TP relative to wide stop, this systematically under-reports winners.
- **`models/trend.py:179`** — `predict_proba` returns probability `1.0` on degenerate single-class RF if `classes_[0] != 1`. Could cause Kelly to size to the cap on a degenerate model.

---

## 15. Recommended ticket sequence (Phase 7 Step 1: Infrastructure)

These are scoped specifically to Step 1 — infrastructure scaffolding only. Steps 2-5 will be planned after Step 1 lands.

1. **[7/infra] Add `pyproject.toml` and make ZAERYN an installable package.** Migrate `requirements.txt` into `[project] dependencies` with conservative version pins. Add `[project.optional-dependencies] dev = [pytest, ruff, mypy]`. Convert all the `sys.path.insert` shims in `scripts/` to `from zaeryn import ...` via `console_scripts` entries. Result: `pip install -e .[dev]` is the only setup step.

2. **[7/infra] Introduce pydantic-settings config layer at `config/settings.py`.** Wrap the existing 500-line module into typed `Settings` objects (one per concern: `DataSettings`, `ModelSettings`, `RiskSettings`, `BacktestSettings`, `SentimentSettings`). Keep the public symbols importable from `config.settings` for backwards compatibility. Remove the import-time side-effects that mutate `ASSET_SOURCE` and rebuild `ALL_ASSETS`. Introduce `ACTIVE_ASSETS` (crypto-only for Phase 7) separate from `ALL_ASSETS` (full universe in the repo). Update `tests/test_yfinance.py:201` accordingly.

3. **[7/infra] Add ruff configuration and CI hook.** `pyproject.toml`-driven ruff config with the standard rule set + import sorting. Add `pre-commit` hook. First pass should fix the trivial issues (unused imports, dead code, the legacy `ASSETS` import in `data/fetcher.py:2` and `scripts/init_data.py:6`).

4. **[7/infra] Wire MLflow into model training.** Add `mlflow` to deps. Add a thin `utils/mlflow_runner.py` that wraps `train_all_models()` to log: feature column list, hyperparameters, train/test split sizes, all returned metrics, joblib artifact path, git SHA. Touch only `scripts/train_models.py` and `models/trainer.py` for the wiring. Track to a local `./mlruns/` directory; add to `.gitignore`. Acceptance: after `train_models.py --retrain`, `mlflow ui` shows a run per asset with parameters and metrics.

5. **[7/infra] Fix the on-chain sentiment dead branch (`sentiment/onchain.py:107`).** This is a low-effort, high-honesty fix to land in Step 1: change the gate from `ASSET_SOURCE[asset] == "dex"` to `ASSET_SOURCE[asset] in ("dex", "birdeye")`. Add a test that asserts JUP/BONK/WIF/PYTH/RAY all return non-neutral on-chain results when Helius is mocked. Documents the fix in the commit referencing this audit.

6. **[7/infra] Replace hardcoded relative paths with project-rooted paths.** Add `ZAERYN_PROJECT_ROOT` discovery (or use `pyproject.toml` location) and rewrite `DB_PATH`, `LOGS_DIR`, `CACHE_DIR`, `MODEL_SAVE_DIR`, `BACKTEST_REPORTS_DIR`, `ALERTS_LOG_FILE` to resolve against it. Saves us from "ran from wrong cwd, created a second `zaeryn.db`" foot-guns.

7. **[7/infra] Add the missing math unit tests** that Step 4 will rely on: direct `compute_sortino` test, direct `compute_calmar` test, and a single test that loops `test_no_future_leakage_in_features`'s logic over all 29 features in `FEATURE_COLUMNS`. Acceptance: 216 → ~220 collected tests, all passing.

8. **[7/infra] Document the audit findings in `CHANGELOG.md`.** Create `CHANGELOG.md` (new file) with the standard `Keep a Changelog` format. Add the Phase 7 Step 1 section listing every commit and which audit-finding number it closes.

After Step 1 lands, Phase 7 Step 2 (data integrity audit) can use the new MLflow tracking + ruff CI + typed config to safely investigate the leakage and survivorship findings without further infrastructure churn.

---

_End of audit._
