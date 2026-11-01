# FIRS PNW — industry set design

Project 2 of 3 for the PNW 1990 scenario (`2026-10-31-pnw-scenario-design.md`). Project 3 places the industries on
the saved scenario and is out of scope here.

## Intent

An industry NewGRF for the Pacific Northwest scenario: a fork of FIRS 5.2.0 with a new temperate "Pacific Northwest"
economy. It keeps FIRS's chains where they fit the region and adds the region's signature industries (Boeing,
De Havilland Canada, shipyards, Alaska crude) plus the user's own Product of Origin / EDEKA Gouda sandwich chain.
New vehicles that carry the new cargos go into the user's existing PNW Transit GRF.

## Goals

- Fork of FIRS 5.2.0 (tag `5.2.0`, github.com/andythenorth/firs) in its own repo, with its own GRF name and ID so it
  never clashes with real FIRS. Economy "Pacific Northwest", temperate climate.
- All chains below work end to end in TGTFTD with the user's vehicle sets.
- New industries have new 8-bit artwork in the OpenTTD/FIRS style (no 32bpp).
- New vehicles in PNW Transit (`G:\dev\coastal-grflink\transit`, `pnw-transit.grf`, GRF ID `TFBR`).

## Non-goals

- Placing industries on the scenario (project 3).
- Other FIRS economies: left as they are in the fork, not tuned.
- NAIS compatibility: the PNW game uses this set instead of NAIS.

## Anti-goals

- 32bpp or painterly art; anything that looks out of place next to FIRS and NARS.
- Cargos that no vehicle in the user's sets can carry.

## Player's vehicle sets (from "Teagan Transport, 27th Feb 1997.sav")

NARS 2.51 + NARS add-on set + NARS 2.5 passenger mod, North American Passenger Railroads, North American Track Set,
TTRS 3, North American Building Set, BC Ferries vessels/terminals, BC Aviation aircraft/airports, Coastal Waterfront,
plus PNW Transit. NARS wagons refit by cargo class, so every new cargo gets the classes that put it in the right
NARS wagons.

## Chains (user's design unless marked)

