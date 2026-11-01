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

import csv
import json
import math
import sys
import time
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

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
    """(col, row) -> (lon, lat) in degrees; also takes numpy arrays."""
    x, y = col * PX - HALF, HALF - row * PX
    d = y / R + LAT0
    phi = np.arcsin(np.sin(d) / np.cosh(x / R))
    dlam = np.arctan2(np.sinh(x / R), np.cos(d))
    return np.degrees(dlam + LON0), np.degrees(phi)


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


def levels(elev, water, peak):
    """Metres -> OpenTTD height levels: 0 water, 1 + m/115 up to level 10, then linear to 15 at the peak."""
    knee = 9 * 115
    lv = np.where(elev <= knee, 1 + elev / 115, 10 + 5 * (elev - knee) / (peak - knee))
    lv = np.clip(np.rint(lv), 1, 15).astype(np.uint8)
    lv[water] = 0
    return lv


def gray(lv):
    """Height levels -> heightmap grey, inverse of heightmap.cpp: 1 + (g - 1) * 15 / 255."""
    return np.where(lv > 0, 1 + 17 * (lv.astype(np.int32) - 1), 0).astype(np.uint8)


def check_levels():
    e = np.array([[-5, 0, 50, 115, 1035, 2500, 4392]], np.float32)
    lv = levels(e, e < 0, peak=4392)
    assert lv.tolist() == [[0, 1, 1, 2, 10, 12, 15]], lv
    g = gray(lv)
    assert g.tolist() == [[0, 1, 1, 18, 154, 188, 239]], g
    assert all(1 + (int(a) - 1) * 15 // 255 == b for a, b in zip(g[0][1:], lv[0][1:]))  # heightmap.cpp:407
    print("levels ok")


def game_pop(real):
    """Real 1990 population -> OpenTTD target: 2,000 -> 100 and Seattle 516,259 -> 3,000 on a power curve."""
    return round(100 * (real / 2000) ** (math.log(30) / math.log(516259 / 2000)))


TOWN_MIN_DISTANCE = 10  # economy.town_min_distance to set in the editor; Manhattan tiles
ALWAYS = {"Tofino", "Ucluelet"}  # kept under 2,000 people at the user's request
GAP_DISTANCE = 40  # a smaller place fills a gap this far (Manhattan tiles, ~10 km) from every kept town
GAP_MIN_POP = 250


def select_towns(places):
    """(name, real pop, lat, lon, region) places -> town-data JSON entries (docs/importing_town_data.md).

    Largest first: places of 2,000+ (and ALWAYS), then smaller places that fill a gap of GAP_DISTANCE.
    A town closer than TOWN_MIN_DISTANCE to a kept one is dropped, as OpenTTD would refuse it.
    A name already taken gets the region appended. JSON x/y are swapped: x is the row, y the column.
    Populations start at 100 at least, the bottom of the small-town range."""
    kept, names = [], set()
    by_size = sorted(places, key=lambda p: -p[1])
    for gap_pass in (False, True):
        for name, pop, lat, lon, region in by_size:
            c, r = (int(v) for v in to_pixel(lat, lon))
            big = pop >= 2000 or name in ALWAYS
            if big == gap_pass or (gap_pass and pop < GAP_MIN_POP) or not (0 <= c < SIZE and 0 <= r < SIZE):
                continue
            if any(abs(c - kc) + abs(r - kr) < (GAP_DISTANCE if gap_pass else TOWN_MIN_DISTANCE) for _, _, kc, kr, _ in kept):
                continue
            if name in names:
                name = f"{name} ({region})"
            names.add(name)
            kept.append((name, pop, c, r, region))
    return [{"name": n, "population": max(100, game_pop(p)), "city": p >= 100_000, "x": (r + 0.5) / SIZE, "y": (c + 0.5) / SIZE}
            for n, p, c, r, _ in kept]


def load_places():
    """1990 US census places in WA and OR, and BC municipalities from the 1991 census list."""
    z = fetch("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/places.zip", CACHE / "places1990.zip")
    places = []
    for line in zipfile.ZipFile(z).read("places.txt").decode("latin1").splitlines():
        # "53 63000 Seattle city      WA    516259    249032 0000217284 0000152018 +47621800 -122350326"
        name, state, pop, _, _, _, lat, lon = line[9:].rsplit(None, 7)
        if state in ("WA", "OR"):
            head, _, kind = name.rpartition(" ")
            places.append((head if kind in ("city", "town", "CDP") else name, int(pop), int(lat) / 1e6, int(lon) / 1e6, state))
    with open(ROOT / "tools" / "pnw_scenario_bc_1991.csv", encoding="utf-8") as f:
        for row in csv.DictReader(line for line in f if not line.startswith("#")):
            places.append((row["name"], int(row["pop1991"]), float(row["lat"]), float(row["lon"]), "BC"))
    return places


def check_towns():
    assert game_pop(2000) == 100 and game_pop(516259) == 3000, (game_pop(2000), game_pop(516259))
    p = [("Seattle", 516259, 47.6062, -122.3321, "WA"), ("Vancouver", 471844, 49.2827, -123.1207, "BC"),
         ("Vancouver", 46380, 45.6387, -122.6615, "WA"), ("Langley", 19765, 49.104, -122.66, "BC"),
         ("Tiny", 1999, 47.63, -122.25, "WA"), ("Shadow", 3000, 47.6070, -122.3330, "WA"), ("Tofino", 1103, 49.153, -125.9066, "BC"),
         ("Remote", 400, 47.9, -121.0, "WA"), ("Hamlet", 200, 48.2, -121.0, "WA")]
    t = {d["name"]: d for d in select_towns(p)}
    assert "Vancouver (WA)" in t and "Vancouver" in t and t["Vancouver"]["city"], t.keys()
    assert "Shadow" not in t and "Tofino" in t, t.keys()  # within 10 px of Seattle / asked for
    assert "Tiny" not in t and "Hamlet" not in t and t["Remote"]["population"] == 100, t.keys()  # no gap / too small / gap
    c, r = to_pixel(47.6062, -122.3321)
    assert abs(t["Seattle"]["x"] - (int(r) + 0.5) / SIZE) < 1e-9 and abs(t["Seattle"]["y"] - (int(c) + 0.5) / SIZE) < 1e-9
    assert len({d["name"] for d in t.values()}) == len(t)
    print("towns ok")


def grid_lonlat():
    """Lon/lat of every map pixel centre, each a SIZE x SIZE array."""
    rows, cols = np.mgrid[0:SIZE, 0:SIZE] + 0.5
    return to_lonlat(cols, rows)


def fetch(url, path):
    """Download url to path once."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, timeout=900)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


def dem():
    """Elevation in metres of every map pixel, sampled bilinearly from AWS Terrain Tiles (Terrarium) at z10."""
    cached = CACHE / "dem.npy"
    if cached.exists():
        return np.load(cached)
    z, n = 10, 1024
    lon, lat = grid_lonlat()
    tx = (lon + 180) / 360 * n * 256  # global Web Mercator pixel coordinates
    ty = (1 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2 * n * 256
    x0, x1 = int(tx.min()) // 256, int(tx.max()) // 256 + 1
    y0, y1 = int(ty.min()) // 256, int(ty.max()) // 256 + 1

    def tile(xy):
        x, y = xy
        p = fetch(f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", CACHE / "terrarium" / f"{z}_{x}_{y}.png")
        a = np.asarray(Image.open(p).convert("RGB"), np.float32)
        return xy, a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768

    mosaic = np.zeros(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256), np.float32)
    with ThreadPoolExecutor(16) as pool:
        for (x, y), a in pool.map(tile, [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]):
            mosaic[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = a
    fx, fy = tx - x0 * 256 - 0.5, ty - y0 * 256 - 0.5
    ix, iy = np.floor(fx).astype(int), np.floor(fy).astype(int)
    wx, wy = fx - ix, fy - iy
    m = mosaic
    elev = ((m[iy, ix] * (1 - wx) + m[iy, ix + 1] * wx) * (1 - wy) + (m[iy + 1, ix] * (1 - wx) + m[iy + 1, ix + 1] * wx) * wy)
    np.save(cached, elev.astype(np.float32))
    return elev.astype(np.float32)


def osm_rings(natural):
    """Closed rings of OSM natural=<natural> areas over the map, as (lonlat list, is_outer)."""
    lon, lat = grid_lonlat()
    lats, lons = np.linspace(lat.min(), lat.max(), 5), np.linspace(lon.min(), lon.max(), 5)
    elements = {}
    for i in range(4):  # 4x4 queries: one query for the whole map times out
        for j in range(4):
            p = CACHE / f"osm_{natural}" / f"{i}_{j}.json"
            if not p.exists():
                bbox = f"{lats[i]:.3f},{lons[j]:.3f},{lats[i + 1]:.3f},{lons[j + 1]:.3f}"
                q = f'[out:json][timeout:900];(way["natural"="{natural}"]({bbox});relation["natural"="{natural}"]({bbox}););out geom;'
                for attempt in range(6):
                    server = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")[attempt % 2]
                    r = requests.post(server, data={"data": q}, timeout=1800,
                                      headers={"User-Agent": "TGTFTD pnw_scenario.py"})  # Overpass answers 406 to the default agent
                    if r.status_code not in (429, 502, 503, 504):
                        break
                    time.sleep(30 * (attempt + 1))
                r.raise_for_status()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(r.content)
            for el in json.loads(p.read_text(encoding="utf-8"))["elements"]:
                elements[(el["type"], el["id"])] = el
    rings = []
    for el in elements.values():
        if el["type"] == "way" and "geometry" in el:
            rings.append(([(g["lon"], g["lat"]) for g in el["geometry"]], True))
        elif el["type"] == "relation":
            for role in ("outer", "inner"):
                segs = [[(g["lon"], g["lat"]) for g in m["geometry"]] for m in el.get("members", [])
                        if m["type"] == "way" and m.get("role", "outer") == role and "geometry" in m]
                rings += [(ring, role == "outer") for ring in join_segments(segs)]
    return rings


def join_segments(segs):
    """Join way segments that share end points into rings; unclosable chains are closed as they are."""
    rings, segs = [], [s for s in segs if len(s) > 1]
    while segs:
        ring = list(segs.pop())
        while ring[0] != ring[-1]:
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]
                elif s[-1] == ring[-1]:
                    ring += s[-2::-1]
                else:
                    continue
                segs.pop(i)
                break
            else:
                break
        rings.append(ring)
    return rings


def open2(mask):
    """Morphological opening with a 2x2 block: keeps only water that some 2x2 block of water covers."""
    p = np.pad(mask, ((0, 1), (0, 1)), constant_values=True)
    e = p[:-1, :-1] & p[1:, :-1] & p[:-1, 1:] & p[1:, 1:]
    q = np.pad(e, ((1, 0), (1, 0)), constant_values=False)
    return q[1:, 1:] | q[:-1, 1:] | q[1:, :-1] | q[:-1, :-1]


def check_water():
    m = np.zeros((8, 8), bool)
    m[1, :] = True       # 1 tile wide: dropped
    m[4:6, :] = True     # 2 tiles wide: kept
    o = open2(m)
    assert not o[1].any() and o[4:6].all() and o.sum() == 16, o.astype(int)
    print("water ok")


def water(elev):
    """Sea (<= 0 m and connected to the map edge) plus OSM water at <= 15 m, without features under ~2 tiles wide."""
    low = elev <= 0
    sea = np.zeros_like(low)
    todo = deque((r, c) for r in range(SIZE) for c in (0, SIZE - 1) if low[r, c])
    todo += deque((r, c) for c in range(SIZE) for r in (0, SIZE - 1) if low[r, c])
    while todo:
        r, c = todo.pop()
        if sea[r, c] or not low[r, c]:
            continue
        sea[r, c] = True
        if r > 0: todo.append((r - 1, c))
        if r < SIZE - 1: todo.append((r + 1, c))
        if c > 0: todo.append((r, c - 1))
        if c < SIZE - 1: todo.append((r, c + 1))

    img = Image.new("L", (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(img)
    rings = osm_rings("water") + osm_rings("bay")  # bays: tidal flats such as Willapa Bay are above 0 m in the DEM
    for outer in (True, False):  # holes after all outers
        for ring, is_outer in rings:
            if is_outer == outer and len(ring) > 2:
                draw.polygon([to_pixel(la, lo) for lo, la in ring], fill=1 if outer else 0)
    osm = (np.asarray(img) > 0) & (elev <= 15)

    w = sea | osm
    return open2(w)


def preview(lv, towns=()):
    """Colour preview: water blue, land green to brown to white by height, towns as red dots."""
    ramp = np.array([[40, 90, 170]] + [[int(70 + 12 * i), int(150 - 5 * i), int(60 - 2 * i)] for i in range(1, 12)]
                    + [[220, 220, 220]] * 4, np.uint8)
    img = Image.fromarray(ramp[lv])
    draw = ImageDraw.Draw(img)
    for t in towns:
        r, c = t["x"] * SIZE, t["y"] * SIZE
        draw.ellipse([c - 2, r - 2, c + 2, r + 2], fill=(230, 30, 30))
    img.save(OUT_DIR / "pnw_1990_preview.png")


def build():
    elev = dem()
    w = water(elev)
    peak = float(elev[~w].max())
    r, c = np.unravel_index(np.argmax(np.where(w, -1e9, elev)), elev.shape)
    print(f"peak {peak:.0f} m at col {c} row {r}; Rainier at {[round(v) for v in to_pixel(46.853, -121.760)]}")
    lv = levels(elev, w, peak)
    Image.fromarray(gray(lv), "L").save(OUT_DIR / "pnw_1990.png")
    print(f"water {w.mean():.1%}; levels {np.bincount(lv.ravel(), minlength=16).tolist()}")

    places = load_places()
    towns = select_towns(places)
    print(f"towns: {len(towns)} kept of {sum(p[1] >= 2000 for p in places)} with 2,000+ people (some outside the map)")
    wet = [t["name"] for t in towns if w[int(t["x"] * SIZE), int(t["y"] * SIZE)]]
    print(f"towns on a water pixel ({len(wet)}): {', '.join(wet)}")
    (OUT_DIR / "pnw_1990.json").write_text(json.dumps(towns, indent=1), encoding="utf-8")
    preview(lv, towns)


def main():
    if "--check" in sys.argv:
        check_projection()
        check_levels()
        check_water()
        check_towns()
    elif "--build" in sys.argv:
        build()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
