#!/usr/bin/env python3
"""
Pacific Northwest 1990 scenario for TGTFTD: heightmap and town data generator.

A 2048x2048 map from Tofino/Comox to Portland and east to Yakima, at true horizontal scale (~250 m per tile),
in a spherical transverse Mercator projection centred on 47.6N 122.6W. See
docs/superpowers/specs/2026-10-31-pnw-scenario-design.md.

    python tools/pnw_scenario.py --check    # self-checks
    python tools/pnw_scenario.py --build    # write pnw_1990.png, .layers.png, .json and _preview.png

Downloads are cached in tools/.pnw_cache/.

Assembling the scenario (scenario editor, no NewGRFs):
  1. Settings: town minimum distance 10.
  2. Load heightmap pnw_1990.png: map 2048x2048, climate Temperate, highest peak 15, rotation counter-clockwise,
     start date 1 Jan 1990, no towns, no industries, rivers none. pnw_1990.layers.png must sit next to it: the
     import reads it for lakes and rivers above sea level and for trees (heightmap.cpp ApplyHeightmapLayers).
  3. Town generation -> Load from file -> pnw_1990.json. Failed towns are left as signs; place those by hand.
  4. Save the scenario as "PNW 1990".
"""

import csv
import json
import math
import re
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


# Gazetteer points that sit far out in the water, replaced by the town centre.
PLACE_FIXES = {("Port Angeles", "WA"): (48.118, -123.430)}


def load_places():
    """1990 US census places in WA and OR, and BC municipalities from the 1991 census list."""
    z = fetch("https://www2.census.gov/geo/docs/maps-data/data/gazetteer/places.zip", CACHE / "places1990.zip")
    places = []
    for line in zipfile.ZipFile(z).read("places.txt").decode("latin1").splitlines():
        # "53 63000 Seattle city      WA    516259    249032 0000217284 0000152018 +47621800 -122350326"
        name, state, pop, _, _, _, lat, lon = line[9:].rsplit(None, 7)
        if state in ("WA", "OR"):
            head, _, kind = name.rpartition(" ")
            name = head if kind in ("city", "town", "CDP") else name
            lat, lon = PLACE_FIXES.get((name, state), (int(lat) / 1e6, int(lon) / 1e6))
            places.append((name, int(pop), lat, lon, state, kind == "CDP"))
    with open(ROOT / "tools" / "pnw_scenario_bc_1991.csv", encoding="utf-8") as f:
        for row in csv.DictReader(line for line in f if not line.startswith("#")):
            places.append((row["name"], int(row["pop1991"]), float(row["lat"]), float(row["lon"]), "BC", False))
    # Census areas such as "West Longview" only repeat a neighbour's name: use their own other name
    # ("East Hill-Meridian" -> Meridian) or else the local suburb or community.
    taken, candidates = {pl[0] for pl in places}, osm_places()
    for i, (name, pop, lat, lon, region, cdp) in enumerate(places):
        m = CARDINAL.match(name)
        if not (cdp and pop >= GAP_MIN_POP and m):
            continue
        rest = name[m.end():]
        if "-" in name:
            new = next((part for part in name.split("-") if not CARDINAL.match(part) and part not in taken), None)
        elif any(rest == n or rest.startswith(n + " ") for n in taken if n != name):
            new = suburb_name(lat, lon, candidates, taken)
        else:
            continue
        if new:
            taken.add(new)
            places[i] = (new, pop, lat, lon, region, cdp)
    return [pl[:5] for pl in places]


CARDINAL = re.compile(r"^(North|South|East|West) ")
DIRECTION = re.compile(r"\b(North|South|East|West)\b")
PLACE_RANK = {"suburb": 0, "quarter": 1, "neighbourhood": 2, "village": 3, "hamlet": 4}


def suburb_name(lat, lon, candidates, taken):
    """Best (name, lat, lon, place) candidate within 5 km: suburbs before neighbourhoods before villages, then nearest.
    Names already taken or with a direction in them are skipped."""
    def km(c):
        return math.hypot((c[1] - lat) * 111.2, (c[2] - lon) * 111.2 * math.cos(math.radians(lat)))
    ok = [c for c in candidates if c[3] in PLACE_RANK and c[0] not in taken and not DIRECTION.search(c[0]) and km(c) <= 5]
    return min(ok, key=lambda c: (PLACE_RANK[c[3]], km(c)))[0] if ok else None


def osm_places():
    """OSM suburb, neighbourhood and small settlement names over the map, as (name, lat, lon)."""
    p = CACHE / "osm_places.json"
    if not p.exists():
        lon, lat = grid_lonlat()
        overpass(f'[out:json][timeout:900];node["place"~"^(suburb|neighbourhood|quarter|village|hamlet|locality)$"]["name"]'
                 f'({lat.min():.3f},{lon.min():.3f},{lat.max():.3f},{lon.max():.3f});out;', p)
    return [(e["tags"]["name"], e["lat"], e["lon"], e["tags"]["place"]) for e in json.loads(p.read_text(encoding="utf-8"))["elements"]]


