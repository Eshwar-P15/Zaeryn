# ZAERYN Data Integrity Audit

Phase 7 Step 2 deliverable. Hunts semantic leaks the structural
145-case leakage sweep (tests/test_models.py) cannot detect.
Cross-asset alignment (T3), survivorship bias (T4), and backtest
fill-time (T5) findings live in their own sections.

## Status
| Ticket | Owner | Status |
|---|---|---|
| T1 (this doc + scaffold) | main agent | DONE |
| T2 (per-family audit, 6 subagents) | parallel subagents | DONE |
| T3 (cross-asset alignment) | main agent | DONE |
| T4 (survivorship bias) | TBD | PENDING |
| T5 (backtest fill-time) | TBD | PENDING |
| T6 (triage + remediation tickets) | main agent | PENDING |

## Scope
- 29 features in FEATURE_COLUMNS (config/_models.py:165-197).
  Note: 26 features are computed in models/features.py and 3
  (returns, log_returns, price_range) are computed in
  data/cleaner.py:111-113. The cleaner module also produces
  volume_ma20 (data/cleaner.py:114) as an intermediate consumed by
  volume_ratio in models/features.py:106; this cross-module
  dependency is surfaced in Family (d) implementation hygiene but
  is not itself a FEATURE_COLUMNS member.
- Cross-asset alignment correctness (separate, T3).
- Backtest engine fill-time semantics (separate, T5).
- Survivorship bias acknowledgment (separate, T4).

## Anti-scope (what T2 subagents must NOT do)
- Modify any code file. Audit is read-only.
- Audit model training code (models/trainer.py).
- Audit backtest engine internals (reserved for T5).
- Audit cross-asset alignment (reserved for T3).
- Propose refactors beyond severity-driven remediation tickets.
- Re-audit features outside their assigned family.
- Re-derive analysis another subagent will produce (e.g., shared
  `_macd` object analysis happens once in Family (a), not three
  times across macd/macd_signal/macd_hist).
- Evaluate equity or forex applicability. Audit assumes crypto-only
  context (24/7 hourly Coinbase data). Cross-market validity is
  Phase 8 work. Forward-flag via checklist item 9 only.

## Audit checklist
Each feature is evaluated against 9 questions. Each gets a verdict:
PASS / CONCERN / LEAK SUSPECTED / LEAK CONFIRMED / N/A.

1. **Lookback window correctness.** Rolling/expanding windows must
   reference only bars strictly prior to the evaluation bar.
   - LEAK: `df['x'].rolling(20).mean()` used as the value AT row t
     (includes row t itself).
   - CLEAN: `df['x'].shift(1).rolling(20).mean()` or window applied
     to lagged series.

2. **Normalization timing.** Statistics (mean, std, min, max, rank)
   used for normalization must come from past data only.
   - LEAK: `(x - x.mean()) / x.std()` over the full series.
   - CLEAN: rolling z-score with explicit window, computed on lagged
     data.

3. **NaN/missing handling.** No backward-fill anywhere. Forward-fill
   only on data already observable at the fill timestamp.
   - LEAK: `df.bfill()` of any kind.
   - LEAK: `df.fillna(method='ffill')` on irregularly-sampled
     external data where "the last observed value" is unknown until
     after the bar.
   - CLEAN: leading NaN preserved during indicator warmup.

4. **Granularity / timezone / resample boundaries.** Aggregations
   across time boundaries must use observable timestamps in the
   asset's native timezone, and the granularity of the input must
   match assumptions baked into the feature.
   - LEAK: yearly_position assumes 8760 bars = 1 year but is fed
     a 1d series (would silently become 24 years).
   - CLEAN: granularity is asserted or derived from the index.

5. **Indicator library convention.** Many `ta`-library indicators
   default to including the current bar in their window. Verify
   each `ta.*` call against the library's documented behavior.
   - LEAK: `ta.trend.SMAIndicator(close, 20).sma_indicator()` if it
     emits the value at index t computed from rows [t-19, t].
   - CLEAN: the same call wrapped in `.shift(1)`, OR documented
     verification that the library lags by one bar by default.

6. **Cross-asset / external dependency.** Any feature referencing
   data from outside the asset's own OHLCV must be flagged for T3.
   - In current FEATURE_COLUMNS this should return N/A for all
     features (Family 0 absence). Flag any that don't.

7. **Label leakage / target smoothing.** Feature must not be a
   transformation that effectively peeks at the prediction target.
   - LEAK: feature is the moving average of future returns.
   - CLEAN: feature is a transformation of past observable data only.

8. **Intent match.** The feature's name and documented intent must
   match its implementation.
   - MISMATCH: `obv` named "On-Balance Volume" but implementation
     is z-scored OBV over 50 bars.
   - MISMATCH: `vol_regime` implies categorical regime but
     implementation returns continuous ratio.
   - MATCH: `rsi_14` named and implemented as 14-period RSI.

9. **Asset-class portability (informational, Phase 8 forward-flag).**
   Does the feature's correctness depend on assumptions specific to
   24/7 crypto data? Specifically:
   - Continuous bars with no session boundaries
   - 8760 bars/year annualization
   - Dollar-denominated single-venue volume
   - Calendar features assuming all 24 hours and 7 days are
     populated and meaningful
   If any assumption is crypto-coupled, mark
   `PORTABILITY: CRYPTO-COUPLED` and name the specific assumption.
   This is NOT a leak finding — it's a forward-flag for Phase 8
   stock integration. Severity for this item is always N/A.
   Features with no crypto-specific assumptions mark
   `PORTABILITY: PORTABLE`.

## Severity rubric
| Level | Definition | Worked example |
|---|---|---|
| **S5 — Critical** | Confirmed leak materially affecting model output. Must be fixed before any retraining. | Z-score normalization computed using full-series statistics including future bars. |
| **S4 — High** | Confirmed leak with minor numerical impact, OR strongly suspected leak in a feature the model relies on heavily. | Forward-fill of sentiment data at the start of the series pulls 5 future observations backward. |
| **S3 — Medium** | Concern with > 50% probability of being a real leak or intent violation, requires verification. | `ta` library RSI default may include the current bar — needs library-version check. |
| **S2 — Low** | Imperfection without performance impact. Inconsistency or hygiene issue. | Feature computed in cleaner.py instead of features.py with no documented rationale. |
| **S1 — Informational** | Documented quirk worth tracking but not acting on. | `yearly_position` hardcoded to 8760 bars — works at 1h granularity, breaks silently at others. |

S3 and above open remediation tickets in T6. S2 and S1 are
documented as accepted-as-is with rationale.

Portability flags from checklist item 9 are tracked separately
(see "Phase 8 portability forward-flags" section) and do not
receive a severity.

## Evidence standards
Every finding must include:
- **Citation:** `file:line` (specific line range, not whole file).
- **Code reference:** quoted snippet under 15 words, or a paraphrase
  of the relevant logic if longer.
- **Reasoning chain:** 1–3 sentences connecting the code to the
  checklist question.

"Looks fine" is not a finding. Findings without evidence get
rejected at T6 triage.

## Prior audit acknowledgment (mandatory for T2 subagents)
`docs/repo_audit.md` §13.2 lists 5 highest-risk features. Quoted
verbatim (each under 15 words):

1. **`yearly_position`** — "52-week rolling window with `min_periods=100`. Yellow flag for non-stationarity (not pure leakage)."
2. **`vol_regime`** — "Divides current vol by 60-bar mean; sensitive if `rolling(60).mean()` produces near-zero divisor."
3. **`volume_trend`** — "10/30 volume ratio; safe but magic windows (10, 30) not in `FEATURE_WINDOWS`."
4. **`vwap_ratio`** — "20-bar rolling VWAP. Safe."
5. **`obv`** — "50-bar z-score; safe but no `min_periods`, first 50 rows produce NaN (dropped)."

Every T2 subagent whose family contains one of these features must
either:
(a) explicitly verify the prior finding and assign final severity, or
(b) explicitly refute it with code-cited reasoning.

Starting from zero on a §13.2-flagged feature is grounds for the
finding being rejected at T6 triage.

## Family 0 — Coverage gaps

This family has zero entries in FEATURE_COLUMNS. The absences
themselves are findings.

### Absent: sentiment features
Status: sentiment is computed in risk/scorer.py and consumed by
the risk-scoring layer, but never enters the model feature matrix.
- Implication: model predictions are uninformed by sentiment.
- Phase 7 Step 5 (FinBERT re-implementation) will change this.
- Audit slot reserved for re-evaluation after Step 5 lands.
- Severity: N/A (design state, not a leak).

### Absent: cross-asset / universe-relative features
Status: every feature is computed from the asset's own OHLCV. No
correlations, betas, dispersion measures, or universe-relative
ranks exist anywhere in FEATURE_COLUMNS.
- Implication: every signal is asset-myopic. The model cannot
  detect when an asset's move is universe-wide vs idiosyncratic.
- Strategic flag for Phase 10 (portfolio risk + correlation layer).
- Severity: N/A (design state, not a leak).

## Family (a) — Trend / Moving averages (8 features)

Subagent assignment: 1 of 6, parallel.

Features:
- sma_20 (models/features.py:39)
- sma_50 (models/features.py:41)
- ema_12 (models/features.py:43)
- ema_26 (models/features.py:45)
- macd (models/features.py:53)
- macd_signal (models/features.py:54)
- macd_hist (models/features.py:55)
- macd_hist_momentum (models/features.py:179)

Shared implementation notes:
- sma_20 and sma_50 both use ta.trend.SMAIndicator — audit once,
  apply to both.
- ema_12 and ema_26 both use ta.trend.EMAIndicator — audit once.
- macd, macd_signal, macd_hist share one _macd object — audit the
  object once, evaluate the three columns it produces.
