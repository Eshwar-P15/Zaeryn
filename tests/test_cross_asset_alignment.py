"""
Cross-asset alignment contract tests — Phase 7 Step 2 Ticket 3.

Locks the contract that ZAERYN's future cross-asset feature module
(deferred to Phase 10 per docs/data_integrity_audit.md §T3) must
honor. There is currently NO cross-asset loader in the codebase
(confirmed by the T3 audit: no `pd.merge` anywhere across assets,
all per-asset isolation). These tests assert the contract against
pandas primitives directly. When the Phase 10 cross-asset loader is
built, replace the `pd.merge(...)` call inside each test with the
canonical function (e.g., `data.cross_asset.align_assets`) and the
assertions stand unchanged.

Contract items locked here (see audit doc for full list):
  1. Inner-join on UTC-aware timestamps — no outer-join + ffill.
  5. Source data canonicalized at ingestion to a consistent
     bar-end convention; not patched at join time.
"""

import pandas as pd


def _make_ohlcv(timestamps, prices: list[float]) -> pd.DataFrame:
    """Minimal single-asset OHLCV frame for join testing."""
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": [1000.0] * len(prices),
        }
    )


# ════════════════════════════════════════════════════════════════════════════
# Contract item 1 — Inner-join semantics
# ════════════════════════════════════════════════════════════════════════════
#
# Future cross-asset features (correlations, betas, dispersion ranks) MUST
# inner-join on observable UTC timestamps. Outer-join + forward-fill
# synthesizes prices for timestamps where one asset was not observable,
# which becomes a future-data leak the moment a correlation or ratio is
# computed.


def test_inner_join_keeps_only_overlapping_timestamps():
    """
    Contract item 1: cross-asset joins MUST be inner-join on timestamp.

    X has timestamps [t0, t1, t2, t3]; Y has [t1, t2, t3, t4]. The only
    timestamps observable in BOTH assets are [t1, t2, t3] — exactly three
    rows. The correct join surfaces these three and no others.
    """
    t = pd.to_datetime(
        [
            "2025-01-01T00:00:00Z",
            "2025-01-01T01:00:00Z",
            "2025-01-01T02:00:00Z",
            "2025-01-01T03:00:00Z",
            "2025-01-01T04:00:00Z",
        ],
        utc=True,
    )

    X = _make_ohlcv(t[:4], [100.0, 101.0, 102.0, 103.0])  # bars at t0..t3
    Y = _make_ohlcv(t[1:], [200.0, 201.0, 202.0, 203.0])  # bars at t1..t4

    # The Phase 10 loader will eventually wrap this — see comment in module
    # docstring. The contract is what is asserted, not the call shape.
    joined = pd.merge(X, Y, on="timestamp", how="inner", suffixes=("_x", "_y"))

    assert len(joined) == 3, f"inner-join overlap must be 3 rows, got {len(joined)}"
    assert list(joined["timestamp"]) == list(t[1:4]), "overlap must be exactly [t1, t2, t3]"

    # No NaN — every joined row has both assets observable at that timestamp.
    assert not joined.isna().any().any(), "inner-join must not introduce NaN"


def test_outer_join_with_ffill_would_be_unsafe():
    """
    Contract item 1 (negative form): outer-join + forward-fill is the
    WRONG pattern. This test pins the leak shape we are guarding against;
    if a future cross-asset loader ever produced this output, that loader
    is broken.

    The unsafe path produces 5 rows (the full union). At t4, asset X is
    forward-filled from t3 — the model now sees a synthesized close_x
    for a timestamp when X was not observable. Any correlation or ratio
    computed using that row leaks future-shaped information.
    """
    t = pd.to_datetime(
        [
            "2025-01-01T00:00:00Z",
            "2025-01-01T01:00:00Z",
            "2025-01-01T02:00:00Z",
            "2025-01-01T03:00:00Z",
            "2025-01-01T04:00:00Z",
        ],
        utc=True,
    )

    X = _make_ohlcv(t[:4], [100.0, 101.0, 102.0, 103.0])
    Y = _make_ohlcv(t[1:], [200.0, 201.0, 202.0, 203.0])

    unsafe = (
        pd.merge(X, Y, on="timestamp", how="outer", suffixes=("_x", "_y"))
        .sort_values("timestamp")
        .ffill()
    )

    # Full union — 5 timestamps in the result.
    assert len(unsafe) == 5

    # At t4, X's close has been forward-filled from t3 (103.0). This is the
    # leak: X was not observable at t4, but the row reports it was at 103.0.
    t4_row = unsafe[unsafe["timestamp"] == t[4]].iloc[0]
    assert t4_row["close_x"] == 103.0, (
        "outer-join + ffill is expected to forward-fill X's close at t4 from "
        "the t3 value (103.0). The Phase 10 cross-asset loader must NEVER "
        "emit a row shaped like this."
    )


# ════════════════════════════════════════════════════════════════════════════
# Contract item 5 — Bar-end convention consistency
# ════════════════════════════════════════════════════════════════════════════
#
# Source data MUST be canonicalized to a consistent bar-end convention at
# ingestion. Joining sources with different conventions silently shifts
# alignment by one bar. This test pins the failure mode.


def test_bar_open_vs_bar_close_timestamps_do_not_naively_align():
    """
    Contract item 5: bar-open vs bar-close timestamps for the same logical
    bars do not match under naive inner-join. The canonical resolution is
    canonicalization at ingestion, not patching at join time.

    Construction:
      Logical bars 1-4 each cover one hour starting at 00:00, 01:00, 02:00,
      03:00.
      - X uses bar-open convention: timestamp = bar start.
      - Y uses end-of-bar convention with a sub-second offset (timestamp =
        last nanosecond of the bar, which is how some vendors emit
        "last trade in bar" timestamps).
    Naive inner-join finds zero overlap because no X timestamp equals any
    Y timestamp. The fix is to floor Y to its bar-open equivalent at
    ingestion — once canonicalized, all four bars align.
    """
    bar_opens = pd.to_datetime(
        [
            "2025-01-01T00:00:00Z",
            "2025-01-01T01:00:00Z",
            "2025-01-01T02:00:00Z",
            "2025-01-01T03:00:00Z",
        ],
        utc=True,
    )
    # Y stamps bars with the last nanosecond of the bar — same logical bars
    # as X, but the timestamps never collide with bar-open timestamps.
    bar_close_ns = bar_opens + pd.Timedelta(hours=1) - pd.Timedelta(nanoseconds=1)

    X = _make_ohlcv(bar_opens, [100.0, 101.0, 102.0, 103.0])
    Y = _make_ohlcv(bar_close_ns, [200.0, 201.0, 202.0, 203.0])

    naive = pd.merge(X, Y, on="timestamp", how="inner", suffixes=("_x", "_y"))
    assert len(naive) == 0, (
        "Bar-open and bar-close-nanosecond timestamps must not naively "
        "intersect — if this assertion ever fails, the test fixture has "
        "drifted, not the contract."
    )

    # Canonical resolution: floor Y's timestamps to bar-open at ingestion.
    # Once canonicalized, the join recovers all four bars exactly.
    Y_canonical = Y.copy()
    Y_canonical["timestamp"] = Y_canonical["timestamp"].dt.floor("1h")
    canonical_join = pd.merge(X, Y_canonical, on="timestamp", how="inner", suffixes=("_x", "_y"))
    assert len(canonical_join) == 4, (
        "After ingestion-time canonicalization, all four bars align. "
        "The Phase 10 cross-asset loader must canonicalize at ingestion, "
        "not patch at join time."
    )