def check_towns():
    c = [("North Hill", 47.0, -122.0, "suburb"), ("Kelso", 47.0, -122.01, "suburb"), ("Ramp", 47.0, -122.0, "locality"),
         ("Hamlet", 47.0, -122.005, "hamlet"), ("Lexington", 47.0, -122.03, "suburb"), ("Far", 47.2, -122.0, "suburb")]
    assert suburb_name(47.0, -122.0, c, {"Kelso"}) == "Lexington"  # suburb beats a nearer hamlet; no locality
    assert suburb_name(47.2, -122.3, c, set()) is None  # nothing within 5 km
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
    pa = [pl for pl in load_places() if pl[0] == "Port Angeles"]
    assert pa and abs(pa[0][2] - 48.118) < 1e-6, pa  # the gazetteer point is offshore in the Strait
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
    """Elevation in metres of every map pixel, from AWS Terrain Tiles (Terrarium)."""
    def terrarium(img):
        a = np.asarray(img.convert("RGB"), np.float32)
        return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
    return sample_tiles("https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", "terrarium", terrarium)


def tree_cover():
    """Canopy cover 0..1 of every map pixel, from the Hansen Global Forest Change tree cover (year 2000)."""
    return sample_tiles("https://storage.googleapis.com/earthenginepartners-hansen/tiles/gfc_v1.4/tree_alpha/{z}/{x}/{y}.png",
                        "hansen", lambda img: np.asarray(img.convert("RGBA"), np.float32)[..., 3] / 255)


def sample_tiles(url, name, decode):
    """Sample a z10 XYZ tile layer bilinearly at every map pixel; decode turns a tile image into a float array."""
    cached = CACHE / f"{name}.npy"
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
        try:
            p = fetch(url.format(z=z, x=x, y=y), CACHE / name / f"{z}_{x}_{y}.png")
        except requests.HTTPError as e:
            if e.response.status_code != 404:
                raise
            return xy, np.zeros((256, 256), np.float32)  # no tile: open ocean
        return xy, decode(Image.open(p))

    mosaic = np.zeros(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256), np.float32)
    with ThreadPoolExecutor(16) as pool:
        for (x, y), a in pool.map(tile, [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]):
            mosaic[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = a
    fx, fy = tx - x0 * 256 - 0.5, ty - y0 * 256 - 0.5
    ix, iy = np.floor(fx).astype(int), np.floor(fy).astype(int)
    wx, wy = fx - ix, fy - iy
    m = mosaic
    v = ((m[iy, ix] * (1 - wx) + m[iy, ix + 1] * wx) * (1 - wy) + (m[iy + 1, ix] * (1 - wx) + m[iy + 1, ix + 1] * wx) * wy)
    np.save(cached, v.astype(np.float32))
    return v.astype(np.float32)


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
                overpass(f'[out:json][timeout:900];(way["natural"="{natural}"]({bbox});relation["natural"="{natural}"]({bbox}););out geom;', p)
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


def overpass(query, path):
    """Run an Overpass query into path, retrying busy servers."""
    for attempt in range(6):
        server = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")[attempt % 2]
        r = requests.post(server, data={"data": query}, timeout=1800,
                          headers={"User-Agent": "TGTFTD pnw_scenario.py"})  # Overpass answers 406 to the default agent
        if r.status_code not in (429, 502, 503, 504):
            break
        time.sleep(30 * (attempt + 1))
    r.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)


MAJOR_RIVERS = ["Fraser", "Columbia", "Willamette", "Skagit", "Cowlitz", "Snohomish"]


def major_rivers():
    """Centre lines of the major rivers, as lists of (lon, lat)."""
    p = CACHE / "osm_major_rivers.json"
    if not p.exists():
        lon, lat = grid_lonlat()
        names = "|".join(MAJOR_RIVERS)
        overpass(f'[out:json][timeout:900];way["waterway"="river"]["name"~"^({names}) River$"]'
                 f'({lat.min():.3f},{lon.min():.3f},{lat.max():.3f},{lon.max():.3f});out geom;', p)
    return [[(g["lon"], g["lat"]) for g in el["geometry"]] for el in json.loads(p.read_text(encoding="utf-8"))["elements"]]


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


def flatten(lv, high):
    """Lower above-sea water and its banks to the lowest water level next to them, so lake tiles come out flat."""
    for _ in range(2):  # the second pass carries levels lowered by the first out to the banks
        p = np.pad(np.where(high, lv, 255), 1, constant_values=255)
        m = np.min([p[dy:dy + lv.shape[0], dx:dx + lv.shape[1]] for dy in range(3) for dx in range(3)], axis=0)
        lv = np.where(m < 255, np.minimum(lv, m), lv).astype(np.uint8)
    return lv


