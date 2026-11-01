# PNW 1990 Scenario Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 2048×2048 sub-arctic 1990 scenario of the Pacific Northwest with real terrain and real towns, no industries.

**Architecture:** One Python script, `tools/pnw_scenario.py`, in the style of `tools/seaplane_fta.py`: plain functions, a docstring with usage, and a `--check` mode of assert-based self-checks (the repo has no pytest). It downloads and caches DEM tiles, OSM water and census data, then writes a heightmap PNG, a towns JSON and a preview PNG into the OpenTTD heightmap folder. The `.scn` is assembled in the scenario editor using the existing town-data import (`docs/importing_town_data.md`).

**Tech Stack:** Python 3.14, numpy 2.4, Pillow 12.3, requests (all installed; no new dependencies). AWS Terrain Tiles (Terrarium), the Overpass API, the 1990 US Census gazetteer, and a hand-curated BC 1991 CSV.

**Spec:** `docs/superpowers/specs/2026-10-31-pnw-scenario-design.md`

## Global Constraints

- Map 2048×2048 px = tiles. Transverse Mercator (spherical, R = 6,371,000 m) centred on (47.6°N, −122.6°). Half-extent H = 255,750 m. Pixel size s = 2H/2048 ≈ 249.76 m.
- Heightmap gray encoding for OpenTTD (`src/heightmap.cpp:407`, "Highest peak" = 15): gray 0 = water; land level L ∈ 1..15 → gray = 1 + 17·(L−1).
- Elevation: L = 1 + m/115 up to m = 1035 (L = 10). Above that, linear from L = 10 to L = 15 at the map's highest sampled point. Round, then clamp to [1, 15] for land.
- Water = sea (DEM ≤ 0 m, connected to the map edge) ∪ OSM `natural=water` polygons where DEM ≤ 15 m. Then a morphological opening (radius 1) to drop features under ~2 tiles wide.
- Towns: real population ≥ 2,000. Game population = round(100 · (real/2000)^k), k = ln 30 / ln(516259/2000) ≈ 0.6125 (pins 2,000 → 100 and Seattle 516,259 → 3,000). `city` = real ≥ 100,000. Greedy by real population (descending): drop a town if its Manhattan pixel distance to an already-kept town is < 10.
- Town JSON coordinates are swapped (`docs/importing_town_data.md` step 8): `"x" = (row + 0.5)/2048`, `"y" = (col + 0.5)/2048`.
- Town names must be unique in OpenTTD. Strip the US suffixes " city", " town" and " CDP". When names collide, the smaller town gets " (WA)", " (OR)" or " (BC)".
- Outputs go to `G:\Google Drive\Documents\OpenTTD\scenario\heightmap\pnw_1990.png`, `pnw_1990.json` and `pnw_1990_preview.png`. The download cache is `tools/.pnw_cache/` (gitignored).

## Review Focus

1. **Duplicate town names** (Vancouver BC/WA, Langley BC/WA). The import would fail or misname them. Owned by Task 3 (`check_names`).
2. **Swapped or flipped town coordinates.** Towns would land mirrored or in the sea. Owned by Task 3 (Seattle pixel check) and Task 4 (in-game placement check).
3. **Diked lowland below 0 m** (Fraser delta, Skagit flats) misread as sea. The preview must show Richmond and Delta as land. Owned by Task 2.
4. **Rainier not on exactly 15, or water at gray > 0.** This breaks the height encoding. Owned by Task 2 (`check_levels`).
5. **Towns whose pixel is water** (waterfront cities like Seattle and Victoria). OpenTTD searches a 16-tile radius, but any that fail become signs. Task 4 records the failures and moves those town points onto the nearest land pixel.

---

### Task 1: Projection and grid

**Files:**
- Create: `tools/pnw_scenario.py`
- Modify: `.gitignore` (add `tools/.pnw_cache/`)

**Interfaces:**
- Produces: `to_pixel(lat: float, lon: float) -> tuple[float, float]` returns (col, row), with row 0 at the north. `to_lonlat(col: float, row: float) -> tuple[float, float]` returns (lon, lat). Constants `SIZE = 2048`, `HALF = 255_750.0`, `PX = 2 * HALF / SIZE`, `CACHE`, `OUT_DIR`.

- [ ] **Step 1: Write `check_projection()`** (called by `--check`):

