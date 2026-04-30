from datetime import datetime, timezone, timedelta
from config.settings import COINBASE_MAX_CANDLES_PER_REQUEST, GRANULARITIES


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_unix(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def from_unix(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def date_range(days_back: int) -> tuple[datetime, datetime]:
    end = now_utc()
    start = end - timedelta(days=days_back)
    return start, end


def chunk_date_range(
    start: datetime,
    end: datetime,
    granularity_key: str
) -> list[tuple[datetime, datetime]]:
    granularity_seconds = GRANULARITIES[granularity_key]
    chunk_seconds = COINBASE_MAX_CANDLES_PER_REQUEST * granularity_seconds
    chunk_delta = timedelta(seconds=chunk_seconds)

    chunks = []
    chunk_start = start

    while chunk_start < end:
        chunk_end = min(chunk_start + chunk_delta, end)
        chunks.append((chunk_start, chunk_end))
        chunk_start = chunk_end

    return chunks
