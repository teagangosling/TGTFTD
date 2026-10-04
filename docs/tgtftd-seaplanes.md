# TGTFTD: Seaplanes and Seaplane Terminals

### A guide for NewGRF authors

TGTFTD is a fork of [JGR's Patch Pack](https://github.com/JGRennison/OpenTTD-patches) (JGRPP). It adds:

* **Seaplanes**: aircraft that take off from and land on water.
* **Seaplane terminals**: airports that are built on water.

This document explains how both work in the game and how to make NewGRFs for them.

* [Seaplane aircraft](#4-making-seaplanes) are ordinary aircraft NewGRFs with one extra property set.
* [Seaplane terminals](#5-making-seaplane-terminals) are ordinary NewGRF airports with one extra property set.

A working example NewGRF (no graphics) is in [`docs/tgtftd/examples`](tgtftd/examples). It is built by a small Python script and also listed in NFO form.

---

## Contents

1. [How seaplanes work in the game](#1-how-seaplanes-work-in-the-game)
2. [Quick reference](#2-quick-reference)
3. [Detecting TGTFTD from a NewGRF](#3-detecting-tgtftd-from-a-newgrf)
4. [Making seaplanes](#4-making-seaplanes)
5. [Making seaplane terminals](#5-making-seaplane-terminals)
6. [Testing and debugging](#6-testing-and-debugging)
7. [Compatibility notes](#7-compatibility-notes)

---

## 1. How seaplanes work in the game

| | Land airports & heliports | Seaplane terminals |
|---|---|---|
| Built on | Flat land | Flat open water: sea, canal or river |
| Normal planes | ✔ | ✘ |
| Helicopters | ✔ | ✘ |
| Seaplanes | ✘ | ✔ |

* **The two groups are completely separate.** A seaplane cannot be given an order to a land airport, and a land plane or helicopter cannot be given an order to a seaplane terminal. The order window shows *"This seaplane can only land at seaplane terminals"* / *"Only seaplanes can use this seaplane terminal"*.
* A seaplane terminal's hangar only lists seaplanes in its *Build vehicle* window.
* Seaplanes only look for seaplane terminal hangars when they need servicing.
* Autoreplace will only replace a seaplane with another seaplane.
* Seaplanes use the normal *small plane* / *large plane* liveries. To AIs and Game Scripts (`AIEngine.GetPlaneType`) they look like normal small or large planes.

### Seaplane terminals

TGTFTD has two built-in seaplane terminals, listed in the airport window under the new **Seaplane terminals** class:

| Name | Size | Berths | Runway | Hangar | Available | Based on |
|---|---|---|---|---|---|---|
| Seaplane Dock | 4×3 | 2 | short | 1 | 1920 – forever | Country airfield |
| Seaplane Harbour | 6×6 | 3 | full length | 1 | 1935 – forever | City airport |

Building rules:

* Every tile of the terminal must be **flat open water at the same height**. Sea, canals and rivers are all allowed.
* Coast tiles, locks, ship depots, buoys, docks and land are not allowed.
* You cannot build on another company's canal.
* There must be no vehicles (e.g. ships) on the tiles and no bridge over them.
* The water class (sea, canal or river) is remembered. Demolishing the terminal puts the original water back.
* Terminals on canals count towards the owner's canal infrastructure, like docks on canals.
* Seaplane terminals **cannot be flooded**, so seaplanes standing on the water are never destroyed by the sea.
* **Ships cannot sail through a seaplane terminal**, the same as an oil rig. Leave a channel around it.
* A seaplane terminal can join a station that also has a dock, so passengers can transfer between ships and seaplanes.
* Noise, catchment, maintenance and town-authority rules are the same as for any airport.

Built-in terminal graphics: the water is drawn under the whole airport, and only the buildings (terminal, piers, hangar, tower) stand on it. Runways and taxiways are open water. Better looking terminals are what [seaplane terminal NewGRFs](#5-making-seaplane-terminals) are for.

---

## 2. Quick reference

| What | Value |
|---|---|
| Feature test name | `tgtftd_seaplanes`, version `2` (version 1 has no seaplane dock) |
| Aircraft property (mappable, feature `03`) | `aircraft_is_seaplane` — 1 byte: `0` normal plane, `1` seaplane |
| Airport property (mappable, feature `0D`) | `airport_seaplane_terminal` — 1 byte: `0` land airport, `1` seaplane terminal, `2` seaplane dock (version 2) |
| Airport class of seaplane terminals | label `SEAP`, name "Seaplane terminals" |
| Water ground sprite for airport tiles | `4061` (`0x0FDD`, `SPR_FLAT_WATER_TILE`) |
| Built-in airport IDs (game internal) | `126` Seaplane Dock, `127` Seaplane Harbour |
| Savegame feature | `tgtftd_seaplanes` (upstream JGRPP refuses to load TGTFTD saves) |

Both properties are **mappable properties**. They have no fixed Action 0 property number. You give them a number yourself with an Action 14 `A0PM` block (see [JGRPP's property mapping spec](newgrf-additions.html#property-mapping)), then use that number in Action 0. Mapped properties are always written as **`<size> <data>`**, so setting either property to 1 is written `01 01` in Action 0.

---

## 3. Detecting TGTFTD from a NewGRF

Usually you don't need a separate test. Ask the property mapping to set a bit of global variable `8D` when it succeeds, and skip your Action 0 when the bit is clear. All the examples below do this.

If you want an explicit test, use a JGRPP feature test:

```
// Set bit 6 of global variable 9D if TGTFTD seaplanes (version >= 1) are available
-1 * -1 14
	"C" "FTST"
		"T" "NAME" 00 "tgtftd_seaplanes" 00
		"B" "MINV" \w2 \w1
		"B" "SETP" \w1 06
		00
	00

// Skip the next 3 sprites if TGTFTD seaplanes are NOT available
-1 * -1  07 9D 01 \70 06 03
```

In JGR's NML fork: `if (extended_feature_test("tgtftd_seaplanes")) { ... }`.

---

## 4. Making seaplanes

A seaplane is a normal NewGRF aircraft: same sprites, callbacks, variables and properties. It also has the property `aircraft_is_seaplane` set to 1.

### 4.1 The property

| Property name | Feature | Size | Values |
|---|---|---|---|
| `aircraft_is_seaplane` | `03` (aircraft) | 1 byte | `00` = normal plane (default), `01` = seaplane |

* The vehicle must be a **plane**: property `09` (helicopter flag) must be `1`, which is the default for planes. Helicopters ignore this property.
* Properties can be set in any order.
* The **"large" flag** (property `0A`) still works: a large seaplane at a short-strip terminal can crash, just like a jet at a small airport. The *Seaplane Dock*, and NewGRF terminals based on the *Country* or *Commuter* airport, have short strips. Make big flying boats "small" if they should use those terminals safely, or build them a terminal based on a long-runway airport.
* Range (property `1F`), speed, capacity, running cost, cargo, refits and the rest are all unchanged.

### 4.2 NFO example

```
// Map "aircraft_is_seaplane" to aircraft property F0; set bit 4 of variable 8D if it worked
-1 * -1 14
	"C" "A0PM"
		"T" "NAME" 00 "aircraft_is_seaplane" 00
		"B" "FEAT" \w1 03
		"B" "PROP" \w1 F0
		"B" "SETT" \w1 04
		00
	00

// Not TGTFTD? Skip the next sprite
-1 * -1  07 8D 01 \70 04 01

// Aircraft IDs 80 and 81 are seaplanes.
// Action 0: feature 03, 1 property, 2 IDs, first ID 80, property F0, then <size> <value> per ID
-1 * -1  00 03 01 02 80  F0 01 01 01 01
```

Put this **after** the Action 0 that defines the aircraft. You can use any property number that isn't already a real aircraft property; `F0`–`FE` are safe.

### 4.3 Graphics tips

The engine draws a seaplane exactly like any other aircraft. There are no new sprites or variables to provide.

* Seaplanes taxi, take off and land on the water surface at "ground" level, using the airport's own movement paths.
* Draw floats or a boat hull and the usual 8 directions plus the shadow. Your normal aircraft sprite sets and callbacks apply.

### 4.4 Using NML

NML has no syntax for TGTFTD's property yet. The simplest workflow is to let NML write NFO and add the lines by hand:

1. Compile your NML to NFO instead of GRF:
   `nmlc --nfo=myplanes.nfo --grf=myplanes.grf myplanes.nml`
   (If your NML has graphics, keep the `--grf` output as a reference. You will rebuild the `.grf` from the NFO in step 4.)
2. Open `myplanes.nfo` and find the Action 0 sprites for your aircraft. They start with `00 03`. The NML `item(FEAT_AIRCRAFT, name, id)` number is the Action 0 ID.
3. After the last of them, paste the three sprites from [4.2](#42-nfo-example), changing the IDs to yours.
4. Run `nforenum myplanes.nfo` to fix the sprite numbers and count. Then build it with grfcodec: put the NFO in a `sprites` folder and run `grfcodec -e myplanes.grf`.

Alternatively, write the vehicle in NFO or [m4nfo](https://www.ttdpatch.de/m4nfo/), which can emit raw Action 14/Action 0 bytes directly.

### 4.5 Running without TGTFTD

With the skip shown above, a game without TGTFTD (vanilla OpenTTD or JGRPP) loads the GRF normally, but your seaplanes become **normal planes** that use land airports. If you would rather hide them there, add a fallback that clears the vehicle's climate availability (property `06` = `00`) when the mapping failed:

```
// TGTFTD present? Skip the "hide" sprite
-1 * -1  07 8D 01 \71 04 01
// Not TGTFTD: make aircraft 80-81 unavailable in all climates
-1 * -1  00 03 01 02 80  06 00 00
```

(`\71` = "skip if bit set", `\70` = "skip if bit clear".)

---

## 5. Making seaplane terminals

A seaplane terminal NewGRF is a normal NewGRF airport (feature `0D`) with its own airport tiles (feature `11`). It is set up like this:

1. **Property `08`** picks a *substitute* default airport. The substitute decides the **state machine**: where aircraft taxi, park, take off and land, where the hangars are, and how many berths there are.
2. The mappable property **`airport_seaplane_terminal` = 1** switches the airport to the **water version** of that state machine. Only seaplanes can use it, it must be built on water, and it appears in the *Seaplane terminals* class.
3. **Property `0A`** (layout) places your airport tiles over the footprint.
4. Your **airport tile** graphics draw the water and the buildings (docks, piers, terminal, hangar, buoys…).

### 5.1 Which substitute airport to use

Only airports that planes can use have a water version. Heliports (`02`, `06`, `08`) are refused.

| `08` value | Default airport | Footprint (x × y) | Hangar tile(s) | Berths | Runway | Short strip |
|---|---|---|---|---|---|---|
| `00` | Small (Country) | 4 × 3 | (3, 0) | 2 | 1, along y = 2 | **yes** |
| `01` | City | 6 × 6 | (5, 0) | 3 | 1, along y = 5 | no |
| `03` | Metropolitan | 6 × 6 | (5, 0) | 3 | 2, along y = 4 and 5 | no |
| `04` | International | 7 × 7 | (0, 3), (6, 1) | 6 | 2, along y = 0 and 6 | no |
| `05` | Commuter | 5 × 4 | (4, 0) | 3 | 1, along y = 3 | **yes** |
| `07` | Intercontinental | 9 × 11 | (0, 5), (8, 4) | 8 | 4 | no |

Coordinates are tile offsets (x, y) from the north corner, for the default rotation.

**Seaplanes need less room than land planes.** The water version of each state machine keeps all ground positions (taxiways, berths, hangars, the end of the landing run), but its flight paths are tighter:

* seaplanes touch down at 40% of the land runway's length from the end of the landing run, so the landing run on the water is short;
* the final approach starts halfway as far out;
* the holding pattern and approach fixes are pulled in to 60% of their distance from the middle of the airport.

Waiting seaplanes therefore get a landing chance much more often, and the runway is free again sooner.

Aircraft movement is fixed by the substitute's state machine, so:

* **Keep the footprint size of the substitute.** The runway(s), berths and hangar(s) are where the table says, whatever your tiles look like.
* **Put a hangar-looking tile on each hangar position.** The hangar is defined by its position, not by the tile graphics. Clicking that tile opens the hangar window.
* Draw your berths, piers and buildings so they match where the substitute parks its aircraft. Easiest: open the default airport's layout (`src/table/airport_defaults.h` in the TGTFTD source) and redraw it in a nautical style.
* The helipads of International, Commuter and Intercontinental are never used, because helicopters can't use seaplane terminals. Draw open water there.
* Rotated layouts (the rotation byte of property `0A`) work as for land airports.

### 5.2 The property

| Property name | Feature | Size | Values |
|---|---|---|---|
| `airport_seaplane_terminal` | `0D` (airports) | 1 byte | `00` = land airport (default), `01` = seaplane terminal, `02` = seaplane dock (see [5.6](#56-seaplane-docks-1-2)) |

* It must come **after property `08`**, in the same or a later Action 0, because it converts the state machine chosen by `08`.
* Setting it to `01` also moves the airport into the *Seaplane terminals* class. Setting it back to `00` restores the substitute's land state machine and class.
* With a heliport substitute the property is ignored, and a warning is logged at `grf` debug level 2.
* `02` ignores the substitute's state machine and hangars and uses the seaplane dock described in [5.6](#56-seaplane-docks-1-2).

### 5.3 Drawing airport tiles on water

Each tile of a seaplane terminal stands on water, and the game remembers whether it is sea, canal or river.

**Default airport tiles** (tile IDs `00`–`49` used directly in your layout) are drawn with **water instead of their ground sprite**, plus their building sprites if they have any. Default tiles whose picture is only a ground sprite (runway, apron, taxiway, grass) appear as plain water.

**Your own airport tiles** (feature `11`) control the ground sprite themselves. In the tile's sprite layout (Action 2), set the ground sprite to:

| Ground sprite | Result |
|---|---|
| `4061` (`0x0FDD`, `SPR_FLAT_WATER_TILE`) | **Recommended.** The game draws the real water of that tile: sea, canal or river, with the player's water graphics, animation and canal edges. |
| `0` | Nothing. Don't use this, it leaves a hole in the map. |
| any other sprite | Drawn as-is. Use for a solid deck or pontoon covering the whole tile. The tile is still water underneath and turns back into water when demolished. |

Then draw piers, pontoons, buildings, buoys, runway markers and so on as building sprites, exactly as for a land airport tile. All airport tile variables, animation and callbacks work as normal.

An Action 2 sprite layout with a water ground sprite looks like this (feature `11`, one building sprite from set `00`):

```
// Airport tile sprite layout: ground = real water (0FDD), one pier/building sprite on top
-1 * -1  02 11 10  01
	\dxFDD                                // ground sprite: 0x0FDD = 4061 = SPR_FLAT_WATER_TILE
	\dx80000000  00 00 00  10 10 08       // building: sprite 0 of the Action 1 set (bit 31 = use GRF sprite), offsets and bounding box
```

(This is the basic Action 2 tile-layout format used by industry and airport tiles. See the [NewGRF Action 2 house/industry/airport tile specification](https://newgrf-specs.tt-wiki.net/wiki/Action2/Houses_and_Industry_Tiles) for the full syntax.)

### 5.4 Complete NFO example

This is the airport part of the example GRF in [`docs/tgtftd/examples/seaplane_test.nfo`](tgtftd/examples/seaplane_test.nfo). It makes a seaplane terminal from the Commuter airport and keeps the Commuter tile layout. A real GRF would add its own property `0A` layout and feature `11` tiles.

```
// Map "airport_seaplane_terminal" to airport property F1; set bit 5 of variable 8D if it worked
-1 * -1 14
	"C" "A0PM"
		"T" "NAME" 00 "airport_seaplane_terminal" 00
		"B" "FEAT" \w1 0D
		"B" "PROP" \w1 F1
		"B" "SETT" \w1 05
		00
	00

// Airport name: text DC00
-1 * -1  04 0D FF 01 \wDC00 "Test Seaplane Base" 00

// Not TGTFTD? Skip the airport
-1 * -1  07 8D 01 \70 05 01

// Action 0, airports, 4 properties, 1 airport, local ID 00
//   08 05           substitute: Commuter
//   F1 01 01        airport_seaplane_terminal = 1  (<size 01> <value 01>)
//   0C ...          available 1920 - forever
//   10 \wDC00       name
-1 * -1  00 0D 04 01 00  08 05  F1 01 01  0C \w1920 \wFFFF  10 \wDC00
```

Notes:

* **Skip the airport when the mapping fails.** Otherwise, on vanilla OpenTTD or JGRPP it becomes a normal *land* airport that uses your water graphics.
* Property `08` must be the first property set for a new airport ID, as for any NewGRF airport.
* All other airport properties work as usual: `0A` layouts, `0C` years, `0E` catchment, `0F` noise, `10` name, `11` maintenance, `12` badges, plus airport callbacks and variables.

### 5.5 Using NML

**NML does not support airports or airport tiles at all**, in standard NML or JGR's fork. Seaplane terminal GRFs, like all airport GRFs, must be written in NFO or a tool that produces NFO, such as [m4nfo](https://www.ttdpatch.de/m4nfo/), CETS or a custom script. The example generator [`make_seaplane_test_grf.py`](tgtftd/examples/make_seaplane_test_grf.py) shows how little is needed to build a GRF from Python.


### 5.6 Seaplane docks (1 × 2)

`airport_seaplane_terminal` = **`02`** (feature version 2) makes the airport a **seaplane dock**: a tiny terminal with **one berth and no hangar**, for a jetty or a small floating dock.

* **Footprint: 1 × 2 tiles** (x = 1, y = 2 in the default rotation). Give property `0A` a layout of exactly these two tiles. Rotated layouts work as usual.
* Property `08` still has to come first (any plane airport, e.g. `00`), but its state machine and hangars are replaced by the dock's. Set `airport_seaplane_terminal` = `02` **after** `08`.
* It is listed in the *Seaplane terminals* class and has the same building rules as other seaplane terminals (flat open water only, no ships through it).
* **No hangar**: seaplanes cannot be bought or serviced at a dock. A seaplane that needs servicing flies to the nearest seaplane terminal with a hangar.
* It is a **short strip**: large seaplanes may crash, as at the *Seaplane Dock* built-in terminal.

Positions, in world units (16 per tile) from the north corner, default rotation:

| What | Position | Notes |
|---|---|---|
| Berth | (10, 16) | Aircraft faces north-west, beside a dock drawn along the north-east edge (x = 0–5) |
| Water lane | x = 24, from y = 44 to y = 0 | **Outside the footprint**, in the water next to the dock. Seaplanes come in on a short final from about (24, 98), touch down at (24, 19) heading north-west, stop at (24, 0), turn round and taxi to the berth; they take off from (24, 44) heading north-west |

* A seaplane only lands when the berth is free; otherwise it circles.
* The water lane is not part of the station, so leave open water on the south-west side of the dock (towards +x) when you build it, the same way you would leave room for any landing aircraft.
* Draw the dock on the north-east half of the footprint (low x) and open water on the rest: the berthed aircraft floats at x = 10, with its wings over the dock.

An NFO Action 0 for a dock (local ID `02`, uses mapped property `F1`, name text `DC02`, layout of two of your tiles `00` and `01`):

```
-1 * -1  00 0D 05 01 02
	08 00                                  // substitute: any plane airport (Country)
	F1 01 02                               // airport_seaplane_terminal = 2: seaplane dock
	0A 01 \d13  00  00 00 FE \w0000  00 01 FE \w0001  00 80
	                                       // 1 layout, rotation north, tiles (0,0) and (0,1), terminator 00 80
	0C \w1950 \wFFFF                       // available 1950 - forever
	10 \wDC02                              // name
```

**Check the feature version** before using `02`: on version 1 the value is read as "seaplane terminal" and gives a broken airport. Test with `"B" "MINV" \w2 \w2` in the feature test and skip the dock when the bit is clear (see [section 3](#3-detecting-tgtftd-from-a-newgrf)).

---

## 6. Testing and debugging

* Build the example GRF: `python docs/tgtftd/examples/make_seaplane_test_grf.py`. Copy `seaplane_test.grf` into your `newgrf` folder and enable it in a new game. It turns the Sampson U52, Coleman Count and Bakewell Cotswald LB-3 into seaplanes, and adds a *Test Seaplane Base* next to the built-in Seaplane Dock and Seaplane Harbour.
* Open the console (`` ` `` key) and type `debug_level grf=2` before loading a game. The console then shows messages such as *"Ignoring use of mapped property … with incorrect data size"* (you forgot the `<size>` byte) and *"… has no seaplane terminal variant"* (you used a heliport substitute).
* With *Settings → NewGRF developer tools* enabled, the NewGRF inspect window works for seaplanes, seaplane terminals and their tiles, as for any airport.
* Quick in-game check:
  1. Build a terminal on the sea and one on a canal.
  2. Buy a seaplane in the terminal's hangar and give it orders between the two.
  3. Try to give it an order to a land airport: this must be refused.
  4. Demolish a terminal: the sea or canal must come back.

---

## 7. Compatibility notes

* **Savegames**: games saved by TGTFTD carry the `tgtftd_seaplanes` savegame feature, so other builds refuse to load them instead of loading them wrongly. TGTFTD loads JGRPP and OpenTTD savegames normally.
* **Multiplayer**: all players must run the same TGTFTD build, as with any patch pack.
* **NewGRF airport slots**: the two built-in seaplane terminals use the last two of the 128 airport slots, which leaves 116 slots for NewGRF airports (JGRPP has 118).
* **Upstream JGRPP / OpenTTD**: neither mappable property exists there. With the skips shown above, your GRF still loads; seaplanes become normal planes and seaplane terminals are skipped.
* Property names and numbers here are **version 2** of `tgtftd_seaplanes`. Version 2 adds the seaplane dock (`airport_seaplane_terminal` = `02`); everything from version 1 is unchanged. Any incompatible change will bump the feature version.
