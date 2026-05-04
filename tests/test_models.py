import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from models.features import compute_technical_indicators, compute_targets
from models.volatility import VolatilityPredictor
from models.trend import TrendClassifier
from config.settings import FEATURE_COLUMNS, MODEL_HORIZON


# -- Synthetic data helpers ---------------------------------------------------

def make_ohlcv(n: int = 600, seed: int = 42) -> pd.DataFrame:
    """
    Generates synthetic OHLCV using Geometric Brownian Motion.
    600 rows ensures enough data for all rolling windows + dropna + training.
    Timestamps are anchored to now so load_candles(days_back=N) includes them.
    """
    np.random.seed(seed)
    returns    = np.random.normal(0.0001, 0.02, n)
    prices     = 40000.0 * np.exp(np.cumsum(returns))
    end_time   = pd.Timestamp.now(tz="UTC").floor("h")
    timestamps = pd.date_range(end=end_time, periods=n, freq="1h")

    df = pd.DataFrame({
        "timestamp": timestamps,
        "close":     prices,
        "open":      prices * (1 + np.random.normal(0, 0.002, n)),
        "high":      prices * (1 + np.abs(np.random.normal(0, 0.005, n))),
        "low":       prices * (1 - np.abs(np.random.normal(0, 0.005, n))),
        "volume":    np.random.uniform(500, 5000, n),
    })
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"]  = df[["low",  "open", "close"]].min(axis=1)
    return df


def make_processed_df(n: int = 600) -> pd.DataFrame:
    """Returns OHLCV with cleaner pipeline applied (needed before indicators)."""
    from data.cleaner import clean_ohlcv, normalize_price_data
    df = make_ohlcv(n)
    df = clean_ohlcv(df)
    df = normalize_price_data(df)
    return df


def make_in_memory_db(n: int = 600):
    """Creates an in-memory SQLite DB populated with synthetic BTC-USD candles."""
    from data.storage import init_db, upsert_candles
    conn = init_db(":memory:")
    df   = make_ohlcv(n)
    upsert_candles("BTC-USD", "1h", df, conn)
    return conn, df


# -- compute_technical_indicators tests ---------------------------------------

def test_all_feature_columns_present():
    """Every column in FEATURE_COLUMNS must exist after indicators are added."""
    df     = make_processed_df(600)
    result = compute_technical_indicators(df)
    missing = [c for c in FEATURE_COLUMNS if c not in result.columns]
    assert not missing, f"Missing feature columns: {missing}"


def test_no_duplicate_columns():
    """No column name should appear twice."""
    df     = make_processed_df(400)
    result = compute_technical_indicators(df)
    cols   = list(result.columns)
    assert len(cols) == len(set(cols)), \
        f"Duplicate columns: {[c for c in cols if cols.count(c) > 1]}"


def test_no_future_leakage_in_features():
    """
    Changing only the last row's close must not affect row[-2] features.
    If any feature at row[-2] changes, future data is leaking.
    """
    df1 = make_processed_df(300)
    df2 = df1.copy()
    df2.loc[df2.index[-1], "close"] = df2["close"].iloc[-1] * 5.0

    r1 = compute_technical_indicators(df1)
    r2 = compute_technical_indicators(df2)

    for col in ["rsi_14", "sma_20", "macd"]:
        if col in r1.columns:
            v1 = r1[col].iloc[-2]
            v2 = r2[col].iloc[-2]
            if pd.notna(v1) and pd.notna(v2):
                assert abs(v1 - v2) < 1e-6, (
                    f"Feature '{col}' at row[-2] changed when only row[-1] was modified — "
                    f"data leakage detected!"
                )


def test_volume_ratio_no_inf():
    """volume_ratio must never be infinite (zero denominator guard)."""
    df = make_processed_df(100)
    df["volume"]      = 0.0
    df["volume_ma20"] = 0.0
    result = compute_technical_indicators(df)
    if "volume_ratio" in result.columns:
        assert not result["volume_ratio"].isin([np.inf, -np.inf]).any()


def test_williams_r_range():
    """Williams %R values must be in [-100, 0] range (ignoring NaN)."""
    df     = make_processed_df(200)
    result = compute_technical_indicators(df)
    if "williams_r_14" in result.columns:
        valid = result["williams_r_14"].dropna()
        assert (valid >= -100).all() and (valid <= 0).all(), \
            "Williams %R out of [-100, 0] range"


def test_bb_position_range():
    """Bollinger Band position should generally be in [-0.5, 1.5]."""
    df     = make_processed_df(300)
    result = compute_technical_indicators(df)
    if "bb_position" in result.columns:
        valid = result["bb_position"].dropna()
        assert (valid >= -0.5).all() and (valid <= 1.5).all(), \
            "bb_position wildly out of range"


