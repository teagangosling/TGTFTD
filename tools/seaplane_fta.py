#!/usr/bin/env python3
"""
Seaplane terminal state machines for TGTFTD: generator and simulator.

Seaplanes land and stop in a short distance, so every runway of a seaplane terminal is split in two:

    approach ->  [ LANDING HALF  | hold short | DEPARTURE HALF ]  -> climb out
                 touch down, stop           line up, take off

Each half has its own block, so one seaplane can land while another takes off on the same runway (like a
"land and hold short" operation). Two-runway airports therefore work like four-runway airports.
Berths, hangars and terminal groups are where the land airports have them, so NewGRF terminal graphics
made for the land layouts still fit. The intercontinental airport keeps the land state machine.

    python tools/seaplane_fta.py            # write src/table/seaplane_movement.h
    python tools/seaplane_fta.py --check    # simulate every airport and report

The simulator re-implements the parts of aircraft_cmd.cpp that drive airport movement (AirportMove,
AirportSetBlocks, AirportHasBlock, AirportClearBlock, terminal selection and the state handlers), so the
tables can be checked for deadlocks and simultaneous use without running the game.
"""

import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "table" / "seaplane_movement.h"

# Movement states / headings (airport.h AirportMovementStates).
STATES = ["TO_ALL", "HANGAR", "TERM1", "TERM2", "TERM3", "TERM4", "TERM5", "TERM6", "HELIPAD1", "HELIPAD2",
          "TAKEOFF", "STARTTAKEOFF", "ENDTAKEOFF", "HELITAKEOFF", "FLYING", "LANDING", "ENDLANDING",
          "HELILANDING", "HELIENDLANDING", "TERM7", "TERM8", "HELIPAD3"]
TERMGROUP = "TERMGROUP"
TERMINALS = ["TERM1", "TERM2", "TERM3", "TERM4", "TERM5", "TERM6", "TERM7", "TERM8"]
TERM_BLOCK = {t: "Term%d" % (i + 1) for i, t in enumerate(TERMINALS)}

# Seaplane blocks (added to AirportBlock in airport.h).
NEW_BLOCKS = {
    "SeaRunway1Land": 32, "SeaRunway1Depart": 33, "SeaRunway1Exit": 34,
    "SeaRunway2Land": 35, "SeaRunway2Depart": 36, "SeaRunway2Exit": 37,
    "SeaHold1": 38, "SeaHold2": 39, "SeaHold3": 40,
    "SeaTaxi1": 41, "SeaTaxi2": 42, "SeaTaxi3": 43, "SeaTaxi4": 44,
    "SeaTaxi5": 45, "SeaTaxi6": 46, "SeaTaxi7": 47, "SeaTaxi8": 48,
    "SeaTaxi9": 49, "SeaTaxi10": 50, "SeaHold4": 51,
}
NOTHING = "Nothing"

AIR = ("NoSpeedClamp", "SlowTurn")
LAND = ("NoSpeedClamp", "Land")
BRAKE = ("NoSpeedClamp", "Brake")
ROLL = ("NoSpeedClamp",)
LIFT = ("NoSpeedClamp", "Takeoff")
EXACT = ("ExactPosition",)


@dataclass
class Airport:
    name: str           # C++ suffix: _airport_moving_data_seaplane_<name>
    title: str
    terminals: list     # {groups, n1, n2, ...}
    entries: list       # entry points for arriving from NE, SE, SW, NW
    positions: list = field(default_factory=list)  # (x, y, flags, direction, comment)
    fta: list = field(default_factory=list)        # (position, heading, blocks, next)
    has_hangar: bool = True
    depots: list = field(default_factory=list)     # own hangar table: ((tile x, tile y), exit direction)

    def pos(self, x, y, flags=(), direction="N", comment=""):
        self.positions.append((x, y, tuple(flags), direction, comment))
        return len(self.positions) - 1

    def on(self, position, heading, blocks, nxt):
        if isinstance(blocks, str):
            blocks = (blocks,) if blocks else ()
        self.fta.append((position, heading, tuple(blocks), nxt))


# ---------------------------------------------------------------------------------------------- airports


def hangars_first(a: Airport, hangars: list) -> Airport:
    """
    Renumber the positions so the hangars come first, in hangar order: OpenTTD finds the position of hangar n as
    position n of the state machine (GetVehiclePosOnBuild).
    """
    order = list(hangars) + [i for i in range(len(a.positions)) if i not in hangars]
    new_index = {old: new for new, old in enumerate(order)}
    a.positions = [a.positions[old] for old in order]
    a.fta = sorted(((new_index[p], h, b, nxt if h == TERMGROUP else new_index[nxt]) for p, h, b, nxt in a.fta),
                   key=lambda e: e[0])
    a.entries = [new_index[e] for e in a.entries]
    return a


def country() -> Airport:
    """Country airfield (4x3): two berths, one hangar, one runway along y = 40 split at x = 32."""
    a = Airport("country", "Seaplane version of the country airfield", [1, 2], [14, 13, 16, 15])
    a.pos(53, 3, EXACT, "SE", "In hangar")
    a.pos(53, 27, (), "N", "Outside the hangar")
    a.pos(32, 23, EXACT, "NW", "Berth 1")
    a.pos(10, 23, EXACT, "NW", "Berth 2")
    a.pos(32, 31, (), "N", "In front of berth 1")
    a.pos(10, 31, (), "N", "In front of berth 2")
    a.pos(26, 40, EXACT, "NE", "Line up: start of the departure half")
    a.pos(3, 40, ROLL, "N", "End of the departure run")
    a.pos(-60, 40, LIFT, "N", "Take off")
    a.pos(110, 40, AIR, "N", "Final approach fix")
    a.pos(60, 40, LAND, "N", "Touch down at the start of the landing half")
    a.pos(40, 40, BRAKE, "N", "Stop, holding short of the departure half")
    a.pos(46, 32, (), "N", "Leave the landing half")
    a.pos(14, 124, AIR, "N", "Holding (north-east)")
    a.pos(14, 9, AIR, "N", "Holding (north-west)")
    a.pos(167, 9, AIR, "N", "Holding (south-west)")
    a.pos(176, 36, AIR, "N", "Holding (south)")

    T = "SeaTaxi1"
    a.on(0, "HANGAR", NOTHING, 1)
    a.on(1, TERMGROUP, T, 0); a.on(1, "HANGAR", (), 0); a.on(1, "TO_ALL", (), 4)
    a.on(2, "TERM1", "Term1", 4)
    a.on(3, "TERM2", "Term2", 5)
    a.on(4, TERMGROUP, T, 0); a.on(4, "TERM1", "Term1", 2); a.on(4, "TERM2", (), 5); a.on(4, "HANGAR", (), 1)
    a.on(4, "TAKEOFF", (), 6); a.on(4, "TO_ALL", (), 1)
    a.on(5, TERMGROUP, T, 0); a.on(5, "TERM2", "Term2", 3); a.on(5, "TO_ALL", (), 4)
    a.on(6, "TAKEOFF", "SeaRunway1Depart", 7)
    a.on(7, "STARTTAKEOFF", "SeaRunway1Depart", 8)
    a.on(8, "ENDTAKEOFF", NOTHING, 0)
    a.on(9, "FLYING", NOTHING, 13); a.on(9, "LANDING", "SeaRunway1Exit", 10)
    a.on(10, "LANDING", "SeaRunway1Land", 11)
    a.on(11, "TO_ALL", "SeaRunway1Land", 12)
    a.on(12, "ENDLANDING", "SeaRunway1Exit", 1); a.on(12, "TO_ALL", (), 1)
    a.on(13, "TO_ALL", NOTHING, 14)
    a.on(14, "TO_ALL", NOTHING, 15)
    a.on(15, "TO_ALL", NOTHING, 16)
    a.on(16, "TO_ALL", NOTHING, 9)
    return a