- macd_hist_momentum is composed from macd_hist via .diff() —
  audit the composition.

Prior audit notes: §13.2 does NOT flag any feature in this family.

### Findings (filled by T2 Subagent a)

**Library version confirmed:** `ta==0.11.0` installed. `pyproject.toml` pins `ta>=0.10.2,<1.0`.

**Indicator library convention — shared determination (applied to all 8 features):**
`_sma` is `series.rolling(window=periods, min_periods=periods).mean()` — pandas rolling with `fillna=False` (the default used in all feature calls) sets `min_periods=periods`, meaning row t's value is the mean of rows [t-periods+1 … t], including row t itself. Similarly, `_ema` is `series.ewm(span=periods, min_periods=periods, adjust=False).mean()` — pandas `.ewm()` computes a running EMA that always includes row t. No `.shift(1)` is applied anywhere in the feature pipeline before or after these calls. For SMA/EMA/MACD used as feature values themselves, this is the standard convention: at bar t, the trader observes the close price at t and can compute SMA(close_t, close_{t-1}, …, close_{t-19}). This is causal — the value at t is available at t. No future information is used.

#### sma_20

- **Implementation:** `models/features.py:39`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:39` `ta.trend.SMAIndicator(close=df["close"], window=w["sma_short"]).sma_indicator()` — `_sma` calls `series.rolling(window=20, min_periods=20).mean()` (`ta/utils.py:60-61`), computing the 20-bar mean ending at row t using only rows [t−19…t]. All 20 bars are causally observable at bar t. No future data referenced.
2. Normalization timing: N/A. Evidence: `features.py:39` — SMA is not normalized; it is a raw price-scale value.
3. NaN/missing handling: PASS. Evidence: `ta/utils.py:60` `min_periods=periods` when `fillna=False` — leading NaN rows preserved during warmup. `features.py:278` `df.dropna(subset=required)` removes warmup NaN rows downstream.
4. Granularity / timezone / resample boundaries: PASS. Evidence: `features.py:39` — operates on native 1h candle index; no resampling.
5. Indicator library convention: PASS. Evidence: `ta/utils.py:59-61` `series.rolling(window=periods, min_periods=periods).mean()` — includes row t causally. Standard convention; no shift needed.
6. Cross-asset / external dependency: N/A. Evidence: `features.py:39` — only references `df["close"]`.
7. Label leakage / target smoothing: PASS. Evidence: `features.py:39` — backward-looking smoothing of past close prices.
8. Intent match: PASS. Evidence: `config/_models.py:148` `"sma_short": 20` — exact name/implementation match.
9. Asset-class portability: PORTABLE. Evidence: `features.py:39` — SMA carries no crypto-specific assumption.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### sma_50

- **Implementation:** `models/features.py:41`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:41` `ta.trend.SMAIndicator(window=w["sma_long"])` resolves to `50` (`config/_models.py:149`). Identical `_sma` implementation, operating on rows [t−49…t]. Fully causal.
2. Normalization timing: N/A. Evidence: `features.py:41` — raw price-scale SMA.
3. NaN/missing handling: PASS. Evidence: `ta/utils.py:60` `min_periods=50` — first 49 rows NaN. No backfill.
4. Granularity / timezone / resample boundaries: PASS. Evidence: `features.py:41` — native 1h index; no resampling.
5. Indicator library convention: PASS. Evidence: same `_sma` function as sma_20.
6. Cross-asset / external dependency: N/A. Evidence: `features.py:41` — only `df["close"]`.
7. Label leakage / target smoothing: PASS. Evidence: backward-looking only.
8. Intent match: PASS. Evidence: `config/_models.py:149` `"sma_long": 50` — exact match.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### ema_12

- **Implementation:** `models/features.py:43`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:43` `ta.trend.EMAIndicator(window=w["ema_fast"])` resolves to `12` (`config/_models.py:150`). `_ema` calls `series.ewm(span=12, min_periods=12, adjust=False).mean()` (`ta/utils.py:64-66`). EWM is a running computation; at row t it incorporates close prices from start of series through close_t, exponentially weighted. All causally observable.
2. Normalization timing: N/A. Evidence: `features.py:43` — raw price-scale EMA.
3. NaN/missing handling: PASS. Evidence: `ta/utils.py:64-66` `min_periods=12` — first 11 rows NaN. No backfill.
4. Granularity / timezone / resample boundaries: PASS. Evidence: native 1h candle index.
5. Indicator library convention: PASS. Evidence: `ta/utils.py:64-66` — EWM running computation includes row t causally. `adjust=False` recursive EMA; standard convention.
6. Cross-asset / external dependency: N/A. Evidence: `features.py:43` — only `df["close"]`.
7. Label leakage / target smoothing: PASS. Evidence: backward-looking EWM.
8. Intent match: PASS. Evidence: `config/_models.py:150` `"ema_fast": 12` — exact match.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### ema_26

- **Implementation:** `models/features.py:45`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:45` `ta.trend.EMAIndicator(window=w["ema_slow"])` resolves to `26` (`config/_models.py:151`). Identical `_ema` implementation, span=26, min_periods=26.
2. Normalization timing: N/A.
3. NaN/missing handling: PASS. Evidence: `min_periods=26` — first 25 rows NaN. No backfill.
4. Granularity / timezone / resample boundaries: PASS.
5. Indicator library convention: PASS. Evidence: same `_ema` function as ema_12.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Evidence: `config/_models.py:151` `"ema_slow": 26`.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### macd

- **Implementation:** `models/features.py:47-53`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Shared `_macd` object audit:** constructed at `features.py:47-52` as `ta.trend.MACD(close=df["close"], window_slow=26, window_fast=12, window_sign=9)`. Inside `MACD._run()` (`ta/trend.py:115-120`): `_emafast = _ema(close, 12); _emaslow = _ema(close, 26); _macd = _emafast - _emaslow; _macd_signal = _ema(_macd, 9); _macd_diff = _macd - _macd_signal`. All EMA computations use the causal `_ema` function. No future data accessed at any stage.

**Checklist results:**

1. Lookback window: PASS. Evidence: `ta/trend.py:116-118` `_macd = _emafast - _emaslow` — difference of two causal EMAs.
2. Normalization timing: N/A. Evidence: `features.py:53` — price-difference quantity, not normalized.
3. NaN/missing handling: PASS. Evidence: dominant warmup is 26-bar slow EMA; first 25 rows NaN.
4. Granularity / timezone / resample boundaries: PASS.
5. Indicator library convention: PASS. Evidence: same causal `_ema` chain.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Evidence: `features.py:53` `df["macd"] = _macd.macd()` — standard MACD line.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### macd_signal

- **Implementation:** `models/features.py:47-54`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `ta/trend.py:119` `_macd_signal = _ema(_macd, 9)` — 9-period EMA of MACD line, itself causal. Total effective lookback ≈26 bars.
2. Normalization timing: N/A. Evidence: `features.py:54` — raw signal-line value.
3. NaN/missing handling: PASS. Effective NaN extent is ~25 leading rows (dominated by slow-EMA warmup).
4. Granularity / timezone / resample boundaries: PASS. Evidence: signal window 9 from `w["macd_signal"]` (`config/_models.py:152`).
5. Indicator library convention: PASS. Same causal `_ema`.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Evidence: `features.py:54` — standard 9-period EMA of MACD line.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### macd_hist

- **Implementation:** `models/features.py:47-55`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `ta/trend.py:120` `_macd_diff = _macd - _macd_signal` — element-wise difference of two causal series.
2. Normalization timing: N/A.
3. NaN/missing handling: PASS. ~25 leading NaN rows from slow-EMA warmup.
4. Granularity / timezone / resample boundaries: PASS.
5. Indicator library convention: PASS. Pure arithmetic on causal EMAs.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Evidence: `features.py:55` — standard MACD histogram (line − signal).
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### macd_hist_momentum

