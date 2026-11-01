# Pacific Northwest scenario — map design

## Intent

A 2048×2048 OpenTTD scenario of the Pacific Northwest, Comox BC to Portland OR,
that is faithful to real geography: real scale, real terrain and real towns as
they were in **1990**. The player should recognise the region and find things
where they actually are, while the game stays playable.

This is project 1 of 3. Project 2 is a FIRS 5.2.0 fork with a PNW economy
(Arctic Basic plus Boeing, De Havilland Canada/Viking Air, orchards, farms,
shipyards, the Product of Origin dairy → EDEKA Gouda Sandwiches chain).
Project 3 places real 1990 industries on this map using the fork's types.
Industries are out of scope here.

## Goals

- Square map, 2048×2048 tiles, **sub-arctic** climate (FIRS Arctic Basic is
  the planned base economy), start date 1 Jan 1990.
- Even crop: no region favoured. Centre on the midpoint of Comox and Portland.
- Real terrain from a public DEM, at true horizontal scale.
- Real towns of 1990 population ≥ 2,000 with real names and positions.
- Saved as a `.scn` the user can load in TGTFTD, with no industries.

## Non-goals

- Industries (project 3) and the FIRS fork (project 2).
- Exaggerated or stylised terrain.
- Towns below 2,000 people (real 1990 population).
- Roads, rail, airports or other infrastructure (player builds those).

## Anti-goals

- Favouring Puget Sound (or any area) in the crop or the density of detail.
- Real-size populations: OpenTTD towns do badly with that many people.

## Constraints and decisions

### Extent and projection (user: no region favoured, ocean only on the west, extend east)
- Comox 49.67°N, Portland 45.52°N. Bounds lat **45.3–49.9°N** (~511 km),
  so each tile is ~250 m. Width the same distance.
- West edge **−126.0°** (user: ~125.9°W, keep Tofino −125.91 and Ucluelet), so
  Nootka Sound/Gold River are cut. East edge follows at ≈ **−119.2°**: Yakima,
  Ellensburg, Wenatchee, Moses Lake and Richland are in; Kennewick and Pasco
  (−119.1) fall on or just past the edge.
- *My call*: transverse Mercator centred on (47.6°N, −122.6°), square in metres.

### Elevation (user: true scale, compress mountains to 15)
- 1 height level ≈ 115 m (half a tile, OpenTTD's visual ratio).
- Linear true scale up to 10 levels (~1,150 m); above that compress smoothly so
  the highest point (Rainier, 4,392 m) lands on exactly **15**. Knee at 10 is
  *my call*.
- Snowline *my call*: ~level 9–10, so the Cascades/Olympics/Coast Mountains are
  snow-capped and the lowlands are green.
- Water at level 0: ocean, Puget Sound, Strait of Georgia, Juan de Fuca, and
  tidal reaches of rivers (Columbia to Bonneville, Fraser to ~Mission,
  Willamette to Oregon City) plus sea-level lakes (Lake Washington). All other
  land ≥ level 1 so it is not flooded. *My call*: rivers and lakes above sea
  level (upper Columbia, Lake Chelan…) stay land, to keep true-scale terrain;
  water too narrow to resolve (< ~2 tiles) is dropped.
- DEM source *my call*: AWS Terrain Tiles (Terrarium, no API key). Water mask
  from DEM sea level plus OSM water polygons. Imported as an OpenTTD heightmap PNG.

### Towns (user: ≥ 2,000, small towns 100–300, Seattle ≤ 3,000, drop smaller when too close)
- Selection on real 1990 US census / 1991 Canadian census population ≥ 2,000.
  *My call*: US incorporated places and CDPs; Canadian municipalities (not CMAs).
- **Game population = 100 × (real/2000)^0.6125** (curve is *my call*): a 2,000 town
  → 100, 10k → ~270, 20k → ~410, Tacoma (177k) → ~1,550, Portland (437k) →
  ~2,700, Vancouver (472k) → ~2,850, Seattle (516k) → 3,000.
- Cities flag *my call*: real population ≥ 100k.
- Loaded through the existing town-data JSON import (`LoadTownData`,
  `src/genworld.cpp`). Where two towns violate OpenTTD's minimum town distance,
  drop the smaller.

### Assembly (*my call*, revised)
- No engine changes. A script writes the heightmap PNG and towns JSON; the
  `.scn` is assembled in the scenario editor with the documented workflow
  (`docs/importing_town_data.md`): load heightmap, load town data, save. Console
  automation was dropped because heightmap generation and town growth are
  asynchronous and would need new sequencing code for a one-off build.
- Town spacing uses `town_min_distance = 10` (the minimum), and the script
  applies the same Manhattan rule so the drop is decided up front.

## Deliverables
- `tools/pnw_scenario.py`: regenerates the heightmap PNG, towns JSON and a
  preview image from cached source data; `--check` runs its self-checks.
- `PNW 1990.scn` in `G:\Google Drive\Documents\OpenTTD\scenario`.

## Left to the builder
- DEM resampling/smoothing and handling of narrow channels.
- Exact source for 1990/1991 census place lists and coordinates.

## Revisions after the first build (user, 2026-10-31)
- Climate **temperate** (green ground; no snow). The FIRS fork's PNW economy must therefore be a temperate one.
- Heightmap rotation **counter-clockwise**.
- **Water above sea level**: all OSM lakes and rivers at their real height (Okanagan Lake, Chelan, upper Fraser and
  Columbia). Water below ~57 m (land level 1) stays sea-level water; higher water is written to a companion image
  `pnw_1990.layers.png` that the fork's heightmap import turns into river-class water (no flooding). Banks are
  levelled so lake tiles are flat.
- **Major rivers widened** to at least 3 tiles: Fraser, Columbia, Willamette, Skagit, Cowlitz, Snohomish (OSM
  centre lines). A deliberate exaggeration; everything else stays true width.
- **Trees** from the Hansen Global Forest Change canopy cover (2000): under 30% none, then 1–4 trees per tile, via the
  same companion image.
- **Towns**: Tofino and Ucluelet kept under 2,000; smaller places (>= 250 people) fill gaps of >= 40 tiles from any
  town; census areas named "<direction> <neighbouring town>" take their own other name or the nearest OSM suburb.