def commuter() -> Airport:
    """
    Commuter airfield (5x4): three berths facing the runway, one hangar, one runway along y = 54 split at x = 40.
    Departures taxi down the clear west column and back-taxi on the departure half; landed seaplanes leave the
    landing half towards the clear east column.
    """
    a = Airport("commuter", "Seaplane version of the commuter airfield", [1, 3], [19, 18, 21, 20])
    a.pos(69, 3, EXACT, "SE", "In hangar")
    a.pos(72, 22, (), "N", "Outside the hangar")
    a.pos(8, 22, (), "N", "West end of the taxi lane")
    a.pos(24, 36, EXACT, "SE", "Berth 1")
    a.pos(40, 36, EXACT, "SE", "Berth 2")
    a.pos(56, 36, EXACT, "SE", "Berth 3")
    a.pos(24, 22, (), "N", "Taxi lane at berth 1")
    a.pos(40, 22, (), "N", "Taxi lane at berth 2")
    a.pos(56, 22, (), "N", "Taxi lane at berth 3")
    a.pos(8, 40, (), "N", "Holding point in the west column")
    a.pos(8, 54, (), "N", "Enter the departure half")
    a.pos(36, 54, EXACT, "NE", "Line up: start of the departure half")
    a.pos(5, 54, ROLL, "N", "End of the departure run")
    a.pos(-60, 54, LIFT, "N", "Take off")
    a.pos(130, 54, AIR, "N", "Final approach fix")
    a.pos(76, 54, LAND, "N", "Touch down at the start of the landing half")
    a.pos(46, 54, BRAKE, "N", "Stop, holding short of the departure half")
    a.pos(72, 46, (), "N", "Leave the landing half to the east column")
    a.pos(16, 100, AIR, "N", "Holding (north-east)")
    a.pos(16, 15, AIR, "N", "Holding (north-west)")
    a.pos(130, 15, AIR, "N", "Holding (south-west)")
    a.pos(150, 48, AIR, "N", "Holding (south)")

    T = "SeaTaxi1"
    a.on(0, "HANGAR", NOTHING, 1)
    a.on(1, TERMGROUP, T, 0); a.on(1, "HANGAR", (), 0); a.on(1, "TO_ALL", (), 8)
    a.on(2, TERMGROUP, T, 0); a.on(2, "TAKEOFF", (), 9); a.on(2, "TO_ALL", (), 6)
    a.on(3, "TERM1", "Term1", 6)
    a.on(4, "TERM2", "Term2", 7)
    a.on(5, "TERM3", "Term3", 8)
    a.on(6, TERMGROUP, T, 0); a.on(6, "TERM1", "Term1", 3); a.on(6, "TAKEOFF", (), 2); a.on(6, "TO_ALL", (), 7)
    a.on(7, TERMGROUP, T, 0); a.on(7, "TERM2", "Term2", 4); a.on(7, "TERM1", (), 6); a.on(7, "TAKEOFF", (), 6)
    a.on(7, "TO_ALL", (), 8)
    a.on(8, TERMGROUP, T, 0); a.on(8, "TERM3", "Term3", 5); a.on(8, "HANGAR", (), 1); a.on(8, "TO_ALL", (), 7)
    a.on(9, "TO_ALL", "SeaHold1", 10)
    a.on(10, "TO_ALL", "SeaRunway1Depart", 11)
    a.on(11, "TAKEOFF", "SeaRunway1Depart", 12)
    a.on(12, "STARTTAKEOFF", "SeaRunway1Depart", 13)
    a.on(13, "ENDTAKEOFF", NOTHING, 0)
    a.on(14, "FLYING", NOTHING, 18); a.on(14, "LANDING", "SeaRunway1Exit", 15)
    a.on(15, "LANDING", "SeaRunway1Land", 16)
    a.on(16, "TO_ALL", "SeaRunway1Land", 17)
    a.on(17, "ENDLANDING", "SeaRunway1Exit", 1); a.on(17, "TO_ALL", (), 1)
    a.on(18, "TO_ALL", NOTHING, 19)
    a.on(19, "TO_ALL", NOTHING, 20)
    a.on(20, "TO_ALL", NOTHING, 21)
    a.on(21, "TO_ALL", NOTHING, 14)
    return a


def _city_terminals(a: Airport, center_y: int):
    """Hangar, berths and taxiways shared by the city and metropolitan layouts (positions 0-7)."""
    a.pos(85, 3, EXACT, "SE", "In hangar")
    a.pos(85, 22, (), "N", "Outside the hangar")
    a.pos(26, 41, EXACT, "SW", "Berth 1")
    a.pos(56, 22, EXACT, "SE", "Berth 2")
    a.pos(38, 8, EXACT, "SW", "Berth 3")
    a.pos(65, 6, (), "N", "In front of berths 2 and 3")
    a.pos(80, 27, (), "N", "Taxiway to berths 2 and 3")
    a.pos(50, center_y, (), "N", "Middle of the harbour")


def city() -> Airport:
    """City airport (6x6): three berths, one hangar, one runway along y = 86 split at x = 48."""
    a = Airport("city", "Seaplane version of the city airport", [1, 3], [17, 16, 19, 18])
    _city_terminals(a, 62)
    a.pos(40, 74, (), "N", "Holding point before the departure half")
    a.pos(42, 86, EXACT, "NE", "Line up: start of the departure half")
    a.pos(3, 86, ROLL, "N", "End of the departure run")
    a.pos(-60, 86, LIFT, "N", "Take off")
    a.pos(140, 86, AIR, "N", "Final approach fix")
    a.pos(90, 86, LAND, "N", "Touch down at the start of the landing half")
    a.pos(56, 86, BRAKE, "N", "Stop, holding short of the departure half")
    a.pos(64, 73, (), "N", "Leave the landing half")
    a.pos(14, 140, AIR, "N", "Holding (north-east)")
    a.pos(14, 10, AIR, "N", "Holding (north-west)")
    a.pos(170, 10, AIR, "N", "Holding (south-west)")
    a.pos(180, 60, AIR, "N", "Holding (south)")

    T = "SeaTaxi1"
    _city_taxi(a, T, takeoff_t1=8)
    a.on(8, "TO_ALL", "SeaHold1", 9)
    a.on(9, "TAKEOFF", "SeaRunway1Depart", 10)
    a.on(10, "STARTTAKEOFF", "SeaRunway1Depart", 11)
    a.on(11, "ENDTAKEOFF", NOTHING, 0)
    a.on(12, "FLYING", NOTHING, 16); a.on(12, "LANDING", "SeaRunway1Exit", 13)
    a.on(13, "LANDING", "SeaRunway1Land", 14)
    a.on(14, "TO_ALL", "SeaRunway1Land", 15)
    a.on(15, "ENDLANDING", "SeaRunway1Exit", 7); a.on(15, "TO_ALL", (), 7)
    a.on(16, "TO_ALL", NOTHING, 17)
    a.on(17, "TO_ALL", NOTHING, 18)
    a.on(18, "TO_ALL", NOTHING, 19)
    a.on(19, "TO_ALL", NOTHING, 12)
    return a


def _city_taxi(a: Airport, T: str, takeoff_t1: int, takeoff_center: int | None = None):
    """Taxi graph between hangar, berths and the middle (positions 0-7), as on the land city airport."""
    a.on(0, "HANGAR", NOTHING, 1)
    a.on(1, TERMGROUP, T, 0); a.on(1, "HANGAR", (), 0); a.on(1, "TERM2", (), 6); a.on(1, "TERM3", (), 6)
    a.on(1, "TO_ALL", (), 7)
    if takeoff_t1 == 8:
        a.on(2, "TERM1", "Term1", 7)
    else:
        a.on(2, "TERM1", "Term1", 7); a.on(2, "TAKEOFF", (), takeoff_t1); a.on(2, "TO_ALL", (), 7)
    a.on(3, "TERM2", "Term2", 6)
    a.on(4, "TERM3", "Term3", 5)
    a.on(5, TERMGROUP, T, 0); a.on(5, "TERM2", "Term2", 3); a.on(5, "TERM3", "Term3", 4); a.on(5, "TO_ALL", (), 6)
    a.on(6, TERMGROUP, T, 0); a.on(6, "TERM2", "Term2", 3); a.on(6, "TERM3", (), 5); a.on(6, "HANGAR", (), 1)
    a.on(6, "TO_ALL", (), 7)
    a.on(7, TERMGROUP, T, 0); a.on(7, "TERM1", "Term1", 2); a.on(7, "TAKEOFF", (), takeoff_center or 8)
    a.on(7, "HANGAR", (), 1); a.on(7, "TO_ALL", (), 6)