def layers(high, cover, w):
    """Companion image for the heightmap import: 255 = water above sea level, 1..4 = trees per tile, else 0."""
    trees = np.where(cover < 0.3, 0, np.clip(1 + np.rint((cover - 0.3) / 0.7 * 3), 1, 4))
    return np.where(high, 255, np.where(w, 0, trees)).astype(np.uint8)


def check_layers():
    lv = np.full((7, 7), 4, np.uint8)
    high = np.zeros((7, 7), bool)
    high[2:5, 2:5] = True
    lv[2:5, 2:5] = [[3, 4, 3], [3, 3, 3], [4, 3, 3]]
    f = flatten(lv, high)
    assert (f[1:6, 1:6] == 3).all() and (f[0] == 4).all() and (f[:, 6] == 4).all(), f
    cover = np.array([[0.2, 0.3, 1.0, 1.0, 1.0]])
    w = np.array([[False, False, False, True, True]])
    hi = np.array([[False, False, False, False, True]])
    assert layers(hi, cover, w).tolist() == [[0, 1, 4, 0, 255]], layers(hi, cover, w)
    print("layers ok")


def water(elev):
    """Sea (<= 0 m, connected to the map edge), OSM lakes and rivers, and OSM bays at <= 15 m, without features
    under 2 tiles wide; then the major rivers drawn 3 tiles wide."""
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
    rings = osm_rings("water")
    for outer in (True, False):  # holes after all outers
        for ring, is_outer in rings:
            if is_outer == outer and len(ring) > 2:
                draw.polygon([to_pixel(la, lo) for lo, la in ring], fill=1 if outer else 0)
    osm = np.asarray(img) > 0
    img = Image.new("L", (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(img)
    for ring, is_outer in osm_rings("bay"):  # bays: tidal flats such as Willapa Bay are above 0 m in the DEM
        if is_outer and len(ring) > 2:
            draw.polygon([to_pixel(la, lo) for lo, la in ring], fill=1)
    bay = (np.asarray(img) > 0) & (elev <= 15)

    img = Image.new("L", (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(img)
    for line in major_rivers():
        draw.line([to_pixel(la, lo) for lo, la in line], fill=1, width=3)
    return open2(sea | osm | bay) | (np.asarray(img) > 0)


def preview(lv, lay, towns=()):
    """Colour preview: water blue, land green to brown to white by height, darker with trees, towns as red dots."""
    ramp = np.array([[40, 90, 170]] + [[int(70 + 12 * i), int(150 - 5 * i), int(60 - 2 * i)] for i in range(1, 12)]
                    + [[220, 220, 220]] * 4, np.uint8)
    rgb = ramp[np.where(lay == 255, 0, lv)].astype(np.float32)
    rgb[(lay > 0) & (lay < 255)] *= 0.65
    img = Image.fromarray(rgb.astype(np.uint8))
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
    sea_level = w & (elev < 115 / 2)  # would be land level 1: becomes heightmap water at 0
    high = w & ~sea_level
    lv = flatten(levels(elev, sea_level, peak), high)
    Image.fromarray(gray(lv), "L").save(OUT_DIR / "pnw_1990.png")
    lay = layers(high, tree_cover(), w)
    Image.fromarray(lay, "L").save(OUT_DIR / "pnw_1990.layers.png")
    print(f"water {w.mean():.1%} ({high.mean():.1%} above sea level); trees on {(lay[lay < 255] > 0).mean():.0%} of tiles")
    print(f"levels {np.bincount(lv.ravel(), minlength=16).tolist()}")

    places = load_places()
    towns = select_towns(places)
    print(f"towns: {len(towns)} kept of {sum(p[1] >= 2000 for p in places)} with 2,000+ people (some outside the map)")
    wet = [t["name"] for t in towns if w[int(t["x"] * SIZE), int(t["y"] * SIZE)]]
    print(f"towns on a water pixel ({len(wet)}): {', '.join(wet)}")
    # LoadTownData searches 16 tiles around the point; beyond that the town becomes a sign.
    lost = [t["name"] for t in towns if w[max(0, int(t["x"] * SIZE) - 16):int(t["x"] * SIZE) + 17,
                                         max(0, int(t["y"] * SIZE) - 16):int(t["y"] * SIZE) + 17].all()]
    if lost:
        print(f"WARNING: no land within 16 tiles, these will fail to import: {', '.join(lost)}")
    (OUT_DIR / "pnw_1990.json").write_text(json.dumps(towns, indent=1), encoding="utf-8")
    preview(lv, lay, towns)


def main():
    if "--check" in sys.argv:
        check_projection()
        check_levels()
        check_water()
        check_layers()
        check_towns()
    elif "--build" in sys.argv:
        build()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