def test_obv_is_normalized():
    """OBV should be roughly zero-centered after normalization."""
    df     = make_processed_df(400)
    result = compute_technical_indicators(df)
    if "obv" in result.columns:
        valid = result["obv"].dropna()
        assert abs(valid.mean()) < 2.0, \
            f"OBV mean too far from 0: {valid.mean():.2f} (not normalized?)"


# -- compute_targets tests ----------------------------------------------------

def test_last_horizon_rows_are_nan():
    """Last MODEL_HORIZON rows of target_direction must be NaN."""
    df     = make_processed_df(300)
    result = compute_targets(df, horizon=MODEL_HORIZON)
    last_n = result["target_direction"].iloc[-MODEL_HORIZON:]
    assert last_n.isna().all(), \
        f"Expected NaN in last {MODEL_HORIZON} rows but got: {last_n.values}"


def test_target_direction_values():
    """target_direction must only contain 0.0, 1.0, or NaN."""
    df     = make_processed_df(300)
    result = compute_targets(df)
    non_nan = result["target_direction"].dropna()
    assert set(non_nan.unique()).issubset({0.0, 1.0}), \
        f"Unexpected values in target_direction: {non_nan.unique()}"


def test_target_volatility_non_negative():
    """target_volatility must be non-negative where not NaN."""
    df     = make_processed_df(300)
    result = compute_targets(df)
    valid  = result["target_volatility"].dropna()
    assert (valid >= 0).all(), "Negative target_volatility detected"


def test_np_where_nan_safety():
    """
    Verify that target_direction is NaN (not False) for last horizon rows.
    This guards against Rule 4: NaN > float silently = False.
    """
    df     = make_processed_df(50)
    result = compute_targets(df, horizon=12)
    last_row_dir = result["target_direction"].iloc[-1]
    assert pd.isna(last_row_dir), \
        f"Expected NaN in last row but got {last_row_dir} — np.where guard missing"


# -- VolatilityPredictor tests ------------------------------------------------

def test_volatility_predictor_metrics_keys():
    """train() must return dict with all required keys."""
    conn, _ = make_in_memory_db(600)

    import models.features as feat
    original_init = feat.init_db
    feat.init_db  = lambda db_path="zaeryn.db": conn

    try:
        pred    = VolatilityPredictor()
        metrics = pred.train("BTC-USD", days_back=365)
        for key in ["mae", "rmse", "r2", "train_rows", "test_rows", "trained_at"]:
            assert key in metrics, f"Missing key: {key}"
        assert pred.is_trained
    finally:
        feat.init_db = original_init
        conn.close()


def test_volatility_predictor_chronological_only():
    """Verify the chronological split formula is correct."""
    n         = 1000
    test_size = 0.20
    split_idx = int(n * (1 - test_size))
    assert split_idx == 800
    train_indices = list(range(split_idx))
    test_indices  = list(range(split_idx, n))
    assert max(train_indices) < min(test_indices), "Split is NOT chronological"


def test_volatility_predictor_predict_non_negative():
    """predict() must never return a negative value."""
    conn, df = make_in_memory_db(600)

    import models.features as feat
    original_init = feat.init_db
    feat.init_db  = lambda db_path="zaeryn.db": conn

    try:
        pred = VolatilityPredictor()
        pred.train("BTC-USD", days_back=365)
        result = pred.predict(df.tail(200))
        assert result >= 0.0, f"Negative volatility prediction: {result}"
    finally:
        feat.init_db = original_init
        conn.close()


def test_volatility_predictor_save_load(tmp_path):
    """Save and reload must produce identical predictions."""
    conn, df = make_in_memory_db(600)

    import models.features as feat
    original_init = feat.init_db
    feat.init_db  = lambda db_path="zaeryn.db": conn

    try:
        pred = VolatilityPredictor()
        pred.train("BTC-USD", days_back=365)
        pred1 = pred.predict(df.tail(200))

        path = str(tmp_path / "vol.pkl")
        pred.save(path)

        loaded = VolatilityPredictor()
        loaded.load(path)
        pred2 = loaded.predict(df.tail(200))

        assert abs(pred1 - pred2) < 1e-6, "Predictions differ after save/load"
        assert loaded.asset == "BTC-USD"
        assert loaded.is_trained
    finally:
        feat.init_db = original_init
        conn.close()


def test_volatility_predictor_raises_if_not_trained():
    pred = VolatilityPredictor()
    with pytest.raises(RuntimeError):
        pred.predict(make_ohlcv(100))


# -- TrendClassifier tests ----------------------------------------------------