def metropolitan() -> Airport:
    """
    Metropolitan airport (6x6): the city berths with two runways, both split in a landing and a departure half,
    so four seaplanes can use the runways at once.
    Runway 1 is along y = 85, runway 2 along y = 69; both are landed towards the north-east (from x = 96).
    Seaplanes from berth 1 take off from runway 1 (crossing the departure half of runway 2), the others from
    runway 2. Seaplanes landed on runway 1 cross the landing half of runway 2 to the middle of the harbour.
    """
    a = Airport("metropolitan", "Seaplane version of the metropolitan airport", [1, 3], [29, 28, 31, 30])
    _city_terminals(a, 54)
    # Runway 2 departures (positions 8-11).
    a.pos(40, 61, (), "N", "Holding point before the departure half of runway 2")
    a.pos(42, 69, EXACT, "NE", "Line up on runway 2")
    a.pos(3, 69, ROLL, "N", "End of the departure run on runway 2")
    a.pos(-60, 69, LIFT, "N", "Take off from runway 2")
    # Runway 1 departures from berth 1 (positions 12-17).
    a.pos(26, 58, (), "N", "Holding point before crossing runway 2")
    a.pos(26, 70, (), "N", "Crossing the departure half of runway 2")
    a.pos(30, 78, (), "N", "Holding point before the departure half of runway 1")
    a.pos(42, 85, EXACT, "NE", "Line up on runway 1")
    a.pos(3, 85, ROLL, "N", "End of the departure run on runway 1")
    a.pos(-60, 85, LIFT, "N", "Take off from runway 1")
    # Landing (positions 18-27).
    a.pos(150, 77, AIR, "N", "Final approach: choose a free landing half")
    a.pos(128, 85, AIR, "N", "Final approach to runway 1")
    a.pos(90, 85, LAND, "N", "Touch down on runway 1")
    a.pos(56, 85, BRAKE, "N", "Stop on runway 1, holding short of its departure half")
    a.pos(62, 78, (), "N", "Leave runway 1")
    a.pos(64, 69, (), "N", "Crossing the landing half of runway 2")
    a.pos(128, 69, AIR, "N", "Final approach to runway 2")
    a.pos(90, 69, LAND, "N", "Touch down on runway 2")
    a.pos(56, 69, BRAKE, "N", "Stop on runway 2, holding short of its departure half")
    a.pos(60, 61, (), "N", "Leave runway 2")
    # Holding (positions 28-31).
    a.pos(14, 140, AIR, "N", "Holding (north-east)")
    a.pos(14, 10, AIR, "N", "Holding (north-west)")
    a.pos(170, 10, AIR, "N", "Holding (south-west)")
    a.pos(180, 50, AIR, "N", "Holding (south)")
    a.pos(66, 60, (), "N", "Wait north of runway 2 after crossing it")   # 32

    _city_taxi(a, "SeaTaxi1", takeoff_t1=12)
    a.on(8, "TO_ALL", "SeaHold1", 9)
    a.on(9, "TAKEOFF", "SeaRunway2Depart", 10)
    a.on(10, "STARTTAKEOFF", "SeaRunway2Depart", 11)
    a.on(11, "ENDTAKEOFF", NOTHING, 0)
    a.on(12, "TO_ALL", "SeaHold2", 13)
    a.on(13, "TO_ALL", "SeaRunway2Depart", 14)
    a.on(14, "TO_ALL", "SeaHold3", 15)
    a.on(15, "TAKEOFF", "SeaRunway1Depart", 16)
    a.on(16, "STARTTAKEOFF", "SeaRunway1Depart", 17)
    a.on(17, "ENDTAKEOFF", NOTHING, 0)
    a.on(18, "FLYING", NOTHING, 28)
    a.on(18, "LANDING", "SeaRunway1Exit", 19)
    a.on(18, "LANDING", "SeaRunway2Exit", 24)
    a.on(19, "TO_ALL", "SeaRunway1Land", 20)
    a.on(20, "LANDING", "SeaRunway1Land", 21)
    a.on(21, "TO_ALL", "SeaRunway1Land", 22)
    a.on(22, "ENDLANDING", "SeaRunway1Exit", 23); a.on(22, "TO_ALL", (), 23)
    a.on(23, "TO_ALL", "SeaRunway2Land", 32)
    a.on(24, "TO_ALL", "SeaRunway2Land", 25)
    a.on(25, "LANDING", "SeaRunway2Land", 26)
    a.on(26, "TO_ALL", "SeaRunway2Land", 27)
    a.on(27, "ENDLANDING", "SeaRunway2Exit", 7); a.on(27, "TO_ALL", (), 7)
    a.on(28, "TO_ALL", NOTHING, 29)
    a.on(29, "TO_ALL", NOTHING, 30)
    a.on(30, "TO_ALL", NOTHING, 31)
    a.on(31, "TO_ALL", NOTHING, 18)
    a.on(32, "TO_ALL", "SeaTaxi2", 7)
    return a


