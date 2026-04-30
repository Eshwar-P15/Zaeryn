import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional

from config.settings import DB_PATH
from utils.logger import get_logger
from utils.time_utils import to_unix, from_unix, now_utc

logger = get_logger(__name__)

CREATE_CANDLES_TABLE = """
CREATE TABLE IF NOT EXISTS candles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset       TEXT    NOT NULL,
    granularity TEXT    NOT NULL,
    timestamp   INTEGER NOT NULL,
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      REAL    NOT NULL,
    is_anomaly  INTEGER DEFAULT 0,
    UNIQUE(asset, granularity, timestamp)
);
"""

CREATE_PRICE_SNAPSHOTS_TABLE = """
CREATE TABLE IF NOT EXISTS price_snapshots (
    asset      TEXT    PRIMARY KEY,
    price      REAL    NOT NULL,
    updated_at INTEGER NOT NULL
);
"""

CREATE_CANDLES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_candles_asset_time
    ON candles (asset, granularity, timestamp);
"""


def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
    cursor.execute(CREATE_CANDLES_TABLE)
    cursor.execute(CREATE_PRICE_SNAPSHOTS_TABLE)
    cursor.execute(CREATE_CANDLES_INDEX)
    conn.commit()

    logger.debug(f"Database initialized: {db_path}")
    return conn


def upsert_candles(
    asset: str,
    granularity: str,
    df: pd.DataFrame,
    conn: sqlite3.Connection,
) -> int:
    if df.empty:
        logger.debug(f"upsert_candles: empty DataFrame for {asset}, nothing written")
        return 0

    rows = []
    for _, row in df.iterrows():
        ts = row["timestamp"]
        if isinstance(ts, (datetime, pd.Timestamp)):
            ts_unix = to_unix(ts)
        else:
            ts_unix = int(ts)

        is_anomaly = int(row.get("is_anomaly", 0)) if "is_anomaly" in df.columns else 0

        rows.append((
            asset,
            granularity,
            ts_unix,
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
            is_anomaly,
        ))

    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT OR REPLACE INTO candles
            (asset, granularity, timestamp, open, high, low, close, volume, is_anomaly)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()

    logger.debug(f"upsert_candles: wrote {len(rows)} rows for {asset} ({granularity})")
    return len(rows)


def load_candles(
    asset: str,
    granularity: str,
    days_back: int = 30,
    conn: Optional[sqlite3.Connection] = None,
) -> pd.DataFrame:
    close_conn = False
    if conn is None:
        conn = init_db()
        close_conn = True

    cutoff_ts = to_unix(now_utc() - timedelta(days=days_back))

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT timestamp, open, high, low, close, volume, is_anomaly
        FROM candles
        WHERE asset = ? AND granularity = ? AND timestamp >= ?
        ORDER BY timestamp ASC
        """,
        (asset, granularity, cutoff_ts),
    )
    rows = cursor.fetchall()

    if close_conn:
        conn.close()

    if not rows:
        logger.debug(f"load_candles: no data found for {asset} ({granularity}, {days_back}d)")
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "is_anomaly"])

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "is_anomaly"])
    df["timestamp"] = df["timestamp"].apply(from_unix)
    df["is_anomaly"] = df["is_anomaly"].astype(bool)

    logger.debug(f"load_candles: loaded {len(df)} rows for {asset} ({granularity})")
    return df


def upsert_price_snapshot(
    asset: str,
    price: float,
    conn: sqlite3.Connection,
) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO price_snapshots (asset, price, updated_at)
        VALUES (?, ?, ?)
        """,
        (asset, price, to_unix(now_utc())),
    )
    conn.commit()


def load_price_snapshots(conn: sqlite3.Connection) -> dict[str, float]:
    cursor = conn.cursor()
    cursor.execute("SELECT asset, price FROM price_snapshots")
    rows = cursor.fetchall()
    return {row["asset"]: row["price"] for row in rows}


def get_db_stats(conn: sqlite3.Connection) -> dict:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            asset,
            granularity,
            COUNT(*) as count,
            MIN(timestamp) as oldest_ts,
            MAX(timestamp) as newest_ts
        FROM candles
        GROUP BY asset, granularity
        ORDER BY asset, granularity
        """
    )
    rows = cursor.fetchall()

    stats = {}
    for row in rows:
        asset = row["asset"]
        gran = row["granularity"]
        if asset not in stats:
            stats[asset] = {}
        stats[asset][gran] = {
            "count": row["count"],
            "oldest": from_unix(row["oldest_ts"]).strftime("%Y-%m-%d %H:%M"),
            "newest": from_unix(row["newest_ts"]).strftime("%Y-%m-%d %H:%M"),
        }

    return stats
