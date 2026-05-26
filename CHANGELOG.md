# Changelog

All notable changes to ZAERYN are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Per-ticket history is tracked via structured commit prefixes
([P{phase}.S{step}.T{ticket}], see CLAUDE.md). Tags mark step and
phase boundaries only.

## [Unreleased]

(empty for now)

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
