import math
from typing import List


def pct_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / old * 100


def rolling_mean(values: List[float], window: int) -> List[float]:
    result = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(float("nan"))
        else:
            window_vals = values[i - window + 1 : i + 1]
            result.append(sum(window_vals) / window)
    return result


def rolling_std(values: List[float], window: int) -> List[float]:
    result = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(float("nan"))
        else:
            window_vals = values[i - window + 1 : i + 1]
            mean = sum(window_vals) / window
            variance = sum((v - mean) ** 2 for v in window_vals) / window
            result.append(math.sqrt(variance))
    return result


def normalize_minmax(values: List[float]) -> List[float]:
    valid = [v for v in values if not math.isnan(v)]
    if not valid:
        return [float("nan")] * len(values)
    min_v = min(valid)
    max_v = max(valid)
    if max_v == min_v:
        return [0.5] * len(values)
    return [(v - min_v) / (max_v - min_v) if not math.isnan(v) else float("nan") for v in values]


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


def safe_log(value: float) -> float:
    if value <= 0:
        return 0.0
    return math.log(value)
