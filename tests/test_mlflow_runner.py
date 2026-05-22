"""Tests for utils/mlflow_runner.py and the trainer's MLflow wiring."""

from __future__ import annotations

import re
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import pytest

from utils.mlflow_runner import (
    compute_dataset_hash,
    get_git_sha,
    get_library_versions,
    init_mlflow,
)


@pytest.fixture(autouse=True)
def _restore_mlflow_state():
    """Restore MLflow global tracking state after each test."""
    original_uri = mlflow.get_tracking_uri()
    original_exp = mlflow.active_run()
    yield
    if original_exp is None and mlflow.active_run() is not None:
        mlflow.end_run()
    mlflow.set_tracking_uri(original_uri)


# -- init_mlflow ---------------------------------------------------------------


def test_init_mlflow_creates_experiment(tmp_path, monkeypatch):
    """Experiment is created and tracking URI is rooted at PROJECT_ROOT/mlruns."""
    monkeypatch.setattr("utils.mlflow_runner.PROJECT_ROOT", tmp_path)

    init_mlflow("test_exp_creates")

    expected_uri = (tmp_path / "mlruns").resolve().as_uri()
    assert mlflow.get_tracking_uri() == expected_uri

    exp = mlflow.get_experiment_by_name("test_exp_creates")
    assert exp is not None
    assert exp.name == "test_exp_creates"


def test_init_mlflow_is_idempotent(tmp_path, monkeypatch):
    """Repeated init calls do not duplicate the experiment."""
    monkeypatch.setattr("utils.mlflow_runner.PROJECT_ROOT", tmp_path)

    init_mlflow("test_exp_idempotent")
    first = mlflow.get_experiment_by_name("test_exp_idempotent")

    init_mlflow("test_exp_idempotent")
    second = mlflow.get_experiment_by_name("test_exp_idempotent")

    assert first.experiment_id == second.experiment_id


# -- compute_dataset_hash ------------------------------------------------------


def test_compute_dataset_hash_deterministic():
    """Identical DataFrames produce identical hashes."""
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    df_again = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})

    h1 = compute_dataset_hash(df)
    h2 = compute_dataset_hash(df_again)

    assert h1 == h2
    assert len(h1) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", h1)


def test_compute_dataset_hash_changes_on_modification():
    """Hash differs when row values change AND when column order changes."""
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    df_modified = df.copy()
    df_modified.loc[0, "a"] = 99.0

    df_reordered = df[["b", "a"]]

    assert compute_dataset_hash(df) != compute_dataset_hash(df_modified)
    assert compute_dataset_hash(df) != compute_dataset_hash(df_reordered)


# -- get_git_sha ---------------------------------------------------------------


def test_get_git_sha_returns_string():
    """Returns a 40-char hex SHA or the 'no-git' sentinel."""
    sha = get_git_sha()
    assert isinstance(sha, str)
    assert sha == "no-git" or re.fullmatch(r"[0-9a-f]{40}", sha)


# -- get_library_versions ------------------------------------------------------


def test_get_library_versions_returns_known_libs():
    """Dict contains all tracked libraries with non-empty version strings."""
    versions = get_library_versions()

    # pandas/numpy/scikit-learn/xgboost/mlflow are all hard runtime deps.
    for lib in ("pandas", "numpy", "scikit-learn", "xgboost", "mlflow"):
        assert lib in versions, f"missing version for {lib}"
        assert isinstance(versions[lib], str)
        assert versions[lib] not in ("", "not-installed")


# -- train_all_models integration ----------------------------------------------


@pytest.mark.integration
def test_train_all_models_creates_mlflow_run(tmp_path, monkeypatch):
    """Mocked training run should produce an MLflow run with expected params + metrics."""
    from config.settings import FEATURE_COLUMNS
    from models import trainer as trainer_mod

    monkeypatch.setattr("utils.mlflow_runner.PROJECT_ROOT", tmp_path)
    init_mlflow("test_train_runs")

    n = 100
    fake_X = pd.DataFrame({c: np.linspace(0.0, 1.0, n) for c in FEATURE_COLUMNS})
    fake_y_vol = pd.Series(np.linspace(0.1, 0.9, n))
    fake_y_dir = pd.Series(np.zeros(n, dtype=int))

    monkeypatch.setattr(
        trainer_mod,
        "build_feature_matrix",
        lambda asset, horizon, days_back: (fake_X, fake_y_vol, fake_y_dir),
    )

    vol_metrics = {
        "asset": "FAKE-ASSET",
        "model": "VolatilityPredictor",
        "train_rows": 80,
        "test_rows": 20,
        "mae": 0.05,
        "rmse": 0.07,
        "r2": 0.85,
        "mape": 10.0,
        "top_features": [],
        "trained_at": "2026-01-01T00:00:00+00:00",
    }
    trend_metrics = {
        "asset": "FAKE-ASSET",
        "model": "TrendClassifier",
        "train_rows": 80,
        "test_rows": 20,
        "accuracy": 0.6,
        "precision": 0.55,
        "recall": 0.62,
        "f1": 0.58,
        "auc": 0.65,
        "log_loss": 0.7,
        "train_up_pct": 50.0,
        "top_features": [],
        "trained_at": "2026-01-01T00:00:00+00:00",
    }

    class FakeVolPredictor:
        def __init__(self, horizon: int = 1):
            self.horizon = horizon

        def train(self, asset, days_back=180):
            return vol_metrics

        def save(self, path):
            Path(path).write_bytes(b"fake-vol-bytes")
            return path

        @staticmethod
        def model_path(asset, horizon=1):
            return str(tmp_path / f"vol_{asset.replace('-', '_')}_{horizon}h.pkl")

    class FakeTrendClassifier:
        def __init__(self, horizon: int = 1):
            self.horizon = horizon

        def train(self, asset, days_back=180):
            return trend_metrics

        def save(self, path):
            Path(path).write_bytes(b"fake-trend-bytes")
            return path

        @staticmethod
        def model_path(asset, horizon=1):
            return str(tmp_path / f"trend_{asset.replace('-', '_')}_{horizon}h.pkl")

    monkeypatch.setattr(trainer_mod, "VolatilityPredictor", FakeVolPredictor)
    monkeypatch.setattr(trainer_mod, "TrendClassifier", FakeTrendClassifier)
    monkeypatch.setattr(trainer_mod, "MODEL_SAVE_DIR", str(tmp_path))

    trainer_mod.train_all_models(assets=["FAKE-ASSET"], horizon=1, days_back=60, force_retrain=True)

    exp = mlflow.get_experiment_by_name("test_train_runs")
    assert exp is not None

    runs = mlflow.search_runs(experiment_ids=[exp.experiment_id])
    # One asset × (volatility + trend) = 2 runs
    assert len(runs) == 2

    model_types = set(runs["params.model_type"].tolist())
    assert model_types == {"XGB", "RF"}

    assert (runs["params.asset"] == "FAKE-ASSET").all()
    assert (runs["params.horizon"] == "1").all()
    assert "params.dataset_hash" in runs.columns
    assert "params.git_sha" in runs.columns
    assert "params.lib_mlflow" in runs.columns

    # One run should carry MAE (volatility), the other accuracy (trend).
    assert runs["metrics.mae"].notna().sum() == 1
    assert runs["metrics.accuracy"].notna().sum() == 1