- **Implementation:** `models/features.py:179`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:179` `df["macd_hist"].diff()` — pandas `.diff()` with default `periods=1` computes `macd_hist[t] - macd_hist[t-1]`. 1-lag difference of an already-causal series.
2. Normalization timing: N/A.
3. NaN/missing handling: PASS. Evidence: `.diff(periods=1)` introduces exactly one additional leading NaN. Total prefix ~26 rows (25 EMA warmup + 1 diff). Dropped by `dropna`.
4. Granularity / timezone / resample boundaries: PASS. Evidence: 1-bar lag = 1 hour at native granularity.
5. Indicator library convention: N/A — pure pandas `.diff()`.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Evidence: `features.py:178-179` comment `"MACD histogram momentum: acceleration/deceleration of momentum"` — `.diff()` is the correct discrete derivative.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

**Family-level notes**

1. **Causal convention uniformly satisfied.** The `ta` library's `_sma` and `_ema` both include the current bar t, but bar t's close is the bar's own observable value — not a future bar. No feature in this family references close_{t+1} or beyond.
2. **`fillna=False` is the default and is in effect for all `ta` calls.** No `fillna=True` or explicit `fillna` keyword appears in `features.py` (confirmed by grep). Leading NaN warmup rows correctly preserved.
3. **`_macd` object audited once, verdicts applied to three features.** `MACD._run()` at `ta/trend.py:115-120` is the single code path; individual method calls (`macd()`, `macd_signal()`, `macd_diff()`) are thin wrappers.
4. **`macd_hist_momentum`'s `.diff()` introduces exactly one additional leading NaN** on top of the ~25-row EMA-26 warmup, for a total prefix of ~26 rows.
5. **No cross-asset or external-data dependency** in any Family (a) feature; checklist item 6 returns N/A uniformly.
6. **FEATURE_WINDOWS values confirmed.** `sma_short=20`, `sma_long=50`, `ema_fast=12`, `ema_slow=26`, `macd_signal=9` in `config/_models.py:148-152`.
7. **All 8 features are PORTABLE** — none rely on 24/7 continuous bars, 8760 bars/year annualization, or single-venue volume.

## Family (b) — Momentum oscillators + trend-strength (5 features)
Subagent assignment: 2 of 6, parallel.

Features:
- rsi_14 (models/features.py:65)
- roc_10 (models/features.py:67)
- williams_r_14 (models/features.py:70-75)
- adx_14 (models/features.py:152-157)
- price_vs_sma20 (models/features.py:57-61) — uses sma_20 (Family a)

Prior audit notes: §13.2 does NOT flag any feature in this family.

### Findings (filled by T2 Subagent b)

#### rsi_14

- **Implementation:** `models/features.py:65`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `ta/momentum.py:37` `diff = self._close.diff(1)` — RSI computed from price differences only; diff(1) references bar t and bar t-1. EWM accumulation is causal.
2. Normalization timing: N/A. RSI is a bounded oscillator (0-100); no statistical normalization applied.
3. NaN/missing handling: PASS. Evidence: `ta/momentum.py:40` `min_periods = 0 if self._fillna else self._window` — `fillna=False` default, so `min_periods=14`. Leading rows remain NaN; no backfill.
4. Granularity/timezone/resample boundaries: N/A — pure price-difference oscillator.
5. Indicator library convention: PASS. Evidence: `ta/momentum.py:37` — `diff(1)` is backward; output at index t computed from data ≤ t.
6. Cross-asset / external dependency: N/A. Uses only `df["close"]`.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Evidence: `config/_models.py:153` `"rsi": 14` — 14-period Wilder RSI; name and implementation consistent.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### roc_10

- **Implementation:** `models/features.py:67`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `ta/momentum.py:394` `self._close - self._close.shift(self._window)` — ROC at row t uses close[t] − close[t−10]. Only past bars referenced.
2. Normalization timing: N/A. Ratio of two point-in-time closes.
3. NaN/missing handling: PASS. Evidence: `fillna=False` default; first 10 rows NaN from `shift(10)`. No backfill.
4. Granularity/timezone/resample boundaries: N/A — fixed bar count, not calendar interval.
5. Indicator library convention: PASS. Evidence: `ta/momentum.py:393-396` — purely shift-based, no rolling window.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS. Evidence: `shift(10)` is backward.
8. Intent match: PASS. Evidence: `config/_models.py:156` `"roc": 10` — name matches.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### williams_r_14

- **Implementation:** `models/features.py:70-75`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `ta/momentum.py:531-537` — `self._high.rolling(self._lbp, min_periods=min_periods).max()` is backward-looking; at row t covers [t-13, t]. Canonical Williams %R formula includes current bar.
2. Normalization timing: N/A. Bounded [-100, 0] by construction.
3. NaN/missing handling: PASS. Evidence: `ta/momentum.py:530` `min_periods=14` (fillna=False). Leading 13 rows NaN.
4. Granularity/timezone/resample boundaries: N/A.
5. Indicator library convention: PASS. Evidence: `ta/momentum.py:531-537` `highest_high = self._high.rolling(lbp).max()` — definitionally correct per textbook Williams %R.
6. Cross-asset / external dependency: N/A. Uses high, low, close from own OHLCV.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Evidence: `config/_models.py:157` `"williams_r": 14`. Comment at `features.py:69` correctly documents [-100, 0] range.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### adx_14

- **Implementation:** `models/features.py:152-157`
- **Audit verdict:** CONCERN
- **Severity:** S2 — Low
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: CONCERN. Evidence: `ta/trend.py:722-723` `close_shift = self._close.shift(1)` correctly shifts close. Directional movement at `ta/trend.py:741-742` `diff_up = self._high - self._high.shift(1)` uses current bar high minus prior bar high — canonical and causal. The deeper concern is at `ta/trend.py:729-731` `self._trs_initial = np.zeros(self._window - 1)` — first `window-1` warmup positions pre-filled with **zeros, not NaN**. After concatenation at line 814, the first 13 rows contain 0.0 (not NaN) and survive `dropna` since zeros are not NaN. These zero rows enter training as legitimate-looking measurements.
2. Normalization timing: N/A. Bounded [0, 100].
3. NaN/missing handling: CONCERN. Evidence: `ta/trend.py:729` `np.zeros(self._window - 1)` — warmup rows initialized to 0.0 instead of NaN. `build_feature_matrix` `dropna` at `features.py:278` cannot catch zero-valued warmup rows. Impact: up to 13 rows per asset enter training with ADX=0.0 (an artifact, not a measurement). Severity S2: ADX values near 0 can legitimately occur in choppy markets, so the zeros are not directionally misleading; but they are wrong.
4. Granularity/timezone/resample boundaries: N/A. Pure price-based rolling indicator.
5. Indicator library convention: PASS (with the hygiene concern above). Evidence: `ta/trend.py:722` — close lagged correctly per Wilder definition.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS (minor hygiene). Evidence: `adx_14` uses `window=14` hardcoded at `features.py:156` rather than reading from `FEATURE_WINDOWS`. Comment at `features.py:151` matches canonical interpretation. Hygiene gap: no `FEATURE_WINDOWS["adx"]` key.
9. Asset-class portability: PORTABLE. OHLC-only; no annualization or calendar assumption.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** Open S2 ticket at T6: either (a) wrap the ADX call with `.replace(0, np.nan)` on the first `window-1` rows, or (b) raise a note for Step 5 retrain to monitor first-N-row ADX values. Resolve before Phase 7 Step 5 retraining to prevent contaminating the full dataset. Companion hygiene item: add `FEATURE_WINDOWS["adx"]` and dereference at `features.py:156`.

#### price_vs_sma20

- **Implementation:** `models/features.py:57-61`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS (composition only; sma_20 trust delegated to Family (a)). Evidence: `features.py:57-61` — `(df["close"] - df["sma_20"]) / df["sma_20"]`; no additional rolling/shifting in composition.
2. Normalization timing: N/A. Ratio against past-looking mean, not full-series statistic.
3. NaN/missing handling: PASS. Evidence: `features.py:58` `np.where(df["sma_20"].notna() & (df["sma_20"] > 0), ..., np.nan)` — propagates NaN cleanly; no backfill.
4. Granularity/timezone/resample boundaries: N/A.
5. Indicator library convention: N/A — pure pandas arithmetic.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Fractional deviation of close from 20-period SMA; division by sma_20 makes it scale-invariant.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

**Family-level notes**

1. **Ta library convention consistency across momentum indicators.** RSI uses `diff(1)` + causal EWM. ROC uses `shift(window)` (pure past lookup). Williams %R uses `rolling(lbp).max/min` including the current bar (definitionally correct). None require an additional `.shift(1)` wrapper.
2. **ADX zero-warmup is the family's outlier.** ADX is the only indicator in Family (b) — and likely the only one across all six families — where the `ta` library emits zeros (not NaN) during warmup (`ta/trend.py:729` `np.zeros(self._window - 1)`). All other `ta` indicators emit NaN. `dropna` catches NaN but not zero. S2 finding.
3. **price_vs_sma20 composition is clean.** Guard `df["sma_20"].notna() & (df["sma_20"] > 0)` correctly handles both warmup (NaN propagation) and DEX-token zero-price edge case. Same `np.where` pattern as `volume_ratio` at `features.py:106-110`.
4. **ADX hardcoded window** at `features.py:156` is the only window in this family not read from `FEATURE_WINDOWS`. Hygiene companion to the S2 finding.
5. **Portability summary:** all 5 features in Family (b) are PORTABLE. No annualization, no session-boundary logic, no 8760-bar assumptions.

## Family (c) — Volatility (5 features)
Subagent assignment: 3 of 6, parallel.

Features:
- atr_14 (models/features.py:79-84)
- bb_width (models/features.py:93)
- bb_position (models/features.py:94)
- realized_vol_20 (models/features.py:98-100)
- vol_regime (models/features.py:145-149) — composed from realized_vol_20

Implementation hygiene to investigate:
- bb_upper and bb_lower (models/features.py:91-92) are materialized
  but absent from FEATURE_COLUMNS. Determine: dead intermediates,
  future scaffolding, or used elsewhere.

Prior audit notes (§13.2): vol_regime is flagged as highest-risk.

### Findings (filled by T2 Subagent c)

#### atr_14

- **Implementation:** `models/features.py:79-84`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `ta/volatility.py:47` `close_shift = self._close.shift(1)` — Wilder-smoothed ATR accumulator initializes with first `window` bars' mean then applies EMA-style update; references only past data. No current-bar close in the TR computation at bar t.
2. Normalization timing: PASS. ATR is a raw price-difference measure (units = price); no statistical normalization applied.
3. NaN/missing handling: PASS. Evidence: `ta/volatility.py:93` `min_periods = self._window` when `fillna=False` — first 14 rows NaN. No backfill.
4. Granularity/timezone/resample boundaries: PASS. Native 1h series; no resampling.
5. Indicator library convention: PASS. Evidence: `ta/volatility.py:47` "close_shift = self._close.shift(1)" — lagged close used for TR; bar t's TR = max(H_t − L_t, |H_t − C_{t-1}|, |L_t − C_{t-1}|).
6. Cross-asset / external dependency: N/A. Uses only own H/L/C.
7. Label leakage / target smoothing: PASS. Past OHLCV only.
8. Intent match: PASS. Evidence: `config/_models.py:154` `"atr": 14` — name/implementation congruent.
9. Asset-class portability: PORTABLE. No session-boundary or annualization assumption.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### bb_width

- **Implementation:** `models/features.py:93`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `BollingerBands._run()` `ta/volatility.py:93-99` uses `self._close.rolling(self._window, min_periods=min_periods).mean()` and `.std(ddof=0)` — value at index t is mean/std of bars [t-19, t]. Bar t contributes to its own band; standard Bollinger convention.
2. Normalization timing: PASS. Evidence: `ta/volatility.py:136` `((hband - lband) / mavg) * 100` — same 20-bar rolling mean used for bands; no global normalization.
3. NaN/missing handling: PASS. Evidence: `min_periods=self._window=20`; first 19 rows NaN. `fillna=False` default; no backfill.
4. Granularity/timezone/resample boundaries: PASS.
5. Indicator library convention: PASS. Evidence: `ta/volatility.py:94` — pandas rolling includes current bar; standard Bollinger convention; no shift needed.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Standard normalized band-width.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### bb_position

- **Implementation:** `models/features.py:94`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `ta/volatility.py:148` `(self._close - self._lband) / (self._hband - self._lband)` — both bands computed from the same 20-bar rolling window ending at t.
2. Normalization timing: PASS. Within-window relative position.
3. NaN/missing handling: PASS. Evidence: first 19 rows NaN; zero-std window guarded by `.where(self._hband != self._lband, np.nan)` at `ta/volatility.py:149`.
4. Granularity/timezone/resample boundaries: PASS.
5. Indicator library convention: PASS. Same `BollingerBands._run()` as bb_width.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Standard Bollinger %B (0 = at lower band, 1 = at upper). Test at `test_models.py:126-132` asserts values in [-0.5, 1.5] (accommodates out-of-band closes).
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action.

#### realized_vol_20

- **Implementation:** `models/features.py:98-100`
- **Audit verdict:** CLEAN
- **Severity:** S1 — Informational (granularity coupling)
- **Portability:** CRYPTO-COUPLED: `ANNUALIZATION_FACTOR=8760` hardcodes 1h/24/7 bars/year

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:98-99` `df["log_returns"].rolling(window=w["realized_vol"]).std()`; `w["realized_vol"] = 20` (`config/_models.py:158`). Standard pandas rolling std; bars [t-19, t]. log_returns[t] = log(close_t / close_{t-1}), past-observable. Including bar t's log return is correct.
2. Normalization timing: PASS. Multiplication by `np.sqrt(ANNUALIZATION_FACTOR)` (8760) is a scaling constant, not a data-derived statistic.
3. NaN/missing handling: PASS. Pandas default `min_periods=20`; first 19 rows NaN. No backfill.
4. Granularity/timezone/resample boundaries: CONCERN (S1). Evidence: `ANNUALIZATION_FACTOR=8760` (`config/_models.py:120`) hardcoded to 1h crypto bars. If granularity ever changes, factor is wrong. Not asserted or derived from the index. `build_feature_matrix()` currently always passes `granularity="1h"`, so the constant is correct in practice. Forward-flag for any future re-granularization.
5. Indicator library convention: N/A — pure pandas rolling std.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS. Target volatility is `log_returns.shift(-1).rolling(horizon).std()` — feature ends at t, target starts at t+1; no overlap.
8. Intent match: PASS. 20-bar realized volatility, annualized. `log_returns.rolling(20).std() * sqrt(8760)`.
9. Asset-class portability: CRYPTO-COUPLED. 8760 bars/year assumes continuous 24/7 trading. Stock data uses market-hours bars (~1,950/year); same formula would overstate annualized vol by ≈2.1× for equities.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** Accepted as-is (S1). `ANNUALIZATION_FACTOR=8760` is documented and crypto-only scope is the Phase 7 invariant. Forward-flag for Phase 8: when stocks re-enter active universe, `ANNUALIZATION_FACTOR` must become per-asset-class.

