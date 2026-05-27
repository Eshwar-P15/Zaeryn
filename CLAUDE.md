# ZAERYN

## Project description
Multi-asset quantitative trading research system combining live market data ingestion, sentiment analysis, ML-based prediction, risk scoring, and walk-forward backtesting. Crypto (Coinbase + Birdeye) is the active universe; stocks and forex code (yfinance) remains in the repo but is frozen during Phase 7. Long-term direction: a defensible multi-agent architecture with specialist LLM agents for research, risk, execution, and narrative monitoring.

## Current state (end of Phase 6)
Phase 1 through Phase 6 work is committed and the repo sits at the academic submission baseline.

What is actually in the repo today:
- `models/`: `features.py`, `trainer.py`, `trend.py` (RF), `volatility.py` (XGBoost). No `lstm.py`, no `ensemble.py`.
- `sentiment/`: `cache.py`, `dex_sentiment.py`, `fear_greed.py`, `news.py`, `onchain.py`, `scorer.py`, `twitter_scraper.py`. `news.py` is TextBlob/VADER only — no FinBERT.
- `data/`: Coinbase (`fetcher.py`), Birdeye (`birdeye_fetcher.py`), DexScreener/GeckoTerminal fallbacks, yfinance (`yfinance_fetcher.py`), SQLite storage (`storage.py`), cleaner, historical loader.
- `backtest/`: `engine.py`, `strategies.py`, `metrics.py`, `reporter.py`.
- `risk/`: `scorer.py`, `position_sizer.py`, `alerts.py`.
- `scripts/`: data fetch runners, `train_models.py`, `train_dex_models.py`, `run_backtest.py`, `risk_report.py`, `run_sentiment.py`, init scripts. No `train_lstm_models.py`.
- `tests/`: `test_models.py`, `test_backtest.py`, `test_birdeye.py`, `test_data.py`, `test_dex.py`, `test_risk.py`, `test_sentiment.py`, `test_yfinance.py`. No `test_lstm.py`, no `test_finbert.py`.
- `dashboard/`: Streamlit app with `pages/`, `components/`, `data_loader.py`.
- Top-level: `zaeryn.db` SQLite store, `candles.csv` export, `requirements.txt`, `pytest.ini`, `.env.example`.

LSTM, ensemble, and FinBERT integration are NOT yet in the repo despite being described in the previous workspace's CLAUDE.md. They were prototyped elsewhere, never committed, and will be re-implemented cleanly in Phase 7 Step 5.

Tech stack: Python 3.12, pandas, numpy, scikit-learn, xgboost, ta, streamlit, yfinance, vaderSentiment, textblob, twikit. Coinbase, Birdeye, and yfinance are the active data sources.

## Active phase
Phase 7: Foundation Hardening. Crypto only for backtesting and training. Stocks and forex code remains in the repo but is excluded from the active universe during this phase.

## Discipline commitments
1. No new model architectures until Phase 10. LSTM and FinBERT re-implementation in Phase 7 Step 5 is the documented exception.
2. No expansion of the active asset universe until Phase 7 ships clean.
3. Every commit references which hole it closes (commit message or CHANGELOG entry).
4. Every phase ends with a tagged version and a one-page results document.
5. The out-of-sample holdout is touched exactly once.

## Claude Code execution protocol

Tactical rules every ticket must follow. Strategic constraints live in
"Discipline commitments" above; these are the per-ticket execution rules.

1. **Read before write.** Verify current state of every file before
   modifying. Never assume what's there from memory or prior prompts.
2. **Scope discipline.** Touch only files explicitly listed in the
   ticket. No drift, no opportunistic cleanup. Surface unrelated
   findings as separate items.
3. **Stage and stop.** Never commit autonomously. Stage changes, run
   verification, report results, wait. Commits are the user's call.
4. **Pre-commit gate is law.** All hooks must pass before reporting
   the ticket done. Fix failures or escalate — never bypass.
5. **Reference the hole.** Every change cites the audit finding,
   ticket, or roadmap step it closes. Commit messages and CHANGELOG
   entries both.
6. **No business logic changes in test-only tickets.** If a test
   reveals a real bug, stop and surface it. Do not silently patch
   production code.
7. **Hand-calculated ground truth for math tests.** Expected values
   are derived from the formula by hand, never from "whatever the
   function returns." Tests that mirror the implementation test nothing.
8. **Explicit deliverables report.** After every ticket: file diff
   summary, hook status, test count (passed/failed/collected), and
   any surprises. No vague "looks good" summaries.
9. **Stop on ambiguity.** Ask before guessing. A 30-second
   clarification beats a 30-minute rollback.
10. **Honest state reporting.** Warnings reported. Skipped tests
    called out. Deprecations flagged. No paper-overs.

### Commit message convention

All ticket commits use the structured prefix `[P{phase}.S{step}.T{ticket}]`
in the subject line, alongside the conventional commit type:
test: [P7.S1.T7] add Sortino/Calmar coverage and leakage sweep
docs: [P7.S1.T8] add CHANGELOG.md with v0.7.1 entry

This makes per-ticket history greppable without polluting the tag
namespace. Tags are reserved for step boundaries (v0.7.1, v0.7.2, ...)
and phase boundaries (v0.8.0, v0.9.0, ...).

## Phase 7 plan (high-level)
Phase 7 = Foundation Hardening, ending at tag `v0.8.0`.

