/*
 * This file is part of OpenTTD.
 * OpenTTD is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 2.
 * OpenTTD is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See the GNU General Public License for more details. You should have received a copy of the GNU General Public License along with OpenTTD. If not, see <https://www.gnu.org/licenses/old-licenses/gpl-2.0>.
 */

/** @file airport.cpp Functions related to airports. */

#include "stdafx.h"
#include "station_base.h"

#include "table/strings.h"
#include "table/airport_movement.h"
#include "table/airporttile_ids.h"

#include "safeguards.h"


/**
 * Define a generic airport.
 * @param name Suffix of the names of the airport data.
 * @param terminals The terminals.
 * @param num_helipads Number of heli pads.
 * @param flags Information about the class of FTA.
 * @param delta_z Height of the airport above the land.
 */
#define AIRPORT_GENERIC(name, terminals, num_helipads, flags, delta_z) \
	static const AirportFTAClass _airportfta_ ## name(_airport_moving_data_ ## name, terminals, \
			num_helipads, _airport_entries_ ## name, flags, _airport_fta_ ## name, delta_z);

/**
 * Define an airport.
 * @param name Suffix of the names of the airport data.
 * @param num_helipads Number of heli pads.
 * @param short_strip Airport has a short land/take-off strip.
 */
#define AIRPORT(name, num_helipads, short_strip) \
	AIRPORT_GENERIC(name, _airport_terminal_ ## name, num_helipads, AirportFTAClass::Flags({AirportFTAClass::Flag::Airplanes, AirportFTAClass::Flag::Helicopters}) | (short_strip ? AirportFTAClass::Flags{AirportFTAClass::Flag::ShortStrip} : AirportFTAClass::Flags{}), 0)

/**
 * Define a heliport.
 * @param name Suffix of the names of the helipad data.
 * @param num_helipads Number of heli pads.
 * @param delta_z Height of the airport above the land.
 */
#define HELIPORT(name, num_helipads, delta_z) \
	AIRPORT_GENERIC(name, nullptr, num_helipads, AirportFTAClass::Flag::Helicopters, delta_z)

AIRPORT(country, 0, true)
AIRPORT(city, 0, false)
HELIPORT(heliport, 1, 60)
AIRPORT(metropolitan, 0, false)
AIRPORT(international, 2, false)
AIRPORT(commuter, 2, true)
HELIPORT(helidepot, 1, 0)
AIRPORT(intercontinental, 2, false)
HELIPORT(helistation, 3, 0)
HELIPORT(oilrig, 1, 54)
AIRPORT_GENERIC(dummy, nullptr, 0, AirportFTAClass::Flags({AirportFTAClass::Flag::Airplanes, AirportFTAClass::Flag::Helicopters}), 0)


/**
 * Derive the movement data of a seaplane terminal from that of a land airport.
 * Seaplanes need far less room than land planes, so waiting for a free runway costs less time:
 *  - the touchdown point moves to 40% of the way from the end of the landing run, for a short run on the water;
 *  - the final approach fix in line with the runway moves halfway towards the new touchdown point;
 *  - the other in-air waypoints (holding pattern, approach fixes) are pulled in to 60% of their distance
 *    from the middle of the airport, for a tighter holding pattern.
 * Ground positions (taxiways, terminals, hangars, the end of the landing run) are unchanged, so the
 * state machine of the land airport still applies.
 * @param land Movement data of the land airport.
 * @return Movement data of the seaplane terminal.
 */
static std::vector<AirportMovingData> MakeSeaplaneMovingData(std::span<const AirportMovingData> land)
{
	using Flag = AirportMovingDataFlag;
	auto in_air = [](const AirportMovingData &amd) {
		return amd.flags.Test(Flag::SlowTurn) && amd.flags.Any({Flag::NoSpeedClamp, Flag::Hold}) &&
				!amd.flags.Any({Flag::Land, Flag::Brake, Flag::Takeoff, Flag::HeliRaise, Flag::HeliLower});
	};

	std::vector<AirportMovingData> out(land.begin(), land.end());

	/* Middle of the ground positions. */
	int min_x = std::numeric_limits<int>::max(), min_y = min_x, max_x = std::numeric_limits<int>::min(), max_y = max_x;
	for (const AirportMovingData &amd : land) {
		if (in_air(amd) || amd.flags.Any({Flag::Land, Flag::Takeoff})) continue;
		min_x = std::min<int>(min_x, amd.x);
		max_x = std::max<int>(max_x, amd.x);
		min_y = std::min<int>(min_y, amd.y);
		max_y = std::max<int>(max_y, amd.y);
	}
	if (min_x > max_x) return out;
	const int centre_x = (min_x + max_x) / 2;
	const int centre_y = (min_y + max_y) / 2;

	std::vector<bool> moved(land.size(), false);
	for (size_t i = 0; i < land.size(); i++) {
		if (!land[i].flags.Test(Flag::Land)) continue;
		/* The end of the landing run: the next braking position in line with this touchdown point. */
		for (size_t j = i + 1; j < land.size(); j++) {
			const AirportMovingData &brake = land[j];
			if (!brake.flags.Test(Flag::Brake)) continue;
			const bool along_x = std::abs(brake.y - land[i].y) <= 3;
			const bool along_y = std::abs(brake.x - land[i].x) <= 3;
			if (!along_x && !along_y) continue;

			const int touch_x = brake.x + (land[i].x - brake.x) * 2 / 5;
			const int touch_y = brake.y + (land[i].y - brake.y) * 2 / 5;
			out[i].x = touch_x;
			out[i].y = touch_y;

			/* In-air waypoints on the extended runway line, beyond the old touchdown point: shorter final approach. */
			for (size_t k = 0; k < land.size(); k++) {
				const AirportMovingData &fix = land[k];
				if (!in_air(fix) || moved[k]) continue;
				if (along_x && std::abs(fix.y - land[i].y) <= 3 && (fix.x - land[i].x) * (land[i].x - brake.x) > 0) {
					out[k].x = touch_x + (fix.x - touch_x) / 2;
					moved[k] = true;
				} else if (along_y && std::abs(fix.x - land[i].x) <= 3 && (fix.y - land[i].y) * (land[i].y - brake.y) > 0) {
					out[k].y = touch_y + (fix.y - touch_y) / 2;
					moved[k] = true;
				}
			}
			break;
		}
	}

	/* Tighter holding pattern and approach fixes. */
	for (size_t k = 0; k < land.size(); k++) {
		if (!in_air(land[k]) || moved[k]) continue;
		out[k].x = centre_x + (land[k].x - centre_x) * 3 / 5;
		out[k].y = centre_y + (land[k].y - centre_y) * 3 / 5;
	}
	return out;
}

/**
 * Define the seaplane terminal variant of an airport.
 * It shares the state machine of the land airport, but only seaplanes may use it. Its movement data is derived
 * from the land airport's with MakeSeaplaneMovingData: shorter landings and a tighter holding pattern.
 * @param name Suffix of the names of the airport data.
 * @param num_helipads Number of heli pads (unused by seaplanes, kept so the state machine is unchanged).
 * @param short_strip Airport has a short land/take-off strip.
 */
#define SEAPLANE_AIRPORT(name, num_helipads, short_strip) \
	static const std::vector<AirportMovingData> _airport_moving_data_seaplane_ ## name = MakeSeaplaneMovingData(_airport_moving_data_ ## name); \
	static const AirportFTAClass _airportfta_seaplane_ ## name(_airport_moving_data_seaplane_ ## name.data(), _airport_terminal_ ## name, \
			num_helipads, _airport_entries_ ## name, \
			AirportFTAClass::Flags{AirportFTAClass::Flag::Seaplanes} | (short_strip ? AirportFTAClass::Flags{AirportFTAClass::Flag::ShortStrip} : AirportFTAClass::Flags{}), \
			_airport_fta_ ## name, 0);

SEAPLANE_AIRPORT(country, 0, true)
SEAPLANE_AIRPORT(city, 0, false)
SEAPLANE_AIRPORT(metropolitan, 0, false)
SEAPLANE_AIRPORT(international, 2, false)
SEAPLANE_AIRPORT(commuter, 2, true)
SEAPLANE_AIRPORT(intercontinental, 2, false)

/* Seaplane dock: a 1x2 dock with one berth and no hangar; it has no land counterpart. */
static const std::vector<AirportMovingData> _airport_moving_data_seaplane_dock_short = MakeSeaplaneMovingData(_airport_moving_data_seaplane_dock);
static const AirportFTAClass _airportfta_seaplane_dock(_airport_moving_data_seaplane_dock_short.data(), _airport_terminal_seaplane_dock,
		0, _airport_entries_seaplane_dock, AirportFTAClass::Flags({AirportFTAClass::Flag::Seaplanes, AirportFTAClass::Flag::ShortStrip}),
		_airport_fta_seaplane_dock, 0);

#undef SEAPLANE_AIRPORT
#undef HELIPORT
#undef AIRPORT
#undef AIRPORT_GENERIC

#include "table/airport_defaults.h"


static uint16_t AirportGetNofElements(const AirportFTAbuildup *apFA);
static void AirportBuildAutomata(std::vector<AirportFTA> &layout, uint8_t nofelements, const AirportFTAbuildup *apFA);


/**
 * Rotate the airport moving data to another rotation.
 * @param orig Pointer to the moving data to rotate.
 * @param rotation How to rotate the moving data.
 * @param num_tiles_x Number of tiles in x direction.
 * @param num_tiles_y Number of tiles in y direction.
 * @return The rotated moving data.
 */
AirportMovingData RotateAirportMovingData(const AirportMovingData *orig, Direction rotation, uint num_tiles_x, uint num_tiles_y)
{
	AirportMovingData amd;
	amd.flags = orig->flags;
	amd.direction = ChangeDir(orig->direction, static_cast<DirDiff>(rotation));
	switch (rotation) {
		case Direction::N:
			amd.x = orig->x;
			amd.y = orig->y;
			break;

		case Direction::E:
			amd.x = orig->y;
			amd.y = num_tiles_y * TILE_SIZE - orig->x - 1;
			break;

		case Direction::S:
			amd.x = num_tiles_x * TILE_SIZE - orig->x - 1;
			amd.y = num_tiles_y * TILE_SIZE - orig->y - 1;
			break;

		case Direction::W:
			amd.x = num_tiles_x * TILE_SIZE - orig->y - 1;
			amd.y = orig->x;
			break;

		default: NOT_REACHED();
	}
	return amd;
}

AirportFTAClass::AirportFTAClass(
	const AirportMovingData *moving_data_,
	const uint8_t *terminals_,
	const uint8_t num_helipads_,
	const uint8_t *entry_points_,
	Flags flags_,
	const AirportFTAbuildup *apFA,
	uint8_t delta_z_
) :
	moving_data(moving_data_),
	terminals(terminals_),
	num_helipads(num_helipads_),
	flags(flags_),
	nofelements(AirportGetNofElements(apFA)),
	entry_points(entry_points_),
	delta_z(delta_z_)
{
	/* Build the state machine itself */
	AirportBuildAutomata(this->layout, this->nofelements, apFA);
}

/**
 * Get the number of elements of a source Airport state automata
 * Since it is actually just a big array of AirportFTA types, we only
 * know one element from the other by differing 'position' identifiers
 * @param apFA The state machine builder.
 * @return The number of elements.
 */
static uint16_t AirportGetNofElements(const AirportFTAbuildup *apFA)
{
	uint16_t nofelements = 0;
	int temp = apFA[0].position;

	for (uint i = 0; i < MAX_ELEMENTS; i++) {
		if (temp != apFA[i].position) {
			nofelements++;
			temp = apFA[i].position;
		}
		if (apFA[i].position == MAX_ELEMENTS) break;
	}
	return nofelements;
}

AirportFTA::AirportFTA(const AirportFTAbuildup &buildup) : blocks(buildup.blocks), position(buildup.position), next_position(buildup.next), heading(buildup.heading)
{
}

/**
 * Construct the FTA given a description.
 * @param layout The vector to write the automata to.
 * @param nofelements The number of elements in the FTA.
 * @param apFA The description of the FTA.
 */
static void AirportBuildAutomata(std::vector<AirportFTA> &layout, uint8_t nofelements, const AirportFTAbuildup *apFA)
{
	uint16_t internalcounter = 0;

	layout.reserve(nofelements);
	for (uint i = 0; i < nofelements; i++) {
		AirportFTA *current = &layout.emplace_back(apFA[internalcounter]);

		/* outgoing nodes from the same position, create linked list */
		while (current->position == apFA[internalcounter + 1].position) {
			current->next = std::make_unique<AirportFTA>(apFA[internalcounter + 1]);
			current = current->next.get();
			internalcounter++;
		}
		internalcounter++;
	}
}

/**
 * Get the finite state machine of an airport type.
 * @param airport_type %Airport type to query FTA from. @see AirportTypes
 * @return Finite state machine of the airport.
 */
const AirportFTAClass *GetAirport(const uint8_t airport_type)
{
	if (airport_type == AT_DUMMY) return &_airportfta_dummy;
	return AirportSpec::Get(airport_type)->fsm;
}

/**
 * Get the seaplane terminal variant of a land airport state machine.
 * @param fta State machine of a land airport.
 * @return The seaplane variant, \a fta itself if it already is one, or \c nullptr if the airport has no seaplane variant (e.g. heliports).
 */
const AirportFTAClass *GetSeaplaneAirportFTA(const AirportFTAClass *fta)
{
	if (fta == nullptr || fta->IsSeaplaneTerminal()) return fta;
	if (fta == &_airportfta_country) return &_airportfta_seaplane_country;
	if (fta == &_airportfta_city) return &_airportfta_seaplane_city;
	if (fta == &_airportfta_metropolitan) return &_airportfta_seaplane_metropolitan;
	if (fta == &_airportfta_international) return &_airportfta_seaplane_international;
	if (fta == &_airportfta_commuter) return &_airportfta_seaplane_commuter;
	if (fta == &_airportfta_intercontinental) return &_airportfta_seaplane_intercontinental;
	return nullptr;
}

/**
 * Get the state machine of the seaplane dock: a 1x2 dock with one berth and no hangar,
 * where seaplanes land and take off on the water next to the dock.
 * @return The seaplane dock state machine.
 */
const AirportFTAClass *GetSeaplaneDockFTA()
{
	return &_airportfta_seaplane_dock;
}

/**
 * Get the vehicle position when an aircraft is build at the given tile
 * @param hangar_tile The tile on which the vehicle is build
 * @return The position (index in airport node array) where the aircraft ends up
 */
uint8_t GetVehiclePosOnBuild(TileIndex hangar_tile)
{
	const Station *st = Station::GetByTile(hangar_tile);
	const AirportFTAClass *apc = st->airport.GetFTA();
	/* When we click on hangar we know the tile it is on. By that we know
	 * its position in the array of depots the airport has.....we can search
	 * layout for #th position of depot. Since layout must start with a listing
	 * of all depots, it is simple */
	for (uint i = 0;; i++) {
		if (st->airport.GetHangarTile(i) == hangar_tile) {
			assert(apc->layout[i].heading == HANGAR);
			return apc->layout[i].position;
		}
	}
	NOT_REACHED();
}