def international() -> Airport:
    """
    International airport (7x7): six berths in two groups either side of a central pier, two hangars, and two
    runways, both split in a landing and a departure half.
    Runway 1 (y = 104) is landed towards the north-east (from x = 112), runway 2 (y = 6) towards the south-west
    (from x = 0). The holding pattern passes both final approach fixes. Seaplanes at the west berths and hangar 1
    take off from runway 1, the others from runway 2.
    """
    a = Airport("international", "Seaplane version of the international airport", [2, 3, 3], [39, 38, 41, 40])
    a.pos(7, 55, EXACT, "SE", "In hangar 1")                       # 0
    a.pos(100, 21, EXACT, "SE", "In hangar 2")                     # 1
    a.pos(7, 70, (), "N", "Outside hangar 1")                      # 2
    a.pos(100, 36, (), "N", "Outside hangar 2")                    # 3
    a.pos(38, 70, EXACT, "SW", "Berth 1")                          # 4
    a.pos(38, 54, EXACT, "SW", "Berth 2")                          # 5
    a.pos(38, 38, EXACT, "SW", "Berth 3")                          # 6
    a.pos(70, 70, EXACT, "NE", "Berth 4")                          # 7
    a.pos(70, 54, EXACT, "NE", "Berth 5")                          # 8
    a.pos(70, 38, EXACT, "NE", "Berth 6")                          # 9
    a.pos(22, 87, (), "N", "South-west corner of the taxiways")    # 10
    a.pos(60, 87, (), "N", "South taxiway")                        # 11
    a.pos(86, 87, (), "N", "South-east corner of the taxiways")    # 12
    a.pos(86, 70, (), "N", "In front of berth 4")                  # 13
    a.pos(86, 54, (), "N", "In front of berth 5")                  # 14
    a.pos(86, 38, (), "N", "In front of berth 6")                  # 15
    a.pos(86, 22, (), "N", "North-east corner of the taxiways")    # 16
    a.pos(60, 22, (), "N", "North taxiway")                        # 17
    a.pos(22, 22, (), "N", "North-west corner of the taxiways")    # 18
    a.pos(22, 70, (), "N", "In front of berth 1")                  # 19
    a.pos(22, 54, (), "N", "In front of berth 2")                  # 20
    a.pos(22, 38, (), "N", "In front of berth 3")                  # 21
    # Runway 2 (y = 6), landed towards the south-west.
    a.pos(-50, 6, AIR, "N", "Final approach fix, runway 2")        # 22
    a.pos(6, 6, LAND, "N", "Touch down on runway 2")               # 23
    a.pos(40, 6, BRAKE, "N", "Stop on runway 2, holding short of its departure half")  # 24
    a.pos(34, 16, (), "N", "Leave runway 2")                       # 25
    a.pos(78, 14, (), "N", "Holding point before the departure half of runway 2")    # 26
    a.pos(64, 6, EXACT, "SW", "Line up on runway 2")               # 27
    a.pos(109, 6, ROLL, "N", "End of the departure run on runway 2")  # 28
    a.pos(170, 6, LIFT, "N", "Take off from runway 2")             # 29
    # Runway 1 (y = 104), landed towards the north-east.
    a.pos(170, 104, AIR, "N", "Final approach fix, runway 1")      # 30
    a.pos(106, 104, LAND, "N", "Touch down on runway 1")           # 31
    a.pos(72, 104, BRAKE, "N", "Stop on runway 1, holding short of its departure half")  # 32
    a.pos(78, 94, (), "N", "Leave runway 1")                       # 33
    a.pos(36, 94, (), "N", "Holding point before the departure half of runway 1")    # 34
    a.pos(48, 104, EXACT, "NE", "Line up on runway 1")             # 35
    a.pos(3, 104, ROLL, "N", "End of the departure run on runway 1")  # 36
    a.pos(-60, 104, LIFT, "N", "Take off from runway 1")           # 37
    # Holding pattern through both final approach fixes.
    a.pos(60, 170, AIR, "N", "Holding (south-east)")               # 38
    a.pos(-50, 110, AIR, "N", "Holding (north-east)")              # 39
    a.pos(60, -60, AIR, "N", "Holding (north-west)")               # 40
    a.pos(170, -20, AIR, "N", "Holding (south-west)")              # 41

    G1, G2 = 0, 1  # TERMGROUP next_position = group index
    # One-way taxi loop around the pier (one block, so it cannot jam):
    # 10 -> 11 -> 12 -> 13 -> 14 -> 15 -> 16 -> 17 -> 18 -> 21 -> 20 -> 19 -> 10, with the hangar exits 2 and 3 on it.
    R = "SeaTaxi1"
    a.on(0, "HANGAR", NOTHING, 2); a.on(0, TERMGROUP, NOTHING, G1); a.on(0, TERMGROUP, NOTHING, G2); a.on(0, "TO_ALL", (), 2)
    a.on(1, "HANGAR", NOTHING, 3); a.on(1, TERMGROUP, NOTHING, G2); a.on(1, TERMGROUP, NOTHING, G1); a.on(1, "TO_ALL", (), 3)
    a.on(2, TERMGROUP, R, 0); a.on(2, "HANGAR", (), 0); a.on(2, "TO_ALL", (), 19)
    a.on(3, TERMGROUP, R, 0); a.on(3, "HANGAR", (), 1); a.on(3, "TO_ALL", (), 15)
    a.on(4, "TERM1", "Term1", 19)
    a.on(5, "TERM2", "Term2", 20)
    a.on(6, "TERM3", "Term3", 21)
    a.on(7, "TERM4", "Term4", 13)
    a.on(8, "TERM5", "Term5", 14)
    a.on(9, "TERM6", "Term6", 15)
    a.on(10, TERMGROUP, R, 0); a.on(10, "TAKEOFF", (), 34); a.on(10, "TO_ALL", (), 11)   # west berths: runway 1
    a.on(11, TERMGROUP, R, 0); a.on(11, "TO_ALL", (), 12)
    a.on(12, TERMGROUP, R, 0); a.on(12, "TO_ALL", (), 13)
    a.on(13, TERMGROUP, R, 0); a.on(13, "TERM4", "Term4", 7); a.on(13, "TO_ALL", (), 14)
    a.on(14, TERMGROUP, R, 0); a.on(14, "TERM5", "Term5", 8); a.on(14, "TO_ALL", (), 15)
    a.on(15, TERMGROUP, R, 0); a.on(15, "TERM6", "Term6", 9); a.on(15, "HANGAR", (), 3); a.on(15, "TO_ALL", (), 16)
    a.on(16, TERMGROUP, R, 0); a.on(16, "TAKEOFF", (), 26); a.on(16, "TO_ALL", (), 17)   # east berths: runway 2
    a.on(17, TERMGROUP, R, 0); a.on(17, "TO_ALL", (), 18)
    a.on(18, TERMGROUP, R, 0); a.on(18, "TO_ALL", (), 21)
    a.on(19, TERMGROUP, R, 0); a.on(19, "TERM1", "Term1", 4); a.on(19, "HANGAR", (), 2); a.on(19, "TO_ALL", (), 10)
    a.on(20, TERMGROUP, R, 0); a.on(20, "TERM2", "Term2", 5); a.on(20, "TO_ALL", (), 19)
    a.on(21, TERMGROUP, R, 0); a.on(21, "TERM3", "Term3", 6); a.on(21, "TO_ALL", (), 20)
    # Runway 2.
    a.on(22, "FLYING", NOTHING, 40); a.on(22, "LANDING", "SeaRunway2Exit", 23)
    a.on(23, "LANDING", "SeaRunway2Land", 24)
    a.on(24, "TO_ALL", "SeaRunway2Land", 25)
    a.on(25, "ENDLANDING", "SeaRunway2Exit", 18); a.on(25, TERMGROUP, NOTHING, G1); a.on(25, TERMGROUP, NOTHING, G2)
    a.on(25, "TO_ALL", (), 18)
    a.on(26, "TO_ALL", "SeaHold2", 27)
    a.on(27, "TAKEOFF", "SeaRunway2Depart", 28)
    a.on(28, "STARTTAKEOFF", "SeaRunway2Depart", 29)
    a.on(29, "ENDTAKEOFF", NOTHING, 0)
    # Runway 1.
    a.on(30, "FLYING", NOTHING, 38); a.on(30, "LANDING", "SeaRunway1Exit", 31)
    a.on(31, "LANDING", "SeaRunway1Land", 32)
    a.on(32, "TO_ALL", "SeaRunway1Land", 33)
    a.on(33, "ENDLANDING", "SeaRunway1Exit", 12); a.on(33, TERMGROUP, NOTHING, G2); a.on(33, TERMGROUP, NOTHING, G1)
    a.on(33, "TO_ALL", (), 12)
    a.on(34, "TO_ALL", "SeaHold1", 35)
    a.on(35, "TAKEOFF", "SeaRunway1Depart", 36)
    a.on(36, "STARTTAKEOFF", "SeaRunway1Depart", 37)
    a.on(37, "ENDTAKEOFF", NOTHING, 0)
    # Holding.
    a.on(38, "TO_ALL", NOTHING, 39)
    a.on(39, "TO_ALL", NOTHING, 22)
    a.on(40, "TO_ALL", NOTHING, 41)
    a.on(41, "TO_ALL", NOTHING, 30)
    return a


def dock() -> Airport:
    """
    Seaplane dock (1x2): one berth beside the dock, no hangar. The water lane at x = 24, outside the footprint, is
    split too: seaplanes touch down at y = 46 and stop at y = 26; departures line up at y = 20 and take off
    towards y < 0. A seaplane can land while the previous one takes off.
    """
    a = Airport("dock", "Seaplane dock", [1, 1], [10, 11, 9, 10], has_hangar=False)
    a.pos(10, 16, EXACT, "NW", "Berth")
    a.pos(20, 10, (), "N", "Leave the berth")
    a.pos(24, 20, EXACT, "NW", "Line up: start of the departure half")
    a.pos(24, -4, ROLL, "N", "End of the departure run")
    a.pos(24, -60, LIFT, "N", "Take off")
    a.pos(24, 110, AIR, "N", "Final approach fix")
    a.pos(24, 46, LAND, "N", "Touch down")
    a.pos(24, 26, BRAKE, "N", "Stop, holding short of the departure half")
    a.pos(18, 22, (), "N", "Leave the water lane")
    a.pos(110, 0, AIR, "N", "Holding (south-west)")
    a.pos(-10, 0, AIR, "N", "Holding (north-west)")
    a.pos(-10, 150, AIR, "N", "Holding (north-east)")
    a.pos(40, 160, AIR, "N", "Holding (south-east)")

    a.on(0, "TERM1", "Term1", 1)
    a.on(1, "TO_ALL", "SeaHold1", 2)
    a.on(2, "TAKEOFF", "SeaRunway1Depart", 3)
    a.on(3, "STARTTAKEOFF", "SeaRunway1Depart", 4)
    a.on(4, "ENDTAKEOFF", NOTHING, 0)
    a.on(5, "FLYING", NOTHING, 9); a.on(5, "LANDING", ("Term1", "SeaRunway1Exit"), 6)
    a.on(6, "LANDING", "SeaRunway1Land", 7)
    a.on(7, "TO_ALL", "SeaRunway1Land", 8)
    a.on(8, "ENDLANDING", "SeaRunway1Exit", 0); a.on(8, "TERM1", "Term1", 0); a.on(8, "TAKEOFF", (), 1)
    a.on(8, "TO_ALL", (), 1)
    a.on(9, "TO_ALL", NOTHING, 10)
    a.on(10, "TO_ALL", NOTHING, 11)
    a.on(11, "TO_ALL", NOTHING, 12)
    a.on(12, "TO_ALL", NOTHING, 5)
    return a