```python
col, row = to_pixel(47.6, -122.6); assert abs(col - 1024) < 1 and abs(row - 1024) < 1
for lat, lon in [(49.67, -124.93), (45.52, -122.68), (49.153, -125.906), (48.946, -125.54)]:  # Comox, Portland, Tofino, Ucluelet
    c, r = to_pixel(lat, lon); assert 20 <= c < SIZE - 20 and 0 <= r < SIZE, (lat, lon, c, r)
c, r = to_pixel(46.21, -119.14); assert c > SIZE - 10  # Kennewick on/over the east edge
lon, lat = to_lonlat(*to_pixel(48.0, -121.0)); assert abs(lat - 48.0) < 1e-6 and abs(lon + 121.0) < 1e-6
```

- [ ] **Step 2: Run** `python tools/pnw_scenario.py --check`. Expected: it fails, because the functions don't exist yet.
- [ ] **Step 3: Implement** using spherical transverse Mercator (φ0 = 47.6°, λ0 = −122.6°):

```
forward: B = cosφ·sin(Δλ); x = R·atanh(B); y = R·(atan2(tanφ, cosΔλ) − φ0)
inverse: D = y/R + φ0; φ = asin(sin D / cosh(x/R)); Δλ = atan2(sinh(x/R), cos D)
col = (x + HALF)/PX; row = (HALF − y)/PX
```

- [ ] **Step 4: Run** `--check`. Expected: `projection ok`.
- [ ] **Step 5: Commit** `tools/pnw_scenario.py` and `.gitignore` with the message "PNW scenario: map projection".

### Task 2: Heightmap

**Files:**
- Modify: `tools/pnw_scenario.py`

**Interfaces:**
- Consumes: `to_lonlat` and `to_pixel` (Task 1).
- Produces: `dem() -> np.ndarray` (2048×2048 float32 metres; cached as `CACHE/dem.npy`). `water(elev) -> np.ndarray[bool]`. `levels(elev, water) -> np.ndarray[uint8]` (0 for water, 1..15 for land). `gray(levels) -> np.ndarray[uint8]`. `write_heightmap()` writes `pnw_1990.png` (8-bit L) and the preview.

- [ ] **Step 1: Write `check_levels()`:**

```python
e = np.array([[-5, 0, 50, 115, 1035, 2500, 4392]], np.float32); w = e < 0
L = levels(e, w, peak=4392)
assert L.tolist() == [[0, 1, 1, 2, 10, 12, 15]]
assert gray(L).tolist() == [[0, 1, 1, 18, 154, 188, 239]]
assert all(1 + (g - 1) * 15 // 255 == l for g, l in zip(gray(L)[0][1:], L[0][1:]))  # heightmap.cpp:407
```

- [ ] **Step 2: Run** `--check`. Expected: it fails.
- [ ] **Step 3: Implement `levels(elev, water, peak)` and `gray(L)`** per Global Constraints. 2500 m → 10 + 5·1465/3357 = 12.18 → 12.
- [ ] **Step 4: Run** `--check`. Expected: it passes.
- [ ] **Step 5: Implement `dem()`.**
  - Fetch the Terrarium tiles at z10 (`https://s3.amazonaws.com/elevation-tiles-prod/terrarium/10/{x}/{y}.png`) covering the map's lon/lat bounds, caching each tile under `CACHE/terrarium/`.
  - Decode with `R·256 + G + B/256 − 32768`.
  - Sample each output pixel's `to_lonlat` bilinearly in Web Mercator.
- [ ] **Step 6: Implement `water(elev)`.**
  - Sea: `elev <= 0`, flood-filled from map-edge pixels (BFS in numpy or a `collections.deque`).
  - OSM: Overpass `[out:json][timeout:900];(way["natural"="water"](bbox);relation["natural"="water"](bbox););out geom;`, cached as `CACHE/osm_water.json`. Rasterise with `PIL.ImageDraw.polygon`: outer rings fill 1, inner rings fill 0. Keep pixels where `elev <= 15`.
  - Union the two, then open with radius 1 (erode, then dilate, via numpy shifts).
- [ ] **Step 7: Implement `write_heightmap()` and `--build`.**
  - `levels` uses `peak = elev[~water].max()`.
  - Save the PNG.
  - Save the preview: water blue, land shaded by level, towns overlaid (once Task 3 exists).
  - Print the peak in metres and its pixel position.
- [ ] **Step 8: Run** `python tools/pnw_scenario.py --build`. Expected: it prints a peak of about 4,390 m near Rainier, `to_pixel(46.853, -121.760)` ±3 px. `pnw_1990.png` is 2048×2048, mode L, max 239.
- [ ] **Step 9: Inspect the preview** with the Read tool on `pnw_1990_preview.png`. Check:
  - Puget Sound, Juan de Fuca, the Strait of Georgia, Lake Washington, and the Columbia up to Bonneville are water.
  - The Fraser delta (Richmond, Delta) and the Skagit flats are land.
  - The upper Columbia and Lake Chelan are land.
  
  Fix the thresholds if any of these is wrong and note the change in the commit.