#### vol_regime

- **Implementation:** `models/features.py:145-149`
- **Audit verdict:** CLEAN (leakage); CONCERN (intent match)
- **Severity:** S2 — Low (intent mismatch only; no leakage)
- **Portability:** CRYPTO-COUPLED: inherits 8760 annualization from realized_vol_20

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:145-149` `df["realized_vol_20"].rolling(60).mean()` — 60-bar trailing mean of already-causal quantity. Window at t covers [t-59, t].
2. Normalization timing: PASS. Ratio `realized_vol_20[t] / mean(realized_vol_20[t-59..t])` — both backward-looking.
3. NaN/missing handling: PASS. Evidence: `features.py:146` `np.where(df["realized_vol_20"].rolling(60).mean() > 0, ..., 1.0)` catches near-zero and NaN denominators (NaN > 0 is False, returns 1.0). Warmup rows have NaN `realized_vol_20` upstream, so they are dropped by `dropna(subset=required)` at `features.py:278`.
4. Granularity/timezone/resample boundaries: PASS. 60-bar window is purely bar-count-relative.
5. Indicator library convention: N/A.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: CONCERN (S2). Evidence: `features.py:144` comment `"Volatility regime: current vol vs 60-period rolling mean (>1 = elevated)"`. Name `vol_regime` implies a categorical regime (elevated/low); implementation returns continuous ratio (e.g., 0.7, 1.4, 2.3). The audit checklist worked example at item 8 explicitly names this as a worked MISMATCH. Continuous ratio is a legitimate regime indicator; the RF/XGBoost models are indifferent to the scaling. Documentation-only concern.
9. Asset-class portability: CRYPTO-COUPLED (inherited from realized_vol_20's 8760 annualization).

**Prior audit acknowledgment:** §13.2 quoted verbatim: "Divides current vol by 60-bar mean; sensitive if `rolling(60).mean()` produces near-zero divisor."
**Verification:** VERIFIED as guarded and safe. `features.py:146` `np.where(... > 0, ..., 1.0)` explicitly catches near-zero (and NaN) divisor and substitutes 1.0. Division by zero cannot produce Inf in production. The §13.2 risk is real in principle but already handled. No remediation needed for this specific concern.

**Remediation:** Open S2 ticket at T6: rename `vol_regime` → `vol_regime_ratio` OR update docstring/comment to explicitly state the output is a continuous ratio, not a categorical label. No correctness fix required. Note: renaming the column breaks FEATURE_COLUMNS order invariant and requires retraining all joblib models — prefer the docstring update.

**Family-level notes**

**bb_upper and bb_lower investigation.** Grep across the codebase (`grep -rn "bb_upper\|bb_lower" --include="*.py"` excluding `.venv` and `models/features.py`) returns **zero results**. The two columns are computed at `features.py:91-92` (`df["bb_upper"] = _bb.bollinger_hband()`, `df["bb_lower"] = _bb.bollinger_lband()`), absent from `FEATURE_COLUMNS`, and consumed nowhere else — not in `backtest/strategies.py`, not in `risk/scorer.py`, not in any dashboard page, not in any test. **Finding: dead intermediates / debugging residue.** The `_bb` object must be instantiated once to call `bollinger_wband()` and `bollinger_pband()`; materializing `bb_upper`/`bb_lower` was almost certainly leftover from prototyping `BollingerBandStrategy`, which actually uses `bb_position` (`backtest/strategies.py:94`). These columns sit in the intermediate DataFrame and are discarded at `features.py:293` (`X = df[FEATURE_COLUMNS].copy()`). Marginal memory overhead per call; no correctness consequence. **S2 hygiene** — open T6 ticket to remove the two assignments. Safe to delete: no consumer anywhere, not a FEATURE_COLUMNS member, no joblib serialization impact.

**Family summary:**

| Feature | Verdict | Severity | Portability |
|---|---|---|---|
| atr_14 | CLEAN | CLEAN | PORTABLE |
| bb_width | CLEAN | CLEAN | PORTABLE |
| bb_position | CLEAN | CLEAN | PORTABLE |
| realized_vol_20 | CLEAN | S1 (granularity annotation only) | CRYPTO-COUPLED |
| vol_regime | CLEAN body / CONCERN intent | S2 | CRYPTO-COUPLED (inherited) |
| bb_upper / bb_lower (non-FEATURE_COLUMNS) | Dead intermediates | S2 hygiene | N/A |

No leakage in this family. Two actionable S2 hygiene items (vol_regime intent docstring, bb_upper/bb_lower dead columns) plus one S1 forward-flag (granularity coupling of `ANNUALIZATION_FACTOR`).

## Family (d) — Volume (4 features)
Subagent assignment: 4 of 6, parallel.

Features:
- volume_ratio (models/features.py:106-110) — uses volume_ma20
  (data/cleaner.py:114, cross-module dependency)
- obv (models/features.py:113-123) — z-scored, not raw
- vwap_ratio (models/features.py:127-134)
- volume_trend (models/features.py:160-166)

Implementation hygiene to surface:
- volume_ma20 is produced in data/cleaner.py:114 and consumed in
  models/features.py:106 without explicit declaration in features.py.
  Audit doc subsection: "implementation hygiene."

Prior audit notes (§13.2): obv, vwap_ratio, and volume_trend are
all flagged as highest-risk.

### Findings (filled by T2 Subagent d)

#### volume_ratio

- **Implementation:** `models/features.py:106-110`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** CRYPTO-COUPLED: dollar-denominated single-venue Coinbase volume; no session-gap semantics

**Checklist results:**

1. Lookback window: PASS. Evidence: `cleaner.py:114` `df["volume"].rolling(window=20, min_periods=1).mean()` — bar t volume is the current bar's own observable value; current-bar inclusion is correct.
2. Normalization timing: N/A. Ratio `volume / volume_ma20`; rolling mean is retrospective.
3. NaN/missing handling: PASS. Evidence: `features.py:106-110` `np.where(df["volume_ma20"] > 0, ..., 1.0)` prevents zero-division. `min_periods=1` in upstream rolling means no leading NaN. Fill with 1.0 (neutral) is correct, not backward-fill.
4. Granularity/timezone/resample boundaries: PASS. 20-bar window is granularity-agnostic.
5. Indicator library convention: N/A — pure pandas.
6. Cross-asset / external dependency: PASS with hygiene note (see family-level notes). `volume_ma20` originates in `data/cleaner.py:114`. Same-asset dependency; not a T3 cross-asset concern.
7. Label leakage / target smoothing: PASS. Past-only ratio.
8. Intent match: PASS. Name matches `current_volume / 20-bar_mean_volume`.
9. Asset-class portability: CRYPTO-COUPLED. Coinbase spot volume; no session boundaries. Equity volumes need session-aware windowing.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action. Portability flag logged for Phase 8.

#### obv

- **Implementation:** `models/features.py:113-123`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity (with S2 hygiene notes on NaN guard completeness and intent-vs-name)
- **Portability:** PORTABLE (cumulative sum is session-agnostic; z-score normalization removes scale)

**Checklist results:**

1. Lookback window: PASS. Evidence: `ta/volume.py:86-87` `obv = np.where(close < close.shift(1), -volume, volume); cumsum()` — decision at bar t uses close[t-1] for sign, adds volume[t]. The 50-bar rolling z-score at `features.py:117-118` uses `_obv_raw.rolling(50).mean()` and `.std()` — trailing window ending at t.
2. Normalization timing: PASS. Rolling z-score on trailing 50-bar window; no full-series statistics.
3. NaN/missing handling: CONCERN (S2). Evidence: `features.py:117-118` calls `.rolling(50).mean()` and `.rolling(50).std()` with **no `min_periods`** — defaults to `window=50`, so first 49 rows yield NaN std/mean. `np.where(_obv_std > 0, ..., 0.0)` at line 119-122 only catches zero std, not NaN std — NaN propagates. Dropped by `dropna` at `features.py:278`. Functionally safe via the backstop; guard is misleadingly incomplete.
4. Granularity/timezone/resample boundaries: PASS.
5. Indicator library convention: PASS. Evidence: `ta/volume.py:86` `np.where(self._close < self._close.shift(1), -self._volume, self._volume)` — `shift(1)` ensures `close[t]` vs `close[t-1]` comparison; matches standard OBV definition.
6. Cross-asset / external dependency: N/A. Own close + volume.
7. Label leakage / target smoothing: PASS. Cumulative sum of past signed volumes, then z-scored over trailing window.
8. Intent match: MISMATCH (S2, accepted). Column is named `obv` but implementation is 50-bar rolling z-score of raw OBV. Comment at `features.py:112` documents this explicitly: `"OBV normalized to z-score — raw OBV is not scale-invariant (Rule 8)"`. Renaming would break FEATURE_COLUMNS order invariant.
9. Asset-class portability: PORTABLE. No 24/7 or dollar-volume assumption.

**Prior audit acknowledgment:** §13.2 quoted verbatim: "50-bar z-score. Safe, but z-score uses past data with no min_periods (so first 50 rows produce NaN and get dropped — OK)."
**Verification:** VERIFIED. `features.py:117-118` confirms no `min_periods` arg; first 49 rows NaN; dropped by `build_feature_matrix` `dropna`. Behavior is as §13.2 describes.

**Remediation:** Two accepted-as-is items:
- S2 (NaN guard completeness): `np.where(_obv_std > 0)` guard at line 119 covers zero only, not NaN. Document that the `dropna` backstop handles NaN, and that adding `min_periods=1` would change z-score semantics for warmup.
- S2 (intent match): Column name vs z-scored implementation. Rationale code-documented at line 112; renaming would break FEATURE_COLUMNS order and require full retrain. Defer to next major model revision (Phase 10).

#### vwap_ratio

- **Implementation:** `models/features.py:127-134`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** CRYPTO-COUPLED: rolling VWAP over 20 bars assumes continuous 24/7 trading; equities use session-reset VWAP

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:127-128` `(df["close"] * df["volume"]).rolling(w["vwap"]).sum()` with `w["vwap"]=20` (`config/_models.py:159`). Standard trailing 20-bar window; includes bar t (observable at bar's close).
2. Normalization timing: PASS. Both numerator and denominator are rolling sums of past+current volume — observable.
3. NaN/missing handling: PASS. Two guards: `np.where(_vwap_den > 0, _vwap_num / _vwap_den, df["close"])` (line 129) and `np.where(_vwap > 0, df["close"] / _vwap, 1.0)` (lines 130-133). Zero-volume windows fall back to `close` (vwap) and `1.0` (ratio). Leading 20-bar warm-up NaN caught by downstream `dropna`.
4. Granularity/timezone/resample boundaries: PASS. Bar-count, not time-boundary based. No session-reset logic (portability flag at item 9).
5. Indicator library convention: N/A — pure pandas. Implementation uses `close * volume` not `(high+low+close)/3 * volume` (typical price) — deliberate simplification; no leakage consequence.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. `close / rolling_vwap_20`; close-weighted simplification is a documented choice, not a naming mismatch.
9. Asset-class portability: CRYPTO-COUPLED. Rolling 20-bar VWAP without session reset assumes continuous trading. Equities use session-reset VWAP by convention; 20-bar rolling spanning overnight would mix sessions.

**Prior audit acknowledgment:** §13.2 quoted verbatim: "20-bar rolling VWAP. Safe."
**Verification:** VERIFIED. `features.py:127-134` confirms 20-bar rolling (`w["vwap"]=20`), all trailing, no future data. Prior finding is accurate.

**Remediation:** CLEAN — no action. Portability flag logged for Phase 8.

#### volume_trend

- **Implementation:** `models/features.py:160-166`
- **Audit verdict:** CLEAN (semantics); CONCERN (config hygiene)
- **Severity:** S2 — Low (magic window literals not in `FEATURE_WINDOWS`)
- **Portability:** CRYPTO-COUPLED: dollar-denominated single-venue volume; no session-gap assumption

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:160-161` `df["volume"].rolling(10).mean()` and `df["volume"].rolling(30).mean()` — both trailing windows ending at t.
2. Normalization timing: N/A. Ratio of two trailing volume MAs.
3. NaN/missing handling: PASS. Evidence: `np.where(vol_ma_30 > 0, vol_ma_10 / vol_ma_30, 1.0)` — zero-divisor falls back to 1.0. Leading 29-bar warmup NaN handled by `dropna`.
4. Granularity/timezone/resample boundaries: PASS. 10/30-bar windows at 1h ≈ 10h/30h, reasonable short/medium volume comparison.
5. Indicator library convention: N/A — pure pandas.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Comment at `features.py:159` `"10/30 volume ratio; >1 = growing participation"` matches implementation.
9. Asset-class portability: CRYPTO-COUPLED. Coinbase spot volume; overnight gaps in equity data would dilute 30-bar MA spuriously.

**Prior audit acknowledgment:** §13.2 quoted verbatim: "10/30 volume ratio. Safe but the magic windows (10, 30) are not in `FEATURE_WINDOWS`."
**Verification:** VERIFIED. `features.py:160-161` hardcodes `10` and `30`. Confirmed by inspection that `config/_models.py:146-161` (`FEATURE_WINDOWS`) has no keys for these. Prior finding accurate.

**Remediation:** Open S2 ticket at T6: add `"vol_trend_short": 10` and `"vol_trend_long": 30` to `FEATURE_WINDOWS`; wire `features.py:160-161` to reference them. Resolve before Phase 7 Step 5 retraining.

**Family-level notes**

**volume_ma20 cross-module dependency.** `volume_ma20` produced in `data/cleaner.py:114` (`df["volume"].rolling(window=20, min_periods=1).mean()`), consumed in `models/features.py:106-110`. Documented in two places (PRECONDITION block in `compute_technical_indicators` docstring `features.py:21-27`; Scope block in this audit doc), but no runtime assertion or import. A reader landing at `features.py:107` cold sees `df["volume_ma20"]` with no apparent provenance. Sole enforcement is the implicit call order in `build_feature_matrix` at `features.py:265-267`. **S2 hygiene.** Recommended T6 ticket: add `assert "volume_ma20" in df.columns, "..."` at the top of `compute_technical_indicators()`.

**FEATURE_WINDOWS registry gap.** `volume_trend` is the only window-bearing feature in the family using bare integer literals (10, 30). Every other window-bearing feature (`vwap`, `obv_norm`) reads `w[key]`. Config-driven experimentation cannot reach these windows. Tracked as the S2 finding under volume_trend above.

**OBV naming convention.** Accepted intentional shorthand documented at `features.py:112`. Renaming requires breaking FEATURE_COLUMNS order — defer to Phase 10.

**vwap_ratio close-vs-typical-price.** Implementation uses `close * volume` rather than canonical `(high+low+close)/3 * volume`. Deliberate simplification, applied uniformly, no leakage consequence. Informational only.

## Family (e) — Price-derived / cleaner-resident (3 features)
Subagent assignment: 5 of 6, parallel.

Features:
- returns (data/cleaner.py:111)
- log_returns (data/cleaner.py:112)
- price_range (data/cleaner.py:113)

Architectural note for the subagent: these features live in
data/cleaner.py rather than models/features.py. Verify the split
is justified (pre-indicator normalization context) and surface
any concerns specific to the cleaner pipeline.

Prior audit notes: §13.2 does NOT flag any feature in this family.

### Findings (filled by T2 Subagent e)

#### returns

- **Implementation:** `data/cleaner.py:111`
- **Audit verdict:** CONCERN
- **Severity:** S2
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `cleaner.py:111` `df["close"].pct_change() * 100` — computes (close[t] − close[t-1]) / close[t-1]; only one prior bar consumed.
2. Normalization timing: PASS. No rolling statistics; uses only close[t] and close[t-1].
3. NaN/missing handling: CONCERN. Evidence: Row 0 produces NaN by definition (correctly dropped downstream). Subtler risk: `clean_ohlcv` forward-fills price NaNs for runs ≤ `MAX_CONSECUTIVE_FILL=3` (`cleaner.py:76-84`). A forward-filled close[t] == close[t-1] produces `returns=0.0` — synthetic zero, not a real trade return. Documented S2 hygiene concern, not a leak.
4. Granularity/timezone/resample boundaries: PASS. Evidence: `cleaner.py:58` `df.sort_values('timestamp').reset_index(drop=True)` — single sorted, tz-normalized frame; one-bar `shift(1)` implicit in `pct_change()`.
5. Indicator library convention: N/A — pure pandas.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS. Evidence: target uses `close.shift(-horizon)` at `features.py:208`; returns references close[t], close[t-1] only.
8. Intent match: PASS. Name = percentage price change one bar; implementation matches.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** Accepted as-is (S2). Forward-fill-induced zero returns are an inherited cleaning artifact (rate-limited to ≤3-bar runs by `MAX_CONSECUTIVE_FILL`), not introduced by `normalize_price_data`. Recommend adding a one-line comment in `normalize_price_data` noting that ffill'd bars produce synthetic zero returns. Documentation hygiene only; no code change.

#### log_returns

- **Implementation:** `data/cleaner.py:112`
- **Audit verdict:** CONCERN
- **Severity:** S3 — Medium
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `cleaner.py:112` `np.log(df['close'] / df['close'].shift(1))` — one prior bar consumed.
2. Normalization timing: PASS. No scaling statistics.
3. NaN/missing handling: CONCERN (S3). Two failure modes neither caught at the computation site:
   - **Log of zero (`close[t]=0` or `close[t-1]=0`):** `np.log(0)` returns `-inf`. pandas treats `inf` as non-NaN by default, so `inf` **survives both** `dropna(subset=required)` at `features.py:278` and the NaN guard `X.isna().sum().sum()` at `features.py:297`. Zero close at any non-row-0 position would inject `-inf` into `X` without triggering any guard.
   - **Forward-fill artifact:** same issue as `returns` — ffill'd identical closes produce `log(1) = 0.0`.
   - `validate_ohlcv` (`cleaner.py:36-38`) checks for non-positive prices but only logs an error and returns `is_valid=False`; `build_feature_matrix` calls `clean_ohlcv` directly and **never invokes `validate_ohlcv`** (confirmed at `features.py:265-266`). Validator is decoupled from the training pipeline.
4. Granularity/timezone/resample boundaries: PASS. Evidence: `cleaner.py:58` — sorted, tz-aware before `normalize_price_data`.
5. Indicator library convention: N/A — pure numpy.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS (with hygiene note). `log_returns` is reused downstream in `compute_targets` to build `target_volatility` at `features.py:202` via `log_returns.shift(-1).rolling(horizon).std()`. The feature value at row t (from `normalize_price_data` using close[t], close[t-1]) and the shifted series used in the target start at row t+1 — no row overlap. Dual-use of the same column is worth documenting but is not leakage.
8. Intent match: PASS. Natural log of price ratio.
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** Open S3 ticket at T6. Fix options:
- (preferred) Add a guard in `normalize_price_data`: `np.where(df["close"].shift(1) > 0, np.log(df["close"] / df["close"].shift(1)), np.nan)`. Local fix; `-inf` never materializes; falls back to NaN which is caught by `dropna`.
- (alternative) Call `validate_ohlcv` inside `build_feature_matrix` and abort on `is_valid=False`. Larger pipeline contract change.

#### price_range

- **Implementation:** `data/cleaner.py:113`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** PORTABLE

**Checklist results:**

1. Lookback window: PASS. Evidence: `cleaner.py:113` `(df['high'] - df['low']) / df['close']` — within-bar arithmetic, all three from same row.
2. Normalization timing: PASS. Division by close[t] is within-bar scaling, not cross-bar.
3. NaN/missing handling: PASS. If close = 0, division produces `inf` (same systemic gap as log_returns, raised under S3 there, not duplicated here). After `clean_ohlcv` + ffill, close is guaranteed positive in practice.
4. Granularity/timezone/resample boundaries: PASS. Same-row inputs.
5. Indicator library convention: N/A.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. Normalized intrabar range (fractional spread).
9. Asset-class portability: PORTABLE.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** CLEAN — no action. Systemic zero-close pipeline gap is already raised at S3 under `log_returns`.

**Family-level notes**

**Architectural rationale for the cleaner/features split.** Partially justified, partially incidental drift. Justified part: `normalize_price_data` runs at pipeline step 3 before `compute_technical_indicators` at step 4 (`features.py:266-267`); the ordering is documented in `build_feature_matrix`'s docstring (`features.py:241-243`). `realized_vol_20` consumes `log_returns` and `volume_ratio` consumes `volume_ma20` — the dependency is load-bearing, not incidental. Incidental part: `returns`, `log_returns`, and `price_range` are not data-cleaning operations — they are feature engineering. Their placement in the cleaner module blurs the "data prep vs. feature engineering" boundary. They are first-class FEATURE_COLUMNS members (positions 0-2 at `config/_models.py:167-169`). The audit may not prescribe a refactor; flag for Phase 8 architecture review.

**Pipeline ordering verification.** Trace from `scripts/train_models.py` → `train_all_models()` → `build_feature_matrix()` (`features.py:225`): the call sequence at `features.py:265-268` is deterministic — `clean_ohlcv` → `normalize_price_data` → `compute_technical_indicators` → `compute_targets`. Cleaner always runs before features.py; not subject to race conditions or import-order issues.

**First-row NaN.** `pct_change()` and `shift(1)` both produce NaN at row 0. Correct behavior; absorbed by downstream `dropna(subset=required)` at `features.py:278`. Indicator warmup (50-bar OBV, 8760-bar yearly_position) dominates the dropped-row count anyway; row-0 NaN poses no independent risk.

**Log-of-zero / log-of-negative systemic gap.** Documented at S3 under `log_returns`. Root cause is the decoupling of `validate_ohlcv` from the training pipeline. `inf` survives both `dropna` and `isna` checks; only NaN is caught. The same gap also affects `price_range` (via division by close) but with lower practical risk because the numerator `high - low ≥ 0` is bounded.

## Family (f) — Calendar / regime-anchor (4 features)
Subagent assignment: 6 of 6, parallel.

Features:
- hour_of_day (models/features.py:138)
- day_of_week (models/features.py:139)
- is_weekend (models/features.py:140) — composed from day_of_week
- yearly_position (models/features.py:168-176)

Prior audit notes (§13.2): yearly_position is flagged as
highest-risk (granularity-coupled to 1h).

### Findings (filled by T2 Subagent f)

**Upstream timestamp handling confirmed.** `data/cleaner.py:55-56` `pd.to_datetime(df["timestamp"], utc=True)` — timestamps normalized to UTC-aware before the feature pipeline runs. `data/storage.py:140` calls `from_unix` which returns `datetime.fromtimestamp(ts, tz=UTC)`. The timestamp that `dt.hour` and `dt.dayofweek` operate on is always UTC.

#### hour_of_day

- **Implementation:** `models/features.py:138`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** CRYPTO-COUPLED: assumes all 24 UTC hours are populated and carry signal

**Checklist results:**

1. Lookback window: PASS. `dt.hour` reads the current bar's own timestamp; no rolling window, no future bar.
2. Normalization timing: PASS. Evidence: `features.py:138` `df["timestamp"].dt.hour.astype(float)` — raw integer 0-23.
3. NaN/missing handling: PASS. `dt.hour` on a UTC-aware timestamp is always defined; no NaN path for a valid timestamp.
4. Granularity/timezone/resample boundaries: PASS. UTC throughout (`cleaner.py:55-56` enforces UTC-aware conversion). `dt.hour` always returns UTC hour, not local session hour.
5. Indicator library convention: N/A — pure pandas `.dt` accessor.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS. Timestamp hour observable at bar open.
8. Intent match: PASS. `dt.hour` returns 0-23 cast to float.
9. Asset-class portability: CRYPTO-COUPLED. yfinance equity bars only populate ~13:30-20:00 UTC during US cash session (`repo_audit.md:236` confirms AAPL only has 13:30-19:30 UTC bars). Out-of-distribution for crypto-trained model applied to equity.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** Accepted as-is for Phase 7 (crypto-only active universe). Open Phase 8 portability ticket: replace with session-relative feature or verify distribution before equity inference.

#### day_of_week

- **Implementation:** `models/features.py:139`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** CRYPTO-COUPLED: assumes all 7 days (0-6) are populated

**Checklist results:**

1. Lookback window: PASS. Same as hour_of_day — current-row timestamp read.
2. Normalization timing: PASS. Evidence: `features.py:139` — raw integer 0-6.
3. NaN/missing handling: PASS.
4. Granularity/timezone/resample boundaries: PASS. UTC convention; day boundary at midnight UTC.
5. Indicator library convention: N/A — pure pandas.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. `dt.dayofweek` returns 0=Monday … 6=Sunday per pandas convention.
9. Asset-class portability: CRYPTO-COUPLED. US equity bars only Mon-Fri (0-4); values 5/6 structurally absent. AAPL ~3,467 rows over 2 years confirms no weekend bars (`repo_audit.md:236`).

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** Accepted as-is for Phase 7. Open Phase 8 portability ticket: drop or replace with trading-day-of-week ordinal for equity universe.

#### is_weekend

- **Implementation:** `models/features.py:140`
- **Audit verdict:** CLEAN
- **Severity:** CLEAN — no severity
- **Portability:** CRYPTO-COUPLED: structural constant zero for equities (zero-variance column)

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:140` `(df["day_of_week"] >= 5).astype(float)` — reads same-row column; no rolling, no future reference.
2. Normalization timing: PASS. Binary 0/1.
3. NaN/missing handling: PASS. `day_of_week` has no NaN path; bool→float produces clean 0.0 or 1.0.
4. Granularity/timezone/resample boundaries: PASS. Inherits UTC day boundary.
5. Indicator library convention: N/A — pure pandas.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS.
8. Intent match: PASS. `day_of_week >= 5` correctly identifies Sat/Sun.
9. Asset-class portability: CRYPTO-COUPLED. For equities, `is_weekend` is identically zero in every bar. Zero-variance constant; adds noise to feature covariance with zero gradient contribution during training. Highest portability risk in this family.

**Prior audit acknowledgment:** N/A — not in §13.2 priority list.

**Remediation:** Accepted as-is for Phase 7 (real signal for 24/7 crypto). Open Phase 8 portability ticket: drop or replace before any stock training.

#### yearly_position

- **Implementation:** `models/features.py:168-176`
- **Audit verdict:** CONCERN
- **Severity:** S1 — Informational (granularity coupling + non-stationarity)
- **Portability:** CRYPTO-COUPLED: 8760-bar window assumes 1h continuous 24/7 data

**Checklist results:**

1. Lookback window: PASS. Evidence: `features.py:169-170` `rolling(8760, min_periods=100)` on `df["close"]` — no shift. At each bar t the window covers [t-8759, t]; standard backward-looking convention.
2. Normalization timing: CONCERN. Rolling min/max drawn from past data (no classical look-ahead). However, the effective normalization range changes structurally as history grows: first 100 bars use a tiny range, bars 101-8760 use an expanding range, bars >8760 see a stable 52-week window. Non-stationarity flagged in §13.2.
3. NaN/missing handling: PASS. Evidence: `min_periods=100` allows computation after 100 bars; `np.where(range_52w > 0, ..., 0.5)` fallback to 0.5 neutral. First 99 rows NaN, dropped by `dropna` at `features.py:278`.
4. Granularity/timezone/resample boundaries: CONCERN (S1). Window literal `8760` hardcoded; implicitly assumes `granularity == "1h"` and 24/7 (8760 = 365 × 24). No guard or assertion in `compute_technical_indicators(df)`. At 1d granularity, 8760 bars = ~24 years. `ANNUALIZATION_FACTOR=8760` exists in config but is not reused here — second magic-literal coupling. The `100` minimum is also magic, not in `FEATURE_WINDOWS`.
5. Indicator library convention: N/A — pure pandas rolling.
6. Cross-asset / external dependency: N/A.
7. Label leakage / target smoothing: PASS. Past-bar max/min only.
8. Intent match: PASS. Comment at `features.py:168` `"Price position in 52-week range (0 = yearly low, 1 = yearly high)"` matches implementation.
9. Asset-class portability: CRYPTO-COUPLED. At equity bar density (~1,700 bars/year per `repo_audit.md:236`), 8760 bars maps to ~5.4 years, not 1 year. Feature silently becomes "5-year position" without error or warning.

**Prior audit acknowledgment:** §13.2 quoted verbatim: "52-week rolling window with `min_periods=100`. Yellow flag for non-stationarity (not pure leakage)."
**Verification:** VERIFIED. Rolling window at `features.py:169-170` confirmed; `min_periods=100` literal confirmed. Non-stationarity is real: denominator `range_52w` is not constant-width for the first 8760 bars of any asset's history. Test fixture comment at `tests/test_models.py:496` explicitly acknowledges the warmup. §13.2 characterization accurate.

**Remediation:** Accepted as-is (S1) with rationale: non-stationarity is mild in practice for the active crypto universe (all active assets have >8760 hours of history per `repo_audit.md:238-256`), so warmup is in the distant past. Granularity-coupling is a Phase 8 concern. Document: "if any new asset is introduced with <8760 hours (~365 days) of history, `yearly_position` is non-stationary across its entire training window." Recommend a forward-flag, not a code change.

**Family-level notes**

All four features in Family (f) are CRYPTO-COUPLED. Phase 8 portability assumptions, named precisely:

1. **24/7 continuous bar population** (affects all four). Crypto produces a bar every hour every day; equities produce ~6.5 hours/day Mon-Fri only.
2. **UTC hour carries intraday signal** (affects `hour_of_day`). Crypto liquidity varies by Asia/Europe/US session handoff; equity bars confined to a narrow UTC window with minimal intra-session variation in the same sense.
3. **Weekend bars exist and carry regime information** (affects `is_weekend`). For equities, the feature is identically zero — zero-variance constant polluting the feature covariance.
4. **8760 bars = 1 calendar year** (affects `yearly_position`). Hardcoded literal at `features.py:169`; `ANNUALIZATION_FACTOR=8760` constant not reused. At equity bar density (~1,700/year), 8760 maps to ~5.4 years.

**Phase 8 remediation direction** (forward-flag, not Phase 7 action). Before any equity asset enters training: (a) drop `is_weekend` for equity models; (b) replace `hour_of_day` with a session-relative feature (minutes-since-open / minutes-until-close); (c) replace `day_of_week` with trading-day ordinal (Mon-Fri → 0-4 for equity, keep 0-6 for crypto); (d) parameterize `yearly_position` window by `BARS_PER_YEAR[granularity][asset_class]` rather than hardcoded 8760.

## Phase 8 portability forward-flags
Aggregated from checklist item 9 across all families. This section
informs Phase 8 stock-integration scope; it is not a Step 2 closure
requirement.

**Counts:** 9 features CRYPTO-COUPLED, 20 features PORTABLE. All
crypto-coupled features are concentrated in Families (c), (d), (f).
Families (a), (b), (e) are 100% portable.

Entries ordered by family, then by feature name within family.

| Feature | Family | Crypto-coupled assumption |
|---|---|---|
| realized_vol_20 | (c) Volatility | `ANNUALIZATION_FACTOR=8760` hardcodes 1h/24/7 bars/year; same formula overstates equity annualized vol by ≈2.1× |
| vol_regime | (c) Volatility | Inherits 8760 annualization assumption from realized_vol_20 |
| obv | (d) Volume | (none — PORTABLE; listed for completeness only — included in z-score family note) |
| volume_ratio | (d) Volume | Dollar-denominated single-venue Coinbase volume; no session-gap semantics |
| volume_trend | (d) Volume | Dollar-denominated single-venue volume; overnight equity gaps would dilute the 30-bar MA spuriously |
| vwap_ratio | (d) Volume | 20-bar rolling VWAP without session reset; equity convention is session-reset VWAP |
| day_of_week | (f) Calendar | Assumes all 7 days populated; equity bars confined to Mon-Fri (0-4); values 5/6 structurally absent |
| hour_of_day | (f) Calendar | Assumes all 24 UTC hours populated and informative; equity bars confined to ~13:30-20:00 UTC |
| is_weekend | (f) Calendar | Identically zero for equities — zero-variance constant polluting feature covariance |
| yearly_position | (f) Calendar | `rolling(8760, min_periods=100)` literal hardcodes 1h continuous bars = 1 year; at equity bar density (~1,700/year) becomes ~5.4 years |

**Note on obv row above:** included as a deliberate `PORTABLE` placeholder to show it was actively evaluated, not omitted. The 50-bar rolling z-score removes the scale dependency; cumulative-sum component is session-agnostic. No action required.

**Phase 8 minimum-viable remediation direction** (aggregated from family-level notes; informational, not Phase 7 work):

1. **Per-asset-class `ANNUALIZATION_FACTOR`.** Replace the single 8760 constant with `{"crypto_1h": 8760, "equity_1h": 1638, ...}` keyed by asset class × granularity. Affects `realized_vol_20`, `vol_regime`.
2. **Session-aware volume and VWAP windows.** For equities, `vwap_ratio` should reset at session open; `volume_ratio` and `volume_trend` should exclude overnight gaps from the rolling window. Affects all of Family (d) except `obv`.
3. **Drop or replace `is_weekend`.** Identically zero for equity universe; must be excluded before any equity-only training.
4. **Replace `hour_of_day` and `day_of_week` with session-relative analogues.** Minutes-since-open / minutes-until-close and trading-day-of-week ordinal respectively.
5. **Parameterize `yearly_position` window.** `BARS_PER_YEAR[granularity][asset_class]` rather than hardcoded 8760.

These do not block Phase 7 closure but should land before any equity asset re-enters the active training universe.

## Cross-asset alignment (T3)

### T3 scope statement

T3 audits the **plumbing only**: how multi-asset data is loaded,
joined, and iterated in the current codebase. Cross-asset feature
scaffolding (e.g., `models/cross_asset.py`) is **deferred to
Phase 10** (portfolio risk + correlation layer) under YAGNI — zero
current `FEATURE_COLUMNS` features are cross-asset, and empty
modules invite premature design and maintenance overhead. T3's job
is to confirm the plumbing is correct so Phase 10 builds on a
sound foundation, and to lock the alignment contract in a
regression test that survives the deferral.

### Current state

Grep across the codebase (`pd.merge`, `pd.concat`, `.join(`,
`reindex`, `ffill`/`bfill` cross-asset) and inspection of every
multi-asset code path:

| Location | Pattern observed | Verdict | Evidence |
|---|---|---|---|
| (codebase-wide) `pd.merge` calls across assets | **None exist** | N/A (no cross-asset joins anywhere) | `grep -rn "pd\.merge"` in `data/`, `models/`, `risk/`, `backtest/`, `scripts/`, `dashboard/` returns zero results outside the venv. |
| `data/gecko_fetcher.py:159` | `pd.concat(all_chunks, ignore_index=True)` | SAFE (single-asset pagination) | "concatenates response chunks for one Solana token's history; not multi-asset." |
| `dashboard/pages/overview.py:127` | `pd.concat([btc, pd.DataFrame([{Buy & Hold BTC row}])])` | SAFE (single-asset cosmetic append) | "appends a synthetic 'Buy & Hold BTC' Sharpe row to an existing BTC-only summary DataFrame; no cross-asset join." |
| `data/storage.py:103-144` `load_candles` | Single-asset SQL: `WHERE asset = ? AND granularity = ?` | SAFE (per-asset isolation by construction) | "single-asset SQL query; returns one asset's DataFrame; cannot accidentally interleave assets." |
| `scripts/risk_report.py:103` `candles_map = {asset: load_candles(...) for asset in ALL_ASSETS}` | Dict-of-DataFrames per asset | SAFE (dict, not joined) | "each asset's candles live in their own dict entry; never merged or reindexed; consumed independently per asset." |
| `scripts/train_models.py:121` training loop | Per-asset iteration over `ALL_ASSETS`; each iteration loads its own data | SAFE — see trainer isolation subsection | "every iteration calls `load_candles(asset, ...)` fresh; no cross-asset DataFrame ever assembled." |
| `risk/scorer.py:352` scoring loop | Per-asset iteration; each call to `compute_risk_score(asset, candles)` is independent | SAFE (with one universe-wide cache caveat, see notes) | "per-asset, per-iteration; only shared state is the universe-wide `_fg_cache` for Fear & Greed (intentional and asset-agnostic)." |
| `data/historical.py:186` fetcher loop | Per-symbol fetch with own router | SAFE | "each symbol fetched into its own DataFrame and upserted to storage independently." |
| `data/cleaner.py:84` `df.loc[fillable, col] = df[col].ffill()` | Forward-fill of price NaN runs ≤3 bars, single-asset | SAFE (intra-asset, bounded) | "`MAX_CONSECUTIVE_FILL=3` bounds the ffill window; runs entirely within one asset's OHLCV; not cross-asset." |

**Headline finding: there is no multi-asset join, merge, reindex,
or forward-fill across assets anywhere in the codebase.** Every
multi-asset loop iterates independent per-asset DataFrames loaded
fresh from storage. The cross-asset alignment surface area is
effectively zero.

### Trainer per-asset isolation

Verified by inspection of `scripts/train_models.py` (entry point),
`models/trainer.py:96-209` (loop body), `models/trend.py:52-140`,
and `models/volatility.py:43-130`:

- **Estimator instances are constructed per asset.** New
  `RandomForestClassifier(**params)` at `models/trend.py:101`; new
  `XGBRegressor(**params)` at `models/volatility.py:87`; new
  `StandardScaler()` at `models/volatility.py:76-77`. No shared
  fit-state between iterations.
- **Random state is config-constant, not mutated.** `random_state=42`
  in both `RF_PARAMS` (`config/_models.py:128`) and `XGB_PARAMS`
  (`config/_models.py:140`) — read each iteration, identical and
  immutable across the loop. No advancing global RNG.
- **MLflow runs are context-managed.** `with mlflow.start_run(...)`
  blocks at `models/trainer.py:135, 171` close cleanly between
  iterations; no run-state leakage.
- **No imports inside the loop.** All module imports are at the top
  of `models/trainer.py`. The lazy imports inside
  `TrendClassifier.predict_proba` (`models/trend.py:160-161`) and
  similar are not on the training path.
- **`MODEL_SAVE_DIR` directory creation is idempotent.**
  `os.makedirs(..., exist_ok=True)` at `models/trainer.py:114`.
- **`build_feature_matrix` builds its own per-asset SQLite cursor
  scope.** Each call at `models/features.py:225` is fully scoped to
  one asset; no cross-asset DataFrame is ever assembled inside it.
- **Per-iteration result dict is fresh.** `asset_result = {}` at
  `models/trainer.py:123`; no accumulation across assets.

Verdict: **SAFE — trainer is genuinely per-asset isolated.** A
failure in asset A cannot leak into asset B's training run.

### Cross-asset alignment contract (forward-looking)

Phase 10 cross-asset features MUST satisfy:

1. **Inner-join on UTC-aware timestamps.** No outer-join with
   forward-fill across assets. Outer-join + ffill synthesizes
   prices for timestamps where one asset was not observable, which
   becomes a future-data leak the moment correlations, ratios, or
   beta features are computed.
2. **Identical granularity across joined assets**, and the join
   MUST assert this rather than silently allow drift. A 1h asset
   joined against a 1d asset must fail loudly, not auto-reconcile.
3. **Survivorship-aware missing-asset handling.** If an asset
   delisted or stopped trading mid-window, the cross-asset feature
   must handle missingness explicitly (drop the affected
   timestamps, mark as NaN, or document the chosen semantics). No
   silent infill. (Cross-references T4 — see survivorship section
   for the broader treatment; T3 locks the alignment-specific
   behavior only.)
4. **Cross-asset feature computation MUST occur after the
   inner-join**, not before. Computing per-asset features and then
   joining the results risks introducing per-asset look-ahead from
   misaligned warmup windows — feature[t] in asset A might depend
   on data at timestamps that asset B has not observed yet.
5. **Source data MUST be canonicalized to UTC-aware timestamps
   AND a consistent bar-end convention at ingestion** (in the
   storage / loader layer, not patched at join time). Crypto and
   equity vendors do not always agree on convention; joining
   sources with different bar-end conventions silently shifts
   alignment by one bar. Today every source funnels through
   `data/storage.py:upsert_candles` which stores Unix epoch
   integers — convention is uniform by construction, but a new
   ingestion path would need to honor the same contract.

### Regression test

`tests/test_cross_asset_alignment.py` — 3 test cases against
pandas primitives (no cross-asset loader exists yet to exercise).
Tests lock the two contract items most likely to be silently
violated by future code:

| Test | Contract item | What it locks |
|---|---|---|
| `test_inner_join_keeps_only_overlapping_timestamps` | item 1 | Inner-join on `timestamp` yields exactly the overlap range; no NaN slips in. |
| `test_outer_join_with_ffill_would_be_unsafe` | item 1 (negative) | Demonstrates the leak pattern the contract forbids — outer-join + ffill fabricates prices outside an asset's observable range. Asserts the forbidden output explicitly so future code can be compared against it. |
| `test_bar_open_vs_bar_close_timestamps_do_not_naively_align` | item 5 | Bar-open vs bar-close timestamps for the same logical bars do not match; naive inner-join produces zero rows. Canonical resolution is ingestion-time, not join-time. |

When the Phase 10 cross-asset loader is built, replace the pandas
`pd.merge(...)` call inside each test with the canonical function
(e.g., `data.cross_asset.align_assets`); the assertions stand
unchanged.

### Phase 10 scaffolding deferral

- **Current FEATURE_COLUMNS contains zero cross-asset features.**
  Confirmed at `config/_models.py:165-197`; every column is
  computed from a single asset's own OHLCV.
- **Cross-asset feature module scaffolding** (e.g.,
  `models/cross_asset.py`, `data/cross_asset_loader.py`) **is
  deferred to Phase 10** when actually needed for portfolio
  correlation and dispersion features.
- **Rationale: YAGNI.** Empty modules invite premature design and
  add maintenance overhead with no current consumer. The
  regression test above guards the contract independent of
  whether the module exists.
- **Phase 8 caveat:** stock integration MAY surface cross-asset
  requirements earlier (e.g., crypto-equity beta, sector
  correlation). If so, the deferral is revisited at Phase 8
  planning. The contract above holds either way.

### Notes

- **One universe-wide cached value exists: `_fg_cache` in
  `risk/scorer.py:29`.** Module-global cache for the Fear & Greed
  index, reset at the top of `score_all_assets()` (lines 337-341).
  This is *intentional* and *not* a cross-asset leakage concern:
  F&G is a single universe-wide reading applied identically to
  every asset. The separately-flagged concern (`docs/repo_audit.md`
  §14.1, third bullet) — that a failed first call poisons the
  cache for the process lifetime — is a Phase 7 robustness issue,
  not a T3 alignment finding.
- **Bar-end convention is uniform today** by virtue of
  `data/storage.py:upsert_candles` storing Unix epoch integers
  and `from_unix` (`utils/time_utils.py:16-17`) returning
  UTC-aware datetimes. Any future ingestion path that bypasses
  `upsert_candles` (e.g., direct DataFrame imports for backtest
  experiments) breaks contract item 5; T6 should track this as a
  forward-flag if such a path is ever introduced.
- **T4 (survivorship) cross-reference.** Contract item 3 names
  survivorship-aware missing-asset handling as part of the
  alignment contract, but the broader survivorship audit
  (universe membership tables, point-in-time asset listings,
  delisting handling) lives in T4. T3 only locks the alignment
  primitive.
- **T5 (backtest fill-time) cross-reference.** The backtest
  engine (`backtest/engine.py`) operates on single-asset candle
  streams; cross-asset fills are not in scope for T5 either.
  The portfolio-level backtest that *would* exercise cross-asset
  alignment does not exist today.
- **T6 candidates from T3:** none mandatory. Contract violations
  surface only when the Phase 10 module is built. The regression
  test makes such violations fail loudly at PR time.

## Survivorship bias (T4)
(empty)

## Backtest engine fill-time (T5)
(empty)

## Triage and remediation (T6)
(empty)
