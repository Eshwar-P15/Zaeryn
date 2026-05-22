"""MLflow tracking helpers used by the training pipeline.

All training runs route through ``init_mlflow`` so the tracking URI and
experiment are pinned to the project root. The other helpers exist to give
each run enough provenance (git SHA, library versions, dataset hash) to be
reproduced from a run ID alone.
"""

from __future__ import annotations

import hashlib
import subprocess
from importlib.metadata import PackageNotFoundError, version

import mlflow
import pandas as pd

from config._models import PROJECT_ROOT
from utils.logger import get_logger

logger = get_logger(__name__)


DEFAULT_EXPERIMENT = "zaeryn_training"
_TRACKED_LIBRARIES = ("pandas", "numpy", "scikit-learn", "xgboost", "mlflow")


def _tracking_uri() -> str:
    return (PROJECT_ROOT / "mlruns").resolve().as_uri()


def init_mlflow(experiment_name: str = DEFAULT_EXPERIMENT) -> None:
    """Pin MLflow to the project-local ``mlruns/`` store and select an experiment.

    Idempotent: safe to call multiple times in the same process.
    """
    uri = _tracking_uri()
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(experiment_name)
    logger.info(f"MLflow initialized: experiment={experiment_name!r} uri={uri}")


def compute_dataset_hash(df: pd.DataFrame) -> str:
    """Deterministic 16-char SHA256 hash of a DataFrame's contents.

    Uses ``pandas.util.hash_pandas_object`` so column order and row order both
    contribute to the hash — two DataFrames with the same values but different
    column ordering will hash differently, which is what we want for ML
    reproducibility.
    """
    row_hashes = pd.util.hash_pandas_object(df, index=True).values
    digest = hashlib.sha256(row_hashes.tobytes())
    # Mix in the column names so column reordering changes the hash.
    digest.update("|".join(map(str, df.columns)).encode("utf-8"))
    return digest.hexdigest()[:16]


def get_git_sha() -> str:
    """Return the current HEAD SHA, or ``"no-git"`` if unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "no-git"
    if out.returncode != 0:
        return "no-git"
    sha = out.stdout.strip()
    return sha or "no-git"


def get_library_versions() -> dict[str, str]:
    """Return installed versions for the libraries that matter for reproducibility."""
    versions: dict[str, str] = {}
    for name in _TRACKED_LIBRARIES:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = "not-installed"
    return versions
