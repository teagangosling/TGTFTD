/*
 * This file is part of OpenTTD.
 * OpenTTD is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, version 2.
 * OpenTTD is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See the GNU General Public License for more details. You should have received a copy of the GNU General Public License along with OpenTTD. If not, see <https://www.gnu.org/licenses/old-licenses/gpl-2.0>.
 */

/**
 * @file network_coastal_grfs.cpp TGTFTD: keep the Coastal GrfLink NewGRFs up to date.
 *
 * At startup the GitHub releases of talonfast/coastal-grflink are listed. For every set, the newest
 * <set>-v<N>.tar that is not in any newgrf search path yet (as the tar or its unpacked folder) is downloaded into content_download/newgrf,
 * older versions of that set in content_download/newgrf are removed, and the NewGRFs are rescanned.
 * Tars the player put in their own newgrf folder are never touched.
 */

#include "../stdafx.h"
#include "network_coastal_grfs.h"
#include "core/http.h"
#include "../debug.h"
#include "../error.h"
#include "../fileio_func.h"
#include "../openttd.h"
#include "../strings_func.h"

#include "../3rdparty/nlohmann/json.hpp"

#include "table/strings.h"

#include <charconv>
#include <filesystem>
#include <map>

#include "../safeguards.h"

static constexpr std::string_view RELEASES_URI = "https://api.github.com/repos/talonfast/coastal-grflink/releases?per_page=100";
static constexpr std::string_view DOWNLOAD_PREFIX = "https://github.com/talonfast/coastal-grflink/releases/download/";

/**
 * Parse a release asset name. Only lowercase letters, digits and '-' are accepted in the set name, as the
 * name becomes a file name (no path separators or "..").
 * @param name Asset name, such as "bcferries-v8.tar".
 * @return The set and version, or std::nullopt when it is not a GRF tar name.
 */
std::optional<CoastalGrfAsset> ParseCoastalGrfAssetName(std::string_view name)
{
	if (!name.ends_with(".tar")) return std::nullopt;
	name.remove_suffix(4);
	size_t v = name.rfind("-v");
	if (v == std::string_view::npos || v == 0) return std::nullopt;

	std::string_view set = name.substr(0, v);
	std::string_view digits = name.substr(v + 2);
	for (char c : set) {
		if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) return std::nullopt;
	}

	int version;
	auto [end, ec] = std::from_chars(digits.data(), digits.data() + digits.size(), version);
	if (digits.empty() || ec != std::errc{} || end != digits.data() + digits.size()) return std::nullopt;
	return CoastalGrfAsset{std::string(set), version};
}

class CoastalGrfSync : public HTTPCallback {
	struct Download {
		std::string set;
		std::string name; ///< File name, <set>-v<N>.tar.
		std::string url;
	};

	std::vector<char> response;
	bool listing = true; ///< Receiving the release list, not a tar.
	std::vector<Download> queue; ///< Tars still to download; the front one is in flight.
	std::string downloaded; ///< Names of the downloaded tars, for the message.

	void ParseReleases()
	{
		nlohmann::json releases = nlohmann::json::parse(this->response.begin(), this->response.end(), nullptr, false);
		if (!releases.is_array()) {
			Debug(net, 0, "Coastal GrfLink: unexpected release list");
			return;
		}

		std::map<std::string, std::pair<int, Download>> newest;
		for (const auto &release : releases) {
			if (!release.is_object() || !release.contains("assets") || !release["assets"].is_array()) continue;
			for (const auto &asset : release["assets"]) {
				if (!asset.is_object() || !asset.contains("name") || !asset["name"].is_string()) continue;
				if (!asset.contains("browser_download_url") || !asset["browser_download_url"].is_string()) continue;
				std::string name = asset["name"].get<std::string>();
				std::string url = asset["browser_download_url"].get<std::string>();
				auto parsed = ParseCoastalGrfAssetName(name);
				if (!parsed.has_value() || !url.starts_with(DOWNLOAD_PREFIX)) continue;

				auto it = newest.find(parsed->set);
				if (it == newest.end() || parsed->version > it->second.first) {
					newest[parsed->set] = {parsed->version, Download{parsed->set, name, url}};
				}
			}
		}

		for (auto &[set, entry] : newest) {
			/* Installed as the tar, or as the folder it unpacks to. */
			std::string_view stem = std::string_view(entry.second.name).substr(0, entry.second.name.size() - 4);
			if (FioFindFullPath(Subdirectory::NewGrf, entry.second.name).empty() && FioFindFullPath(Subdirectory::NewGrf, stem).empty()) {
				this->queue.push_back(std::move(entry.second));
			} else {
				Debug(net, 3, "Coastal GrfLink: {} is up to date", entry.second.name);
			}
		}
	}