def kerb() -> Airport:
    """
    Seaplane kerb dock (6x3): eight slots nose-to-tail along a long floating dock (y = 12), a one-way lane beside
    them (y = 24) and a split runway inside the footprint (y = 40), so no open water is needed around it.
    Seaplanes land towards the north-east on the south-west half of the runway, stop in the middle, enter the lane at
    its south-west end and pull in alongside the dock at the first free slot (slot 1 is nearest the entry). They
    leave forward onto the lane, follow it to its north-east end and take off along the north-east half. With all
    slots taken, a landed seaplane follows the lane and takes off again. No hangar.
    """
    a = Airport("kerb", "Seaplane kerb dock", [1, 8], [26, 25, 28, 27], has_hangar=False)
    xs = [84, 73, 62, 51, 40, 29, 18, 7]
    for i, x in enumerate(xs):
        a.pos(x, 12, EXACT, "NE", f"Slot {i + 1} alongside the dock")          # 0-7
    for i, x in enumerate(xs):
        a.pos(x + 8, 24, (), "N", f"Lane beside slot {i + 1}")                 # 8-15
    a.pos(4, 24, (), "N", "North-east end of the lane")                         # 16
    a.pos(4, 40, (), "N", "Enter the departure half")                           # 17
    a.pos(46, 40, EXACT, "NE", "Line up: start of the departure half")          # 18
    a.pos(2, 40, ROLL, "N", "End of the departure run")                         # 19
    a.pos(-50, 40, LIFT, "N", "Take off")                                       # 20
    a.pos(140, 40, AIR, "N", "Final approach fix")                              # 21
    a.pos(92, 40, LAND, "N", "Touch down at the start of the landing half")     # 22
    a.pos(54, 40, BRAKE, "N", "Stop, holding short of the departure half")      # 23
    a.pos(72, 32, (), "N", "Leave the landing half for the lane")               # 24
    a.pos(10, 130, AIR, "N", "Holding (north-east)")                            # 25
    a.pos(10, -20, AIR, "N", "Holding (north-west)")                            # 26
    a.pos(150, -20, AIR, "N", "Holding (south-west)")                           # 27
    a.pos(170, 30, AIR, "N", "Holding (south)")                                 # 28

    for i in range(8):
        term = TERMINALS[i]
        ahead = 8 + i + 1 if i < 7 else 16
        a.on(i, term, TERM_BLOCK[term], ahead)                    # pull out forward onto the lane
    for i in range(8):
        term = TERMINALS[i]
        lane = "SeaTaxi%d" % (i + 1)
        ahead = 8 + i + 1 if i < 7 else 16
        a.on(8 + i, TERMGROUP, lane, 0); a.on(8 + i, term, TERM_BLOCK[term], i); a.on(8 + i, "TO_ALL", (), ahead)
    a.on(16, "TO_ALL", "SeaHold1", 17)
    a.on(17, "TO_ALL", "SeaRunway1Depart", 18)
    a.on(18, "TAKEOFF", "SeaRunway1Depart", 19)
    a.on(19, "STARTTAKEOFF", "SeaRunway1Depart", 20)
    a.on(20, "ENDTAKEOFF", NOTHING, 0)
    a.on(21, "FLYING", NOTHING, 25); a.on(21, "LANDING", "SeaRunway1Exit", 22)
    a.on(22, "LANDING", "SeaRunway1Land", 23)
    a.on(23, "TO_ALL", "SeaRunway1Land", 24)
    a.on(24, "ENDLANDING", "SeaRunway1Exit", 8); a.on(24, "TO_ALL", (), 8)
    a.on(25, "TO_ALL", NOTHING, 26)
    a.on(26, "TO_ALL", NOTHING, 27)
    a.on(27, "TO_ALL", NOTHING, 28)
    a.on(28, "TO_ALL", NOTHING, 21)
    return a


def _kerb_slots(a: Airport, xs, slot_y, lane_y, facing, lane_dx, first_term, lane_blocks, end_pos):
    """Slots nose-to-tail along a dock and the one-way lane beside them. Returns (slot positions, lane positions)."""
    slots = [a.pos(x, slot_y, EXACT, facing, f"Slot {first_term + i + 1} alongside the dock") for i, x in enumerate(xs)]
    lanes = [a.pos(x + lane_dx, lane_y, (), "N", f"Lane beside slot {first_term + i + 1}") for i, x in enumerate(xs)]
    return slots, lanes


def _kerb_slot_fta(a: Airport, slots, lanes, first_term, lane_blocks, end_pos, extra=None):
    for i, sp in enumerate(slots):
        term = TERMINALS[first_term + i]
        ahead = lanes[i + 1] if i + 1 < len(lanes) else end_pos
        a.on(sp, term, TERM_BLOCK[term], ahead)                           # pull out forward onto the lane
    for i, lp in enumerate(lanes):
        term = TERMINALS[first_term + i]
        ahead = lanes[i + 1] if i + 1 < len(lanes) else end_pos
        a.on(lp, TERMGROUP, lane_blocks[i], 0); a.on(lp, term, TERM_BLOCK[term], slots[i]); a.on(lp, "TO_ALL", (), ahead)


