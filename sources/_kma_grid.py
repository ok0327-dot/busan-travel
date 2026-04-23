"""KMA Lambert Conformal Conic grid conversion (WGS84 ↔ nx/ny).

기상청 격자 5km. 149×253 grid.
테스트 케이스: 서울시청 (37.5665, 126.9780) → (60, 127),
             부산시청 (35.1796, 129.0756) → (98, 76).
"""
from __future__ import annotations

import math

RE = 6371.00877       # 지구 반경 (km)
GRID = 5.0            # 격자 간격 (km)
SLAT1 = 30.0          # 표준위도 1
SLAT2 = 60.0          # 표준위도 2
OLON = 126.0          # 기준점 경도
OLAT = 38.0           # 기준점 위도
XO = 43               # 기준점 X 좌표
YO = 136              # 기준점 Y 좌표
DEGRAD = math.pi / 180.0


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """WGS84 위경도 → KMA 격자 (nx, ny)."""
    re = RE / GRID
    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon = OLON * DEGRAD
    olat = OLAT * DEGRAD
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    )
    sf = (math.tan(math.pi * 0.25 + slat1 * 0.5) ** sn) * math.cos(slat1) / sn
    ro = re * sf / (math.tan(math.pi * 0.25 + olat * 0.5) ** sn)
    ra = re * sf / (math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5) ** sn)
    theta = lon * DEGRAD - olon
    if theta > math.pi:
        theta -= 2 * math.pi
    if theta < -math.pi:
        theta += 2 * math.pi
    theta *= sn
    nx = int(ra * math.sin(theta) + XO + 0.5)
    ny = int(ro - ra * math.cos(theta) + YO + 0.5)
    return nx, ny


if __name__ == "__main__":
    # 검증: 서울시청 = (60, 127), 부산시청 = (98, 76)
    for name, lat, lon, expected in [
        ("서울시청", 37.5665, 126.9780, (60, 127)),
        ("부산시청", 35.1796, 129.0756, (98, 76)),
        ("해운대",   35.1627, 129.1639, None),
        ("광안리",   35.1531, 129.1188, None),
    ]:
        got = latlon_to_grid(lat, lon)
        status = "OK" if expected is None or got == expected else "FAIL"
        print(f"{status}  {name}: ({lat}, {lon}) → {got}  expected={expected}")
