# ZAERYN Data Integrity Audit

Phase 7 Step 2 deliverable. Hunts semantic leaks the structural
145-case leakage sweep (tests/test_models.py) cannot detect.
Cross-asset alignment (T3), survivorship bias (T4), and backtest
fill-time (T5) findings live in their own sections.

## Status
| Ticket | Owner | Status |
|---|---|---|
| T1 (this doc + scaffold) | main agent | DONE |
| T2 (per-family audit, 6 subagents) | parallel subagents | PENDING |
| T3 (cross-asset alignment) | TBD | PENDING |
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
(empty)

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
(empty)

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
(empty)

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
(empty)

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
(empty)

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
(empty)

## Phase 8 portability forward-flags
Aggregated from checklist item 9 across all families. This section
informs Phase 8 stock-integration scope; it is not a Step 2 closure
requirement.

(filled by T2)

## Cross-asset alignment (T3)
(empty)

## Survivorship bias (T4)
(empty)

## Backtest engine fill-time (T5)
(empty)

## Triage and remediation (T6)
(empty)