def kerb_hangar() -> Airport:
    """
    Seaplane kerb terminal with a hangar (5x4), e.g. Victoria: a terminal building and the hangar on the north-west
    row, a long dock in front of them with five slots nose-to-tail, a one-way lane and a split runway (y = 56).
    The hangar (tile 0,0) is at the exit end of the lane: seaplanes for service go straight in from there; seaplanes
    leaving it join the lane through a return path south of the lane, or line up directly for departure.
    """
    a = Airport("kerb_hangar", "Seaplane kerb terminal with hangar", [1, 5], [0, 0, 0, 0], depots=[((0, 0), "SE")])
    xs = [70, 59, 48, 37, 26]
    slots, lanes = _kerb_slots(a, xs, 29, 41, "NE", 6, 0, None, None)   # 0-4 slots, 5-9 lanes
    W = a.pos(14, 41, (), "N", "North-east end of the lane")          # 10
    H = a.pos(7, 3, EXACT, "SE", "In hangar")                         # 11
    HX = a.pos(8, 24, (), "N", "Outside the hangar")                  # 12
    R = a.pos(6, 56, (), "N", "Enter the departure half")             # 13
    LU = a.pos(38, 56, EXACT, "NE", "Line up: start of the departure half")  # 14
    END = a.pos(2, 56, ROLL, "N", "End of the departure run")         # 15
    LF = a.pos(-50, 56, LIFT, "N", "Take off")                        # 16
    F = a.pos(130, 56, AIR, "N", "Final approach fix")                # 17
    TD = a.pos(76, 56, LAND, "N", "Touch down at the start of the landing half")  # 18
    BR = a.pos(44, 56, BRAKE, "N", "Stop, holding short of the departure half")  # 19
    X = a.pos(66, 48, (), "N", "Leave the landing half for the lane")  # 20
    RL1 = a.pos(4, 47, (), "N", "Return path from the hangar")         # 21
    RL2 = a.pos(58, 48, (), "N", "Return path to the lane")            # 22
    H1 = a.pos(10, 130, AIR, "N", "Holding (north-east)")             # 23
    H2 = a.pos(10, -20, AIR, "N", "Holding (north-west)")             # 24
    H3 = a.pos(150, -20, AIR, "N", "Holding (south-west)")            # 25
    H4 = a.pos(170, 40, AIR, "N", "Holding (south)")                  # 26
    a.entries = [H2, H1, H4, H3]

    _kerb_slot_fta(a, slots, lanes, 0, ["SeaTaxi%d" % (i + 1) for i in range(5)], W)
    a.on(W, TERMGROUP, "SeaHold1", 0); a.on(W, "HANGAR", (), H); a.on(W, "TO_ALL", (), R)
    a.on(H, "HANGAR", NOTHING, HX)
    a.on(HX, TERMGROUP, "Hangar1Area", 0); a.on(HX, "TAKEOFF", (), R); a.on(HX, "HANGAR", (), H); a.on(HX, "TO_ALL", (), RL1)
    a.on(R, "TO_ALL", "SeaRunway1Depart", LU)
    a.on(LU, "TAKEOFF", "SeaRunway1Depart", END)
    a.on(END, "STARTTAKEOFF", "SeaRunway1Depart", LF)
    a.on(LF, "ENDTAKEOFF", NOTHING, 0)
    a.on(F, "FLYING", NOTHING, H1); a.on(F, "LANDING", "SeaRunway1Exit", TD)
    a.on(TD, "LANDING", "SeaRunway1Land", BR)
    a.on(BR, "TO_ALL", "SeaRunway1Land", X)
    a.on(X, "ENDLANDING", "SeaRunway1Exit", lanes[0]); a.on(X, "TO_ALL", (), lanes[0])
    a.on(RL1, "TO_ALL", "SeaTaxi6", RL2)
    a.on(RL2, "TO_ALL", "SeaTaxi6", X)
    a.on(H1, "TO_ALL", NOTHING, H2)
    a.on(H2, "TO_ALL", NOTHING, H3)
    a.on(H3, "TO_ALL", NOTHING, H4)
    a.on(H4, "TO_ALL", NOTHING, F)
    return hangars_first(a, [H])


def kerb_large() -> Airport:
    """
    Large seaplane kerb terminal (7x7), e.g. Vancouver: a central pier (y = 50-62) with the terminal, slots along both
    faces of it, and two independent circuits, each with its own one-way lane, split runway and hangar:
      north: runway y = 8 landed towards the north-east, lane y = 32 towards x = 0, slots 1-4 at y = 44, hangar (6,1);
      south: runway y = 104 landed towards the south-west, lane y = 80 towards x = 112, slots 5-8 at y = 68, hangar (6,5).
    The holding pattern passes both final approach fixes.
    """
    a = Airport("kerb_large", "Large seaplane kerb terminal", [2, 4, 4], [0, 0, 0, 0],
                depots=[((6, 1), "SE"), ((6, 5), "SE")])
    sn, ln = _kerb_slots(a, [92, 74, 56, 38], 44, 32, "NE", 8, 0, None, None)     # 0-3, 4-7
    ss, ls = _kerb_slots(a, [20, 38, 56, 74], 68, 80, "SW", -8, 4, None, None)    # 8-11, 12-15
    WN = a.pos(24, 32, (), "N", "North lane: north-east end")                    # 16
    RN = a.pos(8, 8, (), "N", "Enter the departure half of the north runway")   # 17
    LUN = a.pos(56, 8, EXACT, "NE", "Line up on the north runway")              # 18
    ENDN = a.pos(2, 8, ROLL, "N", "End of the departure run, north runway")     # 19
    LIFTN = a.pos(-50, 8, LIFT, "N", "Take off from the north runway")          # 20
    FN = a.pos(170, 8, AIR, "N", "Final approach fix, north runway")            # 21
    TDN = a.pos(106, 8, LAND, "N", "Touch down on the north runway")            # 22
    BRN = a.pos(64, 8, BRAKE, "N", "Stop on the north runway, holding short")    # 23
    XN = a.pos(84, 20, (), "N", "Leave the north runway for the north lane")    # 24
    HN = a.pos(103, 19, EXACT, "SE", "In the north hangar")                     # 25
    HXN = a.pos(106, 38, (), "N", "Outside the north hangar")                   # 26
    RN1 = a.pos(20, 22, (), "N", "Path to the north hangar")                    # 27
    RN2 = a.pos(92, 24, (), "N", "Path to the north hangar")                    # 28
    ES = a.pos(90, 80, (), "N", "South lane: south-west end")                   # 29
    RS = a.pos(106, 104, (), "N", "Enter the departure half of the south runway")  # 30
    LUS = a.pos(56, 104, EXACT, "SW", "Line up on the south runway")            # 31
    ENDS = a.pos(110, 104, ROLL, "N", "End of the departure run, south runway")  # 32
    LIFTS = a.pos(170, 104, LIFT, "N", "Take off from the south runway")        # 33
    FS = a.pos(-60, 104, AIR, "N", "Final approach fix, south runway")          # 34
    TDS = a.pos(6, 104, LAND, "N", "Touch down on the south runway")            # 35
    BRS = a.pos(48, 104, BRAKE, "N", "Stop on the south runway, holding short")  # 36
    XS = a.pos(28, 92, (), "N", "Leave the south runway for the south lane")    # 37
    HS = a.pos(103, 83, EXACT, "SE", "In the south hangar")                     # 38
    HXS = a.pos(104, 96, (), "N", "Outside the south hangar")                   # 39
    RS1 = a.pos(90, 92, (), "N", "Return path from the south hangar")           # 40
    RS2 = a.pos(8, 90, (), "N", "Return path to the south lane")                # 41
    HNW = a.pos(60, -60, AIR, "N", "Holding (north-west)")                      # 42
    HW = a.pos(-60, 40, AIR, "N", "Holding (north-east)")                       # 43
    HSE = a.pos(60, 170, AIR, "N", "Holding (south-east)")                      # 44
    HE = a.pos(170, 70, AIR, "N", "Holding (south-west)")                       # 45
    a.entries = [HW, HSE, HE, HNW]

    # North circuit (terminal group 0).
    _kerb_slot_fta(a, sn, ln, 0, ["SeaTaxi1", "SeaTaxi2", "SeaTaxi3", "SeaTaxi4"], WN)
    a.on(WN, TERMGROUP, "SeaHold2", 0); a.on(WN, "HANGAR", (), RN1); a.on(WN, "TO_ALL", (), RN)
    a.on(RN, "TO_ALL", "SeaRunway2Depart", LUN)
    a.on(LUN, "TAKEOFF", "SeaRunway2Depart", ENDN)
    a.on(ENDN, "STARTTAKEOFF", "SeaRunway2Depart", LIFTN)
    a.on(LIFTN, "ENDTAKEOFF", NOTHING, 0)
    a.on(FN, "FLYING", NOTHING, HNW); a.on(FN, "LANDING", "SeaRunway2Exit", TDN)
    a.on(TDN, "LANDING", "SeaRunway2Land", BRN)
    a.on(BRN, "TO_ALL", "SeaRunway2Land", XN)
    a.on(XN, "ENDLANDING", "SeaRunway2Exit", ln[0]); a.on(XN, TERMGROUP, NOTHING, 0); a.on(XN, "TO_ALL", (), ln[0])
    a.on(HN, "HANGAR", NOTHING, HXN); a.on(HN, TERMGROUP, NOTHING, 0); a.on(HN, "TO_ALL", (), HXN)
    a.on(HXN, TERMGROUP, "Hangar1Area", 0); a.on(HXN, "HANGAR", (), HN); a.on(HXN, "TO_ALL", (), ln[0])
    a.on(RN1, "TO_ALL", "SeaTaxi9", RN2)
    a.on(RN2, "TO_ALL", "SeaTaxi9", HN)
    # South circuit (terminal group 1).
    _kerb_slot_fta(a, ss, ls, 4, ["SeaTaxi5", "SeaTaxi6", "SeaTaxi7", "SeaTaxi8"], ES)
    a.on(ES, TERMGROUP, "SeaHold1", 0); a.on(ES, "HANGAR", (), HS); a.on(ES, "TO_ALL", (), RS)
    a.on(RS, "TO_ALL", "SeaRunway1Depart", LUS)
    a.on(LUS, "TAKEOFF", "SeaRunway1Depart", ENDS)
    a.on(ENDS, "STARTTAKEOFF", "SeaRunway1Depart", LIFTS)
    a.on(LIFTS, "ENDTAKEOFF", NOTHING, 0)
    a.on(FS, "FLYING", NOTHING, HSE); a.on(FS, "LANDING", "SeaRunway1Exit", TDS)
    a.on(TDS, "LANDING", "SeaRunway1Land", BRS)
    a.on(BRS, "TO_ALL", "SeaRunway1Land", XS)
    a.on(XS, "ENDLANDING", "SeaRunway1Exit", ls[0]); a.on(XS, TERMGROUP, NOTHING, 1); a.on(XS, "TO_ALL", (), ls[0])
    a.on(HS, "HANGAR", NOTHING, HXS); a.on(HS, TERMGROUP, NOTHING, 1); a.on(HS, "TO_ALL", (), HXS)
    a.on(HXS, TERMGROUP, "Hangar2Area", 0); a.on(HXS, "TAKEOFF", (), RS); a.on(HXS, "HANGAR", (), HS); a.on(HXS, "TO_ALL", (), RS1)
    a.on(RS1, "TO_ALL", "SeaTaxi10", RS2)
    a.on(RS2, "TO_ALL", "SeaTaxi10", ls[0])
    # Holding pattern through both final approach fixes.
    a.on(HNW, "TO_ALL", NOTHING, HW)
    a.on(HW, "TO_ALL", NOTHING, FS)
    a.on(HSE, "TO_ALL", NOTHING, HE)
    a.on(HE, "TO_ALL", NOTHING, FN)
    return hangars_first(a, [HN, HS])