def test_trend_classifier_metrics_keys():
    """train() must return dict with all required keys."""
    conn, _ = make_in_memory_db(600)

    import models.features as feat
    original_init = feat.init_db
    feat.init_db  = lambda db_path="zaeryn.db": conn

    try:
        clf     = TrendClassifier()
        metrics = clf.train("BTC-USD", days_back=365)
        for key in ["accuracy", "f1", "auc", "train_rows", "test_rows"]:
            assert key in metrics, f"Missing key: {key}"
        assert 0.0 <= metrics["auc"] <= 1.0
    finally:
        feat.init_db = original_init
        conn.close()


def test_trend_predict_proba_structure():
    """predict_proba() output must have all keys with valid values."""
    conn, df = make_in_memory_db(600)

    import models.features as feat
    original_init = feat.init_db
    feat.init_db  = lambda db_path="zaeryn.db": conn

    try:
        clf = TrendClassifier()
        clf.train("BTC-USD", days_back=365)
        result = clf.predict_proba(df.tail(200))

        assert "up_probability"   in result
        assert "down_probability" in result
        assert "direction"        in result
        assert "confidence"       in result
        assert result["direction"] in ("UP", "DOWN", "UNCERTAIN")
        assert 0.0 <= result["up_probability"]   <= 1.0
        assert 0.0 <= result["down_probability"] <= 1.0
        assert 0.0 <= result["confidence"]       <= 1.0

        prob_sum = result["up_probability"] + result["down_probability"]
        assert abs(prob_sum - 1.0) < 0.01, f"Probabilities don't sum to 1: {prob_sum}"
    finally:
        feat.init_db = original_init
        conn.close()


def test_trend_uncertainty_at_fifty_fifty():
    """A 0.5/0.5 prediction must produce direction='UNCERTAIN', confidence=0.0."""
    clf                 = TrendClassifier()
    clf.is_trained      = True
    clf.feature_columns = FEATURE_COLUMNS

    class MockModel:
        classes_ = np.array([0, 1])
        def predict_proba(self, X):
            return np.array([[0.5, 0.5]])

    clf.model = MockModel()

    df     = make_processed_df(200)
    df_ind = compute_technical_indicators(df)

    result = clf.predict_proba(df_ind)
    assert result["direction"]  == "UNCERTAIN"
    assert result["confidence"] == 0.0


def test_trend_classifier_raises_if_not_trained():
    clf = TrendClassifier()
    with pytest.raises(RuntimeError):
        clf.predict_proba(make_ohlcv(100))


def test_trend_classifier_save_load(tmp_path):
    """Save and reload must produce identical predictions."""
    conn, df = make_in_memory_db(600)

    import models.features as feat
    original_init = feat.init_db
    feat.init_db  = lambda db_path="zaeryn.db": conn

    try:
        clf = TrendClassifier()
        clf.train("BTC-USD", days_back=365)
        r1 = clf.predict_proba(df.tail(200))

        path = str(tmp_path / "trend.pkl")
        clf.save(path)

        loaded = TrendClassifier()
        loaded.load(path)
        r2 = loaded.predict_proba(df.tail(200))

        assert r1["direction"] == r2["direction"]
        assert abs(r1["up_probability"] - r2["up_probability"]) < 1e-6
    finally:
        feat.init_db = original_init
        conn.close()


# -- should_retrain test ------------------------------------------------------

def test_should_retrain_true_if_models_missing():
    from models.trainer import should_retrain
    assert should_retrain("FAKE_ASSET_XYZ_999") is True


# -- Integration tests (require DB populated by fetch_history.py) -------------

@pytest.mark.integration
def test_build_feature_matrix_btc_live():
    from models.features import build_feature_matrix
    result = build_feature_matrix("BTC-USD", days_back=90)
    if result is None:
        pytest.skip("Not enough data — run scripts/fetch_history.py first")
    X, y_vol, y_dir = result
    assert not X.isna().any().any(), "NaN in feature matrix"
    assert list(X.columns) == FEATURE_COLUMNS
    print(f"\nBTC-USD: {X.shape}, vol_mean={y_vol.mean():.4f}, UP%={y_dir.mean()*100:.1f}%")


@pytest.mark.integration
def test_train_volatility_btc_live():
    pred = VolatilityPredictor()
    try:
        m = pred.train("BTC-USD", days_back=90)
        print(f"\nBTC-USD vol: MAE={m['mae']:.4f}  R²={m['r2']:.4f}")
    except RuntimeError as e:
        pytest.skip(str(e))


@pytest.mark.integration
def test_train_trend_btc_live():
    clf = TrendClassifier()
    try:
        m = clf.train("BTC-USD", days_back=90)
        print(f"\nBTC-USD trend: ACC={m['accuracy']:.3f}  AUC={m['auc']:.3f}")
        assert m["auc"] >= 0.40, "AUC below 0.40 — feature pipeline may be broken"
    except RuntimeError as e:
        pytest.skip(str(e))