### Aerospace
- **Dreamlifter Delivery Airport** (Paine Field): primary, produces **Aircraft Parts** with no input ("from worldwide
  origins"). Delivering **Jet Fuel** boosts its production (FIRS primary-industry supply boost).
- **Aluminium Smelter** (real 1990 sites: Ferndale, Longview, Vancouver WA, Troutdale): primary, produces
  **Aluminium**, no input (*my call*: stands in for imported alumina and hydro power).
- **Aircraft Assembly Plant** (Renton): Aluminium + Aircraft Parts → **Aircraft**.
- **Aircraft Quality Assurance Centre** (Everett): Aircraft → **Certified Aircraft**, a higher-value cargo. It cannot
  build aircraft itself.
- **Customer Acceptance Centre** (Sea-Tac and YVR): accepts Aircraft and Certified Aircraft.
- **Floatplane Factory** (De Havilland Canada / Viking Air, Victoria airport): Aluminium + Aircraft Parts →
  **Floatplanes**.
- **Seaplane Base** (*my call* on sites: Vancouver Harbour, Victoria Inner Harbour, Nanaimo Harbour, Lake Union):
  accepts Floatplanes.

### Product of Origin / EDEKA
- **Product of Origin Dairy Farm** → **Product of Origin Dairy** (liquid) → **Product of Origin Sandwich Factory** →
  **EDEKA Gouda Sandwiches** → towns and **EDEKA Grocery Store**.
- Sandwiches use the same cargo classes as FIRS Food, so generic food wagons and containers carry them. PNW Transit
  adds EDEKA-branded containers that carry only sandwiches.

### Shipbuilding
- **Shipyard**: Steel + Lumber → **Ships**, accepted by **Port**.

### Oil
- **Oil Terminal** (Alaska crude, placed at Powell River so crude must be moved across the Strait): primary, produces
  Crude Oil with no input.
- Plus FIRS **Oil Rig** (offshore) and **Oil Wells** (on land), knowingly unrealistic for the region.
- **Oil Refinery** (Cherry Point, Ferndale, Anacortes, Tacoma): Crude Oil → **Jet Fuel** and Petrol;
  Petrol → FIRS Petrol Station.

### Supporting FIRS chains (*my call*, reused from FIRS 5.2.0 industries and cargos)
- Forestry: Forest → Wood → Sawmill (→ Lumber) and Paper Mill (→ Paper).
- Steel: Scrap Yard → Scrap Metal → Electric Arc Furnace → Steel.
- Farming: Orchard, Farm, Dairy Farm → Dairy; fishing: Fishing Grounds → Fishing Harbour.
- Power: Coal Mine (Centralia) → Power Plant.
- Towns: General Store, Hotel, Port, Wharf.
The exact FIRS inputs/outputs of these follow FIRS 5.2.0 as they are; where a FIRS industry needs a cargo not in this
economy, the builder drops that input or the industry and records it.

### Spawning and closure (user)
- **Signature industries are scenario-only and never close**: Dreamlifter Delivery Airport, Aluminium Smelter,
  Aircraft Assembly Plant, Aircraft QA Centre, Customer Acceptance Centre, Floatplane Factory, Seaplane Base, Oil
  Terminal. They never spawn at map generation or during play, never close, and have no location check that would
  stop them being placed at their real sites in the scenario editor.
- Everything else (forests, farms, oil wells and rigs, fishing, sawmills, shipyards, refineries, Product of Origin and
  EDEKA industries, …) spawns and closes like normal FIRS industries.

### Town delivery of sandwiches (user)
- EDEKA Gouda Sandwiches are accepted by EDEKA Grocery Stores and FIRS General Stores, both town industries. No house
  GRF.

### Dead ends (*my call*)
- Every output in the economy has a consumer. Where a reused FIRS output (Paper, Food, …) has none in the lists
  above, the FIRS industry that consumes it (Printing Works, …) joins the economy.
- The Oil Refinery is a new PNW-only industry with new art (no FIRS 5.2.0 economy has a refinery).

## New cargos

Aircraft Parts, Aluminium, Aircraft, Certified Aircraft, Floatplanes, Ships, Jet Fuel, Product of Origin Dairy,
EDEKA Gouda Sandwiches. Each gets a unique 4-letter label not used by FIRS or the standard cargo label list, cargo
classes chosen so NARS wagons carry what they physically could (liquid → tank cars; sandwiches → as FIRS Food;
aluminium/parts → as FIRS steel/goods), and a payment rate. Certified Aircraft pays more than Aircraft.

## New PNW Transit vehicles (user: "aircraft-carrying rail cars, for instance"; EDEKA containers)

*My call* on the set: an aircraft rail car (Aircraft, Certified Aircraft, Floatplanes), EDEKA-branded container wagon
and truck (sandwiches only), and a heavy-lift barge (Ships, Aircraft, Floatplanes), so every oversized cargo has
at least rail and water carriers. Built with the coastal-grflink toolchain and voxel renderer like the existing
vehicles.

## Artwork

8-bit, OpenTTD palette, matching FIRS. *My call*: rendered with coastal-grflink's voxel renderer
(`common/render.py`) into the sprite sheets the FIRS build uses, so buildings and vehicles share one look.

New industry art: Dreamlifter Delivery Airport, Aluminium Smelter, Aircraft Assembly Plant, Aircraft QA Centre,
Customer Acceptance Centre, Floatplane Factory, Seaplane Base, Shipyard, Oil Terminal, Oil Refinery, Product of
Origin Dairy Farm, Product of Origin Sandwich Factory, EDEKA Grocery Store. New cargo icons for each new cargo.

## Constraints
- FIRS is GPL v2; the fork stays GPL v2 and credits FIRS.
- Must load in TGTFTD (JGRPP-based) alongside the vehicle sets above.
- Built GRFs are installed to `G:\Google Drive\Documents\OpenTTD\newgrf`.

## Left to the builder
- Repo location and GRF ID of the fork, cargo labels and payment numbers.
- Production rates and boost amounts, within FIRS norms.
- Industry layouts and sizes.