AIRPORTS = [country, commuter, city, metropolitan, international, dock, kerb, kerb_hangar, kerb_large]

# ---------------------------------------------------------------------------------------------- C++ output


def cpp_blocks(blocks):
    if not blocks:
        return "{}"
    if len(blocks) == 1:
        return "AirportBlock::" + blocks[0]
    return "AirportBlocks({" + ", ".join("AirportBlock::" + b for b in blocks) + "})"


def generate() -> str:
    out = ["/*",
           " * This file is part of OpenTTD.",
           " * OpenTTD is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 2.",
           " * OpenTTD is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.",
           " * See the GNU General Public License for more details. You should have received a copy of the GNU General Public License along with OpenTTD. If not, see <https://www.gnu.org/licenses/old-licenses/gpl-2.0>.",
           " */",
           "",
           "/**",
           " * @file seaplane_movement.h Movement data and state machines of the TGTFTD seaplane terminals.",
           " * GENERATED by tools/seaplane_fta.py -- edit that script and re-run it instead of editing this file.",
           " *",
           " * Every runway is split in a landing half and a departure half with their own blocks, so a seaplane can",
           " * land while another one takes off. Berths and hangars are where the land airports have them.",
           " */",
           "",
           "#ifndef SEAPLANE_MOVEMENT_H",
           "#define SEAPLANE_MOVEMENT_H",
           ""]
    for make in AIRPORTS:
        a = make()
        validate(a)
        out.append(f"/** {a.title}. */")
        out.append(f"static const AirportMovingData _airport_moving_data_seaplane_{a.name}[{len(a.positions)}] = {{")
        for i, (x, y, flags, direction, comment) in enumerate(a.positions):
            fl = "{" + ", ".join("AirportMovingDataFlag::" + f for f in flags) + "}"
            out.append(f"\t{{ {x:4d}, {y:4d}, {fl + ',':<75} Direction::{direction:<2} }}, // {i:02d} {comment}")
        out.append("};")
        if a.depots:
            hangars = ", ".join(f"{{{{{x}, {y}}}, Direction::{d}, {i}}}" for i, ((x, y), d) in enumerate(a.depots))
            out.append(f"static const HangarTileTable _airport_depots_seaplane_{a.name}[] = {{ {hangars} }};")
        out.append(f"static const uint8_t _airport_terminal_seaplane_{a.name}[] = {{ {', '.join(map(str, a.terminals))} }};")
        out.append(f"static const uint8_t _airport_entries_seaplane_{a.name}[] = {{ {', '.join(map(str, a.entries))} }};")
        out.append(f"static const AirportFTAbuildup _airport_fta_seaplane_{a.name}[] = {{")
        last = None
        line = []
        for p, heading, blocks, nxt in a.fta:
            if p != last and line:
                out.append("\t" + " ".join(line))
                line = []
            last = p
            line.append(f"{{ {p:2d}, {heading}, {cpp_blocks(blocks)}, {nxt} }},")
        out.append("\t" + " ".join(line))
        out.append("\t{ MAX_ELEMENTS, TO_ALL, {}, 0 } // end marker. DO NOT REMOVE")
        out.append("};")
        out.append("")
    out.append("#endif /* SEAPLANE_MOVEMENT_H */")
    return "\n".join(out) + "\n"


def validate(a: Airport):
    n = len(a.positions)
    seen = []
    for p, heading, blocks, nxt in a.fta:
        assert 0 <= p < n, (a.name, p)
        assert 0 <= nxt < n or heading == TERMGROUP, (a.name, p, nxt)
        assert heading in STATES or heading == TERMGROUP, heading
        for b in blocks:
            assert b in NEW_BLOCKS or b in ("Nothing", "Hangar1Area", "Hangar2Area") or b.startswith("Term"), b
        if not seen or seen[-1] != p:
            assert p not in seen, f"{a.name}: entries of position {p} are not consecutive"
            seen.append(p)
    assert seen == list(range(n)), f"{a.name}: positions without state machine entries: {set(range(n)) - set(seen)}"
    assert len(a.entries) == 4 and all(0 <= e < n for e in a.entries)
    first = {}
    for p, heading, blocks, nxt in a.fta:
        first.setdefault(p, heading)
    hangar_positions = sorted(p for p, h in first.items() if h == "HANGAR")
    assert hangar_positions == list(range(len(hangar_positions))), \
        f"{a.name}: hangars must be the first positions (hangar n = position n), got {hangar_positions}"
    if a.depots:
        assert len(hangar_positions) == len(a.depots), f"{a.name}: {len(a.depots)} hangar tiles but {hangar_positions}"

# ---------------------------------------------------------------------------------------------- simulator


class Entry:
    def __init__(self, position, heading, blocks, nxt):
        self.position, self.heading, self.blocks, self.next_position = position, heading, frozenset(blocks), nxt
        self.next = None


def build_layout(a: Airport):
    layout = []
    for p, heading, blocks, nxt in a.fta:
        e = Entry(p, heading, blocks, nxt)
        if p == len(layout):
            layout.append(e)
        else:
            cur = layout[p]
            while cur.next is not None:
                cur = cur.next
            cur.next = e
    return layout


class Plane:
    def __init__(self, idx):
        self.idx = idx
        self.pos = 0
        self.previous_pos = 0
        self.state = "FLYING"
        self.x = self.y = 0.0
        self.wait = 0           # ticks to stay (loading, servicing)
        self.away = 0           # ticks away from the airport (flying elsewhere)
        self.goto_hangar = False
        self.stuck = 0


