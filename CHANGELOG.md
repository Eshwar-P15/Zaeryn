# Changelog

All notable changes to ZAERYN are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Per-ticket history is tracked via structured commit prefixes
([P{phase}.S{step}.T{ticket}], see CLAUDE.md). Tags mark step and
phase boundaries only.

## [Unreleased]

(empty for now)

## [0.7.2] - 2026-05-26

Phase 7 Step 2 — Data Integrity Audit. Comprehensive audit of
feature pipeline (29 features), cross-asset alignment plumbing,
survivorship characteristics, and backtest engine fill-time
semantics. Triages all findings into a remediation backlog
(RM-01 through RM-07) for Phase 7 Steps 3-6.

### Added
- docs/data_integrity_audit.md: full audit deliverable covering
  29 features across 6 concern families, cross-asset alignment,
  survivorship documentation, backtest engine fill-time analysis,
  and triaged remediation backlog (RM-01 through RM-07).
- tests/test_cross_asset_alignment.py: 3-case regression test
  locking the cross-asset alignment contract.
- tests/test_backtest_fill_time.py: 3-case regression test (2
  pass pinning current contract, 1 xfail-strict locking the
  correct fill-at-S+1-open contract).
- README.md Known Limitations section documenting survivorship
  bias systemically across all data sources.
- README.md Phase 5 Sharpe table footnote disclosing the
  impossible-fill finding (RM-01).

### Findings (severity-ordered)
- **S5 — IMPOSSIBLE FILL (RM-01)** across all 4 backtest
  strategies. Engine at `backtest/engine.py:185-192` fills
  trades at the same bar's close where the signal was computed.
  Every Sharpe ratio ZAERYN has ever reported, including the
  README Phase 5 results, is inflated by an unknown magnitude.
  Remediation: new Phase 7 Step 3 (v0.7.3).
- **S3 — log_returns -inf bypass (RM-02).** `np.log(0)`
  survives both `dropna` and `isna` guards because pandas
  treats `inf` as non-NaN. Bundled with RM-01 in Step 3 to keep
  Step 4's cost-drag attribution clean.
- **S2 (RM-03 through RM-07)** — adx_14 zero-warmup artifact +
  hardcoded window (RM-03), bb_upper/bb_lower dead intermediates
  (RM-04), vol_regime intent docstring (RM-05), volume_trend
  magic windows (RM-06), volume_ma20 cross-module assertion
  (RM-07). Bundled as pre-Step 6 retrain prep.
- **S1 and additional S2 — accepted as-is** with documented
  rationale (obv NaN guard incompleteness, obv naming
  convention deferred to Phase 10, returns ffill synthetic-zero
  artifact, realized_vol_20 annualization, yearly_position
  granularity).
- **9 features CRYPTO-COUPLED** — Phase 8 forward-flags (not
  Phase 7 work).
- **0 leaks** of the form the 145-case structural sweep (Step 1
  T7) would catch — the feature pipeline is structurally clean;
  the bugs identified are semantic and downstream of the
  feature graph.

### Changed
- Phase 7 restructured from 5 steps to 6 after T5's S5 finding.
  New Step 3 (engine fill-time remediation + RM-02 guard,
  v0.7.3) inserted; downstream steps shifted by one. Step 6
  closes Phase 7 at v0.8.0.
- CLAUDE.md Phase 7 plan section updated to reflect 6-step
  structure.
- README.md Phase 5 Sharpe table annotated with disclosure
  footnote (table itself preserved; corrected numbers produced
  by Step 4).

### Test Suite
- All pre-existing tests still pass. 6 new tests added (3
  cross-asset, 3 fill-time).
- 45 pre-existing backtest tests in tests/test_backtest.py
  encode the current (broken) fill contract. They will require
  expected-value recomputation when Step 3 ships (sub-task
  within RM-01 acceptance criteria — hand-derived from the same
  synthetic fixtures, not empirically captured).

## [0.7.1] - 2026-05-25

Phase 7 Step 1 — Repo Audit Fixes. Closes audit findings 11, 13.6,
13.7, 14.1, 14.3, 14.5, 14.6, and addresses asset universe
inconsistencies from Section 3.

### Added
- pyproject.toml with installable package definition and centralized
  repo-relative path resolution via utils/paths.py (finding 14.3,
  partial).
- pydantic-settings-based typed configuration in config/settings.py
  with ACTIVE_ASSETS split from full ASSETS universe (Section 3 —
  asset universe inconsistencies).
- Ruff lint + format configuration with pre-commit hook integration
  (infrastructure add).
- Staged-diff safety pre-commit hook scanning for secrets, local
  absolute paths, and binary commits (infrastructure add).
- MLflow tracking wired into models/trainer.py and scripts/
  train_models.py, logging params/metrics/artifacts per run
  (finding 13.6).
- Direct unit tests for compute_sortino and compute_calmar with
  hand-calculated ground truth and Sortino-vs-Sharpe sanity
  inequality (Section 11 — missing/thin spots #1).
- 145-case parametrized feature leakage sweep covering every
  FEATURE_COLUMN x OHLCV input pair (finding 13.7).
- Claude Code Execution Protocol section in CLAUDE.md codifying
  10 tactical execution rules and structured commit prefix convention.

### Changed
- On-chain sentiment branch closed for Birdeye-routed Solana DEX
  assets; routing now respects ASSET_SOURCE (finding 14.1).
- 318 ruff violations resolved across data/, models/, risk/,
  sentiment/, backtest/, dashboard/, scripts/, tests/, utils/
  (findings 14.5, 14.6). 57 files reformatted. 51 unused imports
  removed. 48 timezone modernizations to datetime.UTC. 6 typing
  modernizations to PEP 604 union syntax.
- data/fetcher.py: legacy ASSETS import replaced with
  _COINBASE_POLL_ASSETS derived from ACTIVE_ASSETS filtered by
  ASSET_SOURCE == 'coinbase' (finding 14.6).

### Fixed
- Hardcoded absolute paths replaced with utils/paths.py resolution
  throughout (finding 14.3).

### Test Suite
- 215 tests passing.
- Non-integration runtime under 16 seconds.
- Only warnings are MLflow's pydantic v1 deprecation notices,
  upstream and out of scope.