- Step 1 — Repo audit fixes (v0.7.1, ✓ closed May 25, 2026)
- Step 2 — Data integrity audit (v0.7.2, closing May 26, 2026)
- Step 3 — Engine fill-time remediation + log_returns -inf guard (v0.7.3) [NEW step inserted after T5 found S5 IMPOSSIBLE FILL]
- Step 4 — Transaction cost model + cost-aware Phase 5 rerun (v0.7.4)
- Step 5 — Validation infrastructure (holdout, regime labels, nested CV) (v0.7.5)
- Step 6 — Retrain + LSTM/FinBERT re-implementation + final validation (v0.8.0, closes Phase 7)

## Architecture invariants
These are real design decisions still in force from the previous workspace and must be preserved as Phase 7 work lands:
- **`FEATURE_COLUMNS` order is sacred.** 29 features in `models/features.py`; joblib serialization of RF/XGBoost depends on this exact order. Adding or removing features requires retraining every model.
- **`predict_proba()` interface contract.** Any trend model returns a dict with `{up_probability, down_probability, direction, confidence}`. `risk/scorer.py` and `backtest/strategies.py` call `.get("confidence", 0.0)` and `.get("direction")` on this dict — the shape is the contract.
- **Training splits are always chronological**, never shuffled. `MODEL_TEST_SIZE = 0.20`, recency weighting via `np.exp(np.linspace(0, 1, n))`.
- **`init_db()` is idempotent.** Call it anywhere a connection is needed; it creates tables only if missing.
- **Sentiment is cache-first in the risk scorer.** `load_cached_sentiment()` runs before any live fetch; failed sources contribute nothing rather than zero-padding.

## Specifications for upcoming Phase 7 Step 5 work
Forward-looking specs carried from the previous workspace. **Not yet implemented.** These are the contracts the Step 5 implementation must satisfy:
- **LSTM (`models/lstm.py`, not yet present):** 2-layer LSTM, hidden=128, 48-candle sequence window, BCELoss + Adam. `predict_proba()` returns a float P(up) — LSTM is only called through the ensemble. Saves to `models/saved_lstm/{asset}.pt` plus `{asset}_scaler.pkl`. All methods auto-skip gracefully if torch is not installed.
- **Ensemble (`models/ensemble.py`, not yet present):** 40% LSTM + 60% RF (`ENSEMBLE_LSTM_WEIGHT` / `ENSEMBLE_RF_WEIGHT`). `predict_proba()` returns the **same dict shape** as `TrendClassifier.predict_proba()` so it is a drop-in replacement. Falls back to RF-only (weight 1.0) if LSTM weights are missing. `load(asset)` loads both and adjusts weights if only one is available.
- **FinBERT (`sentiment/news.py`):** lazy-loaded singleton (`_finbert_pipeline`). Falls back to TextBlob if FinBERT unavailable. Routes by `ASSET_CLASS[asset]` to `STOCK_NEWS_KEYWORDS` / `FOREX_NEWS_KEYWORDS` / `ASSET_NEWS_KEYWORDS`.

## Conventions
- Branch naming: `phase-N/short-description` (e.g., `phase-7/centralized-config`).
- Commit messages: `[phase/category] present-tense description` (e.g., `[7/infra] migrate to pyproject.toml`).
- Python: 3.12, managed by uv, virtual env at `.venv/`.
- Tests: pytest, in `tests/`, mirror the source structure.
- Formatting and lint: ruff (added in Phase 7 Step 1).
- Experiment tracking: MLflow (added in Phase 7 Step 1).

## Guardrails for Claude Code
- Do NOT install `torch`, `transformers`, or `accelerate` during Phase 7 Steps 1–4. They are installed only when Step 5 begins.
- Do NOT add new asset classes or modify the active universe during Phase 7.
- When modifying code, add or update tests in the same change.
- Do not commit on the user's behalf. Stage changes for the user to review and commit themselves.
- When in doubt about design decisions, refer to the Architecture invariants section above and the previous workspace's CLAUDE.md at `/mnt/c/Coding/ZAERYN/CLAUDE.md`.

## File structure
- `backtest/`: walk-forward backtesting engine, strategies, metrics, reporter.
- `config/`: centralized settings (`settings.py`) — asset universe, model horizons, feature columns, cache TTLs.
- `dashboard/`: Streamlit app with multi-page UI and cached DB/model loaders.
- `data/`: ingestion adapters (Coinbase, Birdeye, DexScreener, GeckoTerminal, yfinance), cleaning, SQLite storage, historical loader.
- `logs/`: runtime log output (gitignored).
- `models/`: feature engineering, trainer, RF trend classifier, XGBoost volatility predictor. LSTM/ensemble land here in Phase 7 Step 5.
- `risk/`: composite risk score, Kelly position sizer, alerting hooks.
- `scripts/`: standalone runner entry points for fetch, train, backtest, sentiment, and risk reports.
- `sentiment/`: per-source sentiment fetchers (news, DEX flow, on-chain, fear & greed, Twitter), cache layer, aggregator.
- `tests/`: pytest suite mirroring source layout.
- `utils/`: shared helpers — logger, math utilities, time utilities.

## Environment variables
Expected `.env` keys (file is gitignored and never committed):
- `COINBASE_API_KEY`
- `COINBASE_API_SECRET`
- `HELIUS_API_KEY`
- `NEWSAPI_API_KEY`
- `BIRDEYE_API_KEY`

## Reference
The strategic roadmap PDF (kept by the user) defines Phases 7 through 11 in detail and is the authoritative source for what comes next.
