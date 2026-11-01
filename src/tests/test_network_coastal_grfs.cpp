/*
 * This file is part of OpenTTD.
 * OpenTTD is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 2.
 * OpenTTD is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See the GNU General Public License for more details. You should have received a copy of the GNU General Public License along with OpenTTD. If not, see <https://www.gnu.org/licenses/old-licenses/gpl-2.0>.
 */

/** @file test_network_coastal_grfs.cpp Tests for the Coastal GrfLink release asset names. */

#include "../stdafx.h"

#include "../3rdparty/catch2/catch.hpp"

#include "../network/network_coastal_grfs.h"

TEST_CASE("ParseCoastalGrfAssetName")
{
	auto a = ParseCoastalGrfAssetName("bcferries-v8.tar");
	REQUIRE(a.has_value());
	CHECK(a->set == "bcferries");
	CHECK(a->version == 8);

	a = ParseCoastalGrfAssetName("coastal-waterfront-v12.tar");
	REQUIRE(a.has_value());
	CHECK(a->set == "coastal-waterfront");
	CHECK(a->version == 12);

	CHECK_FALSE(ParseCoastalGrfAssetName("bcferries-v8.tar.gz").has_value());
	CHECK_FALSE(ParseCoastalGrfAssetName("bcferries-v.tar").has_value());
	CHECK_FALSE(ParseCoastalGrfAssetName("bcferries-v8a.tar").has_value());
	CHECK_FALSE(ParseCoastalGrfAssetName("-v8.tar").has_value());
	CHECK_FALSE(ParseCoastalGrfAssetName("../evil-v1.tar").has_value());
	CHECK_FALSE(ParseCoastalGrfAssetName("a/b-v1.tar").has_value());
	CHECK_FALSE(ParseCoastalGrfAssetName("Upper-v1.tar").has_value());
}
