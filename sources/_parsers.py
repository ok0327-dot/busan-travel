"""Shared parsing utilities for source adapters."""
from __future__ import annotations

import math

# 부산광역시 대략 bounding box (여유 포함)
BUSAN_LAT_MIN, BUSAN_LAT_MAX = 34.9, 35.5
BUSAN_LON_MIN, BUSAN_LON_MAX = 128.7, 129.4


def to_float(v) -> float | None:
    """Parse value to float; return None for invalid/NaN/zero."""
    try:
        f = float(v)
        if math.isnan(f) or f == 0:
            return None
        return f
    except (TypeError, ValueError):
        return None


def busan_latlon(lat_raw, lon_raw) -> tuple[float | None, float | None]:
    """부산 범위 내 좌표만 통과. 범위 벗어나면 (None, None)."""
    lat = to_float(lat_raw)
    lon = to_float(lon_raw)
    if lat is None or lon is None:
        return None, None
    if not (BUSAN_LAT_MIN <= lat <= BUSAN_LAT_MAX and BUSAN_LON_MIN <= lon <= BUSAN_LON_MAX):
        return None, None
    return lat, lon
