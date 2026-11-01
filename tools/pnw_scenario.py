#!/usr/bin/env python3
"""
Pacific Northwest 1990 scenario for TGTFTD: heightmap and town data generator.

A 2048x2048 map from Tofino/Comox to Portland and east to Yakima, at true horizontal scale (~250 m per tile),
in a spherical transverse Mercator projection centred on 47.6N 122.6W. See
docs/superpowers/specs/2026-10-31-pnw-scenario-design.md.

    python tools/pnw_scenario.py --check    # self-checks
    python tools/pnw_scenario.py --build    # write pnw_1990.png, pnw_1990.json and pnw_1990_preview.png

Downloads are cached in tools/.pnw_cache/.
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tools" / ".pnw_cache"
OUT_DIR = Path(r"G:\Google Drive\Documents\OpenTTD\scenario\heightmap")

SIZE = 2048
HALF = 255_750.0  # metres from the centre to each edge: 45.3N..49.9N
PX = 2 * HALF / SIZE
R = 6_371_000.0
LAT0, LON0 = math.radians(47.6), math.radians(-122.6)


def to_pixel(lat, lon):
    """(lat, lon) in degrees -> (col, row), row 0 at the north edge."""
    phi, dlam = math.radians(lat), math.radians(lon) - LON0
    x = R * math.atanh(math.cos(phi) * math.sin(dlam))
    y = R * (math.atan2(math.tan(phi), math.cos(dlam)) - LAT0)
    return (x + HALF) / PX, (HALF - y) / PX


def to_lonlat(col, row):
    """(col, row) -> (lon, lat) in degrees."""
    x, y = col * PX - HALF, HALF - row * PX
    d = y / R + LAT0
    phi = math.asin(math.sin(d) / math.cosh(x / R))
    dlam = math.atan2(math.sinh(x / R), math.cos(d))
    return math.degrees(dlam + LON0), math.degrees(phi)


def check_projection():
    col, row = to_pixel(47.6, -122.6)
    assert abs(col - 1024) < 1 and abs(row - 1024) < 1, (col, row)
    for lat, lon in [(49.67, -124.93), (45.52, -122.68), (49.153, -125.906), (48.946, -125.54)]:  # Comox, Portland, Tofino, Ucluelet
        c, r = to_pixel(lat, lon)
        assert 20 <= c < SIZE - 20 and 0 <= r < SIZE, (lat, lon, c, r)
    c, r = to_pixel(46.21, -119.14)
    assert c > SIZE - 10, c  # Kennewick on/over the east edge
    lon, lat = to_lonlat(*to_pixel(48.0, -121.0))
    assert abs(lat - 48.0) < 1e-6 and abs(lon + 121.0) < 1e-6, (lon, lat)
    print("projection ok")


def main():
    if "--check" in sys.argv:
        check_projection()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