class Sim:
    TAXI, AIRSPEED = 0.6, 2.0  # world units per tick

    def __init__(self, a: Airport, planes: int, seed: int):
        self.a = a
        self.layout = build_layout(a)
        self.blocks = set()
        self.rng = random.Random(seed)
        self.planes = [Plane(i) for i in range(planes)]
        self.tick = 0
        self.landings = self.takeoffs = 0
        self.overlap_ticks = 0
        self.concurrent = 0
        for p in self.planes:
            p.away = self.rng.randrange(1, 400)

    # --- helpers mirroring aircraft_cmd.cpp
    def num_terminals(self):
        return sum(self.a.terminals[1:])

    def free_terminal(self, p, first, last):
        for i in range(first, last):
            b = "Term%d" % (i + 1)
            if b not in self.blocks:
                p.state = TERMINALS[i]
                self.blocks.add(b)
                return True
        return False

    def find_free_terminal(self, p):
        if self.a.terminals[0] > 1:
            temp = self.layout[p.pos].next
            while temp is not None:
                if temp.heading == TERMGROUP:
                    if not (self.blocks & temp.blocks):
                        group = temp.next_position + 1
                        start = sum(self.a.terminals[1:group])
                        if self.free_terminal(p, start, start + self.a.terminals[group]):
                            return True
                else:
                    return False
                temp = temp.next
        return self.free_terminal(p, 0, self.num_terminals())

    def has_block(self, p, cur):
        reference = self.layout[p.pos]
        nxt = self.layout[cur.next_position]
        if self.layout[cur.position].blocks != nxt.blocks:
            b = set(nxt.blocks)
            if cur is not reference and cur.blocks and cur.blocks != {"Nothing"}:
                b |= cur.blocks
            if self.blocks & b:
                return True
        return False

    def set_blocks(self, p, cur):
        nxt = self.layout[cur.next_position]
        reference = self.layout[p.pos]
        if not nxt.blocks <= self.layout[cur.position].blocks:
            b = set(nxt.blocks)
            c = cur
            if c is reference:
                c = c.next
            while c is not None:
                if c.heading == cur.heading and c.blocks:
                    b |= c.blocks
                    break
                c = c.next
            if cur.blocks == nxt.blocks:
                b ^= nxt.blocks
            if self.blocks & b:
                return False
            if nxt.blocks != {"Nothing"}:
                self.blocks |= b
        return True

    def clear_block(self, p):
        if self.layout[p.previous_pos].blocks != self.layout[p.pos].blocks:
            self.blocks -= self.layout[p.previous_pos].blocks

    def airport_move(self, p):
        cur = self.layout[p.pos]
        if cur.heading == p.state:
            prev_pos = p.pos
            self.handle(p)
            if p.state != "FLYING":
                p.previous_pos = prev_pos
            return True
        p.previous_pos = p.pos
        if cur.next is None:
            if self.set_blocks(p, cur):
                p.pos = cur.next_position
            return False
        while cur is not None:
            if p.state == cur.heading or cur.heading == "TO_ALL":
                if self.set_blocks(p, cur):
                    p.pos = cur.next_position
                return False
            cur = cur.next
        raise RuntimeError(f"{self.a.name}: cannot move further (pos {p.pos} state {p.state})")

    # --- state handlers
    def handle(self, p):
        s = p.state
        if s == "HANGAR":
            if p.previous_pos != p.pos:      # just arrived: service
                p.wait = 40
                p.previous_pos = p.pos
                return
            if self.has_block(p, self.layout[p.pos]):
                return
            if not self.find_free_terminal(p):
                return
            self.airport_move(p)
        elif s in TERMINALS:
            if p.previous_pos != p.pos:      # just arrived: load
                p.wait = self.rng.randrange(60, 200)
                p.previous_pos = p.pos
                return
            if self.has_block(p, self.layout[p.pos]):
                return
            p.state = "HANGAR" if (self.a.has_hangar and self.rng.random() < 0.15) else "TAKEOFF"
            self.airport_move(p)
        elif s == "TAKEOFF":
            p.state = "STARTTAKEOFF"
        elif s == "STARTTAKEOFF":
            p.state = "ENDTAKEOFF"
        elif s == "ENDTAKEOFF":
            self.takeoffs += 1
            p.state = "FLYING"
            p.away = self.rng.randrange(100, 900)
        elif s == "FLYING":
            cur = self.layout[p.pos].next
            while cur is not None:
                if cur.heading == "LANDING" and not self.has_block(p, cur):
                    p.state = "LANDING"
                    p.pos = cur.next_position
                    self.blocks |= self.layout[p.pos].blocks
                    return
                cur = cur.next
            p.state = "FLYING"
            p.pos = self.layout[p.pos].next_position
        elif s == "LANDING":
            p.state = "ENDLANDING"
            self.landings += 1
        elif s == "ENDLANDING":
            if self.has_block(p, self.layout[p.pos]):
                return
            if self.find_free_terminal(p):
                return
            p.state = "HANGAR" if self.a.has_hangar else "TAKEOFF"

    # --- movement
    def step_plane(self, p):
        if p.away > 0:
            p.away -= 1
            if p.away == 0:
                p.pos = p.previous_pos = self.a.entries[self.rng.randrange(4)]
                x, y, *_ = self.a.positions[p.pos]
                p.x, p.y = x, y
            return
        if p.wait > 0:
            p.wait -= 1
            return
        x, y, flags, *_ = self.a.positions[p.pos]
        d = math.hypot(x - p.x, y - p.y)
        speed = self.AIRSPEED if ("SlowTurn" in flags or "Land" in flags or "Takeoff" in flags or "NoSpeedClamp" in flags) else self.TAXI
        if d > speed:
            p.x += (x - p.x) / d * speed
            p.y += (y - p.y) / d * speed
            p.stuck = 0
            return
        p.x, p.y = x, y
        before = (p.pos, p.state)
        self.clear_block(p)
        self.airport_move(p)
        p.stuck = p.stuck + 1 if (p.pos, p.state) == before else 0

    def run(self, ticks):
        land_rolls = {i for i, pos in enumerate(self.a.positions) if "Land" in pos[2] or "Brake" in pos[2]}
        dep_rolls = {i for i, pos in enumerate(self.a.positions) if "ExactPosition" in pos[2] and False}
        for t in range(ticks):
            self.tick = t
            for p in self.planes:
                self.step_plane(p)
            landing = any(p.away == 0 and p.pos in land_rolls and p.state in ("LANDING", "ENDLANDING") for p in self.planes)
            departing = any(p.away == 0 and p.state in ("STARTTAKEOFF", "ENDTAKEOFF", "TAKEOFF") for p in self.planes)
            if landing and departing:
                self.overlap_ticks += 1
            here = [p for p in self.planes if p.away == 0]
            if here and all(p.wait == 0 and p.stuck > 2000 for p in here):
                desc = "; ".join(f"plane {p.idx} at {p.pos} ({self.a.positions[p.pos][4]}) state {p.state}"
                                 + (f" moving, wait {p.wait}" if p.wait else "") for p in self.planes if p.away == 0)
                raise RuntimeError(f"{self.a.name}: deadlock at tick {t}: {desc}; blocks {sorted(self.blocks)}")
            self.max_wait = max([getattr(self, "max_wait", 0)] + [p.stuck for p in here])
        return self


def check():
    ok = True
    for make in AIRPORTS:
        a = make()
        validate(a)
        planes = {"dock": 3, "kerb": 12, "kerb_hangar": 8, "kerb_large": 12}.get(a.name, sum(a.terminals[1:]) * 2 + 2)
        results = []
        for seed in range(8):
            try:
                s = Sim(a, planes, seed).run(60000)
                results.append(s)
            except RuntimeError as e:
                print("FAIL", e)
                ok = False
                break
        else:
            land = sum(r.landings for r in results) // len(results)
            take = sum(r.takeoffs for r in results) // len(results)
            overlap = sum(r.overlap_ticks for r in results) // len(results)
            wait = max(r.max_wait for r in results)
            print(f"{a.name:14s} {planes:2d} seaplanes: {land:5d} landings, {take:5d} take-offs per run, "
                  f"landing and taking off at the same time for {overlap} ticks, longest wait {wait} ticks; "
                  f"no deadlock in {len(results)} runs")
    return ok


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    OUT.write_text(generate(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