- [ ] **Step 10: Commit** with the message "PNW scenario: heightmap from Terrarium DEM and OSM water".

### Task 3: Towns

**Files:**
- Modify: `tools/pnw_scenario.py`
- Create: `tools/pnw_scenario_bc_1991.csv` (columns `name,pop1991,lat,lon`): every BC municipality inside the map with a 1991 census population ≥ 2,000. Compiled from the StatCan 1991 census and Wikipedia coordinates; note the sources in the CSV header comment.

**Interfaces:**
- Consumes: `to_pixel`, and the water mask from Task 2.
- Produces: `load_places() -> list[tuple[str, int, float, float, str]]` (name, real pop, lat, lon, region). `select_towns(places) -> list[dict]` in the town-JSON format (`name`, `population`, `city`, `x`, `y`). `write_towns()` writes `pnw_1990.json`.

- [ ] **Step 1: Write `check_towns()`:**

```python
assert game_pop(2000) == 100 and game_pop(516259) == 3000
p = [("Seattle", 516259, 47.6062, -122.3321, "WA"), ("Vancouver", 471844, 49.2827, -123.1207, "BC"),
     ("Vancouver", 46380, 45.6387, -122.6615, "WA"), ("Langley", 19765, 49.104, -122.66, "BC"),
     ("Tiny", 1999, 47.0, -122.0, "WA"), ("Shadow", 3000, 47.6070, -122.3330, "WA")]
t = {d["name"]: d for d in select_towns(p)}
assert "Vancouver (WA)" in t and "Vancouver" in t and t["Vancouver"]["city"]
assert "Tiny" not in t and "Shadow" not in t          # under 2,000 / within 10 px of Seattle
c, r = to_pixel(47.6062, -122.3321)
assert abs(t["Seattle"]["x"] - (int(r) + 0.5) / 2048) < 1e-9 and abs(t["Seattle"]["y"] - (int(c) + 0.5) / 2048) < 1e-9
assert len({d["name"] for d in t.values()}) == len(t)
```

- [ ] **Step 2: Run** `--check`. Expected: it fails.
- [ ] **Step 3: Implement `game_pop`, `select_towns` and the naming rules** per Global Constraints. Drop places outside 0 ≤ col, row < 2048.
- [ ] **Step 4: Run** `--check`. Expected: it passes.
- [ ] **Step 5: Implement `load_places()`.**
  - US: the 1990 gazetteer `https://www2.census.gov/geo/docs/maps-data/data/gazetteer/places.zip`, cached. It's fixed-width; confirm the column layout from the file and keep WA (53) and OR (41).
  - BC: the CSV.
- [ ] **Step 6: Run `--build`.**
  - Expected: it prints the kept and dropped counts, and lists every town whose pixel is water.
  - Spot-check Comox, Tofino, Victoria, Bellingham, Seattle, Yakima, Ellensburg and Portland in the JSON.
  - Seattle should have population 3000 and `city: true`.
- [ ] **Step 7: Commit** with the message "PNW scenario: 1990 towns".

### Task 4: Assemble the scenario (manual, in the editor)

**Files:**
- Modify: `tools/pnw_scenario.py` docstring: add the assembly steps below so they're kept with the script.

- [ ] **Step 1: No NewGRFs.** Leave FIRS out; industries are project 3.
- [ ] **Step 2: Scenario editor → Load heightmap → `pnw_1990.png`**, with these settings:
  - Map 2048×2048; climate Sub-arctic; Highest peak 15.
  - Rotation clockwise (coordinates then match the Land Info tool).
  - Start date 1 Jan 1990; snow line height 10.
  - Town-name style English; town minimum distance 10.
  - No towns and no industries.
- [ ] **Step 3: Town generation → Load from file → `pnw_1990.json`.**
  - Expected: towns appear at the right places, e.g. Seattle on Elliott Bay and Victoria at the island's southern tip.
  - Signs mark failures. Record each failed name.
  - For failed towns whose real site is water, add a nearest-land-pixel nudge in `select_towns` and rebuild.
  - Re-import until there are no failures, or only failures in rough terrain that you place by hand.
- [ ] **Step 4: Save the scenario** as `PNW 1990` in `G:\Google Drive\Documents\OpenTTD\scenario`. Reload it with Play Scenario and confirm the date is 1990, the climate is sub-arctic and snow sits on the Cascades.
- [ ] **Step 5: Commit** the docstring update (and any nudge code) with the message "PNW scenario: assembly steps".