	void SaveDownload(const Download &d)
	{
		std::string dir = FioGetDirectory(Searchpath::AutodownloadDir, Subdirectory::NewGrf);
		std::string part = dir + d.name + ".part";
		{
			auto f = FileHandle::Open(part, "wb");
			if (!f.has_value() || fwrite(this->response.data(), 1, this->response.size(), *f) != this->response.size()) {
				Debug(net, 0, "Coastal GrfLink: could not write {}", part);
				f.reset();
				FioRemove(part);
				return;
			}
		}

		std::error_code ec;
		std::filesystem::rename(OTTD2FS(part), OTTD2FS(dir + d.name), ec);
		if (ec) {
			Debug(net, 0, "Coastal GrfLink: could not rename {}: {}", part, ec.message());
			FioRemove(part);
			return;
		}
		Debug(net, 1, "Coastal GrfLink: downloaded {}", d.name);
		if (!this->downloaded.empty()) this->downloaded += ", ";
		this->downloaded += d.name;

		/* Remove older versions of this set that we downloaded before. */
		for (const auto &entry : std::filesystem::directory_iterator(OTTD2FS(dir), ec)) {
			std::string file = FS2OTTD(entry.path().filename().native());
			auto parsed = ParseCoastalGrfAssetName(file);
			if (parsed.has_value() && parsed->set == d.set && file != d.name) {
				Debug(net, 1, "Coastal GrfLink: removing {}", file);
				FioRemove(dir + file);
			}
		}
	}

	void Next()
	{
		this->response.clear();
		if (!this->queue.empty()) {
			NetworkHTTPSocketHandler::Connect(this->queue.front().url, this);
			return;
		}
		if (this->downloaded.empty()) return;

		RequestNewGRFScan();
		ShowErrorMessage(GetEncodedString(STR_COASTAL_GRFS_UPDATED, this->downloaded), {}, WarningLevel::Info);
	}

public:
	void Start()
	{
		NetworkHTTPSocketHandler::Connect(RELEASES_URI, this);
	}

	void OnFailure() override
	{
		if (this->listing) {
			Debug(net, 1, "Coastal GrfLink: could not list the releases");
			return;
		}
		Debug(net, 0, "Coastal GrfLink: could not download {}", this->queue.front().name);
		this->queue.erase(this->queue.begin());
		this->Next();
	}

	void OnReceiveData(UniqueBuffer<char> data) override
	{
		if (data != nullptr) {
			this->response.insert(this->response.end(), data.get(), data.get() + data.size());
			return;
		}

		if (this->listing) {
			this->listing = false;
			this->ParseReleases();
		} else {
			this->SaveDownload(this->queue.front());
			this->queue.erase(this->queue.begin());
		}
		this->Next();
	}

	bool IsCancelled() const override
	{
		return false;
	}
};

static CoastalGrfSync _coastal_grf_sync;

/** Check for and download newer Coastal GrfLink GRFs, in the background. */
void NetworkCoastalGrfSync()
{
	_coastal_grf_sync.Start();
}
