/*
 * This file is part of OpenTTD.
 * OpenTTD is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 2.
 * OpenTTD is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See the GNU General Public License for more details. You should have received a copy of the GNU General Public License along with OpenTTD. If not, see <https://www.gnu.org/licenses/old-licenses/gpl-2.0>.
 */

/** @file network_coastal_grfs.h TGTFTD: keep the Coastal GrfLink NewGRFs up to date. */

#ifndef NETWORK_COASTAL_GRFS_H
#define NETWORK_COASTAL_GRFS_H

#include <optional>
#include <string>
#include <string_view>

void NetworkCoastalGrfSync();

/** A release asset named <set>-v<version>.tar. */
struct CoastalGrfAsset {
	std::string set;
	int version;
};

std::optional<CoastalGrfAsset> ParseCoastalGrfAssetName(std::string_view name);

#endif /* NETWORK_COASTAL_GRFS_H */
