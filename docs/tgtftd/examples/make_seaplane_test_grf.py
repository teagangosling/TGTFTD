#!/usr/bin/env python3
"""
Build seaplane_test.grf: a tiny NewGRF for testing TGTFTD seaplanes and seaplane terminals.

It contains no graphics. It:
  * marks the default Sampson U52, Coleman Count and Bakewell Cotswald LB-3 as seaplanes, and
  * adds a NewGRF airport "Test Seaplane Base" that uses the Commuter airport layout on water.

Usage:  python make_seaplane_test_grf.py [output.grf]
Then copy the .grf into your OpenTTD "newgrf" folder and enable it in the NewGRF settings.

The same content is listed in NFO form in seaplane_test.nfo (next to this script) so it can be
read alongside docs/tgtftd-seaplanes.md. Only the Python standard library is needed.
"""

import struct
import sys

GRFID = b"TGS\x01"

# Property IDs we assign with Action 14 property mapping (any unused ID of the feature works).
PROP_AIRCRAFT_IS_SEAPLANE = 0xF0
PROP_AIRPORT_SEAPLANE_TERMINAL = 0xF1

# Bits of global variable 0x8D that the property mappings set on success.
BIT_AIRCRAFT_MAPPED = 4
BIT_AIRPORT_MAPPED = 5

FEAT_AIRCRAFT = 0x03
FEAT_AIRPORTS = 0x0D


def text(s: str) -> bytes:
    return s.encode("utf-8") + b"\x00"


def a14_text(chunk_id: bytes, value: str) -> bytes:
    """Action 14 text sub-chunk: 'T' <id> <language> <string> 00."""
    return b"T" + chunk_id + b"\x00" + text(value)


def a14_binary(chunk_id: bytes, data: bytes) -> bytes:
    """Action 14 binary sub-chunk: 'B' <id> <size: word> <data>."""
    return b"B" + chunk_id + struct.pack("<H", len(data)) + data


def a14_property_mapping(name: str, feature: int, prop: int, success_bit: int) -> bytes:
    """Action 14 C "A0PM" chunk mapping a named property to an Action 0 property ID."""
    return (b"C" + b"A0PM"
            + a14_text(b"NAME", name)
            + a14_binary(b"FEAT", bytes([feature]))
            + a14_binary(b"PROP", bytes([prop]))
            + a14_binary(b"SETT", bytes([success_bit]))
            + b"\x00")


def skip_if_bit_clear(variable: int, bit: int, num_sprites: int) -> bytes:
    """Action 7: skip num_sprites sprites if the given bit of a global variable is clear."""
    return bytes([0x07, variable, 0x01, 0x01, bit, num_sprites])


def pseudo_sprite(data: bytes) -> bytes:
    """Container version 1 pseudo sprite: <size: word> FF <data>."""
    return struct.pack("<H", len(data)) + b"\xff" + data


def build() -> bytes:
    sprites = []

    # Action 8: GRF version 8, GRF ID, name, description.
    sprites.append(b"\x08\x08" + GRFID + text("TGTFTD seaplane test")
                   + text("Marks the Sampson U52, Coleman Count and Bakewell Cotswald LB-3 as seaplanes "
                          "and adds a Test Seaplane Base. For testing TGTFTD only."))

    # Action 14: map the TGTFTD properties to property IDs F0 (aircraft) and F1 (airports).
    sprites.append(b"\x14"
                   + a14_property_mapping("aircraft_is_seaplane", FEAT_AIRCRAFT, PROP_AIRCRAFT_IS_SEAPLANE, BIT_AIRCRAFT_MAPPED)
                   + a14_property_mapping("airport_seaplane_terminal", FEAT_AIRPORTS, PROP_AIRPORT_SEAPLANE_TERMINAL, BIT_AIRPORT_MAPPED)
                   + b"\x00")

    # Seaplanes: skip the next 2 sprites when not running TGTFTD (mapping failed).
    sprites.append(skip_if_bit_clear(0x8D, BIT_AIRCRAFT_MAPPED, 2))
    # Action 0, aircraft, 1 property, 2 vehicles starting at ID 0 (Sampson U52, Coleman Count):
    # mapped property F0, each value is <size 01> <value 01>.
    sprites.append(bytes([0x00, FEAT_AIRCRAFT, 0x01, 0x02, 0x00, PROP_AIRCRAFT_IS_SEAPLANE, 0x01, 0x01, 0x01, 0x01]))
    # Action 0, aircraft ID 4 (Bakewell Cotswald LB-3).
    sprites.append(bytes([0x00, FEAT_AIRCRAFT, 0x01, 0x01, 0x04, PROP_AIRCRAFT_IS_SEAPLANE, 0x01, 0x01]))

    # Action 4: airport name text DC00 (all languages).
    sprites.append(bytes([0x04, FEAT_AIRPORTS, 0xFF, 0x01]) + struct.pack("<H", 0xDC00) + text("Test Seaplane Base"))

    # Seaplane terminal: skip the next sprite when not running TGTFTD.
    sprites.append(skip_if_bit_clear(0x8D, BIT_AIRPORT_MAPPED, 1))
    # Action 0, airports, 4 properties, 1 airport with local ID 0:
    #   08 05        substitute airport: 05 = Commuter (copies its layout, hangar and state machine)
    #   F1 01 01     airport_seaplane_terminal = 1 (seaplane-only state machine, built on water, "Seaplane terminals" class)
    #   0C 80 07 FF FF  available from 1920, never expires
    #   10 00 DC     name = text DC00
    sprites.append(bytes([0x00, FEAT_AIRPORTS, 0x04, 0x01, 0x00,
                          0x08, 0x05,
                          PROP_AIRPORT_SEAPLANE_TERMINAL, 0x01, 0x01,
                          0x0C]) + struct.pack("<HH", 1920, 0xFFFF)
                   + bytes([0x10]) + struct.pack("<H", 0xDC00))

    out = bytearray()
    # Sprite 0: number of sprites that follow.
    out += pseudo_sprite(struct.pack("<I", len(sprites)))
    for s in sprites:
        out += pseudo_sprite(s)
    # End of sprites, followed by an (unused) checksum.
    out += struct.pack("<H", 0) + struct.pack("<I", 0)
    return bytes(out)


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "seaplane_test.grf"
    with open(path, "wb") as f:
        f.write(build())
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
