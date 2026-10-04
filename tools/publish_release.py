#!/usr/bin/env python3
"""
Publish a TGTFTD GitHub release from this machine, using the bundles built by the "Release" workflow.

    python tools/publish_release.py [--run RUN_ID] [--wait] [--tag TAG]

Releases are created locally, not by GitHub Actions: the Actions token may not create tags/releases here
(403 "Resource not accessible by integration"). The Release workflow only builds the bundles.

* --run: the Release workflow run to publish (default: the newest one).
* --wait: wait for the Windows and macOS builds of that run to finish first.
* --tag: the release tag; by default the version the run's Source job determined (e.g. tgtftd-0.1.1), read from its log.
  (The bundle file names use the version data committed in the source, e.g. jgrpp-0.73.3, so they don't give the tag.) Each Actions artifact is a
zip wrapping the real bundle files; they are unwrapped, so the release has the plain .zip/.dmg files (no zip in a zip).
Re-running replaces assets with the same name. Authentication uses the GitHub credentials stored for git.
"""

import io
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

REPO = "teagangosling/TGTFTD"
API = f"https://api.github.com/repos/{REPO}"
BUNDLES = ("openttd-windows-", "openttd-macos-")

BODY = """TGTFTD build {version}, based on JGR's Patch Pack.

* **Windows (x64)**: download the `windows-win64` zip, extract it and run `openttd.exe`.
* **macOS (Apple Silicon, M1 or newer)**: download the `macos` zip (or the `.dmg`) and extract it. The app is not signed by Apple: right-click it and choose **Open** the first time, or run `xattr -dr com.apple.quarantine /path/to/OpenTTD.app`.

You still need base graphics (OpenGFX can be downloaded from the in-game "Check online content" menu, or copy the original TTD files).

Seaplane and seaplane terminal NewGRF documentation: see `docs/tgtftd-seaplanes.md` in the repository.
"""


def token() -> str:
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)["password"]


TOKEN = token()
HEADERS = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github+json"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api(method, url, data=None, content_type="application/json"):
    if not url.startswith("http"):
        url = API + url
    body = data if isinstance(data, (bytes, type(None))) else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers={**HEADERS, "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"{method} {url}: {e.code} {e.read().decode(errors='replace')}") from e


def download_artifact(artifact_id) -> bytes:
    """Artifact downloads redirect to blob storage, which must not get the GitHub token."""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(urllib.request.Request(f"{API}/actions/artifacts/{artifact_id}/zip", headers=HEADERS))
        raise RuntimeError("expected a redirect")
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise
        location = e.headers["Location"]
    with urllib.request.urlopen(location) as r:
        return r.read()


def job_log(job_id) -> str:
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(urllib.request.Request(f"{API}/actions/jobs/{job_id}/logs", headers=HEADERS))
        raise RuntimeError("expected a redirect")
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise
        location = e.headers["Location"]
    with urllib.request.urlopen(location) as r:
        return r.read().decode(errors="replace")


def source_version(jobs) -> str | None:
    """The version printed by the Source job ("Version: ..." in its metadata step)."""
    for job in jobs:
        if job["name"].startswith("Source"):
            # The last "Version:" line is the metadata step's; earlier ones come from tool installers.
            found = re.findall(r"^\S+ Version: (\S+)\s*$", job_log(job["id"]), re.M)
            if found:
                return found[-1]
    return None


def main():
    args = sys.argv[1:]
    run_id = args[args.index("--run") + 1] if "--run" in args else None
    if run_id is None:
        run_id = api("GET", "/actions/workflows/release.yml/runs?per_page=1")["workflow_runs"][0]["id"]
    run = api("GET", f"/actions/runs/{run_id}")
    print(f"run {run_id}: {run['status']} {run['conclusion']} ({run['html_url']})")

    while True:
        jobs = api("GET", f"/actions/runs/{run_id}/jobs?per_page=50")["jobs"]
        builds = [j for j in jobs if j["name"].startswith(("Windows", "MacOS"))]
        if builds and all(j["status"] == "completed" for j in builds):
            break
        if "--wait" not in args:
            sys.exit("builds are not finished yet; use --wait")
        print("waiting for builds:", ", ".join(f"{j['name']}={j['status']}" for j in builds) or "not started")
        time.sleep(60)
    failed = [j["name"] for j in builds if j["conclusion"] != "success"]
    if failed:
        sys.exit(f"builds failed: {failed}")

    files = {}
    for art in api("GET", f"/actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]:
        if not art["name"].startswith(BUNDLES):
            continue
        with zipfile.ZipFile(io.BytesIO(download_artifact(art["id"]))) as z:
            for info in z.infolist():
                if not info.is_dir():
                    files[info.filename.rsplit("/", 1)[-1]] = z.read(info)
    if not files:
        sys.exit("no bundles found in the run's artifacts")

    version = args[args.index("--tag") + 1] if "--tag" in args else source_version(jobs)
    if not version:
        sys.exit("could not read the version from the Source job log; pass --tag")
    sha = run["head_sha"]
    tag_ref = api("GET", f"/git/ref/tags/{version}")
    if tag_ref is not None:
        obj = tag_ref["object"]
        sha = api("GET", f"/git/tags/{obj['sha']}")["object"]["sha"] if obj["type"] == "tag" else obj["sha"]
    print(f"version {version} at {sha[:10]}: {', '.join(sorted(files))}")

    rel = api("GET", f"/releases/tags/{version}")
    if rel is None:
        rel = api("POST", "/releases", {
            "tag_name": version, "target_commitish": sha, "name": f"TGTFTD {version}",
            "body": BODY.format(version=version), "prerelease": not version.startswith("tgtftd-"),
        })
        print(f"created release {version}")
    existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
    upload_url = rel["upload_url"].split("{")[0]
    for name, data in sorted(files.items()):
        if name in existing:
            api("DELETE", f"/releases/assets/{existing[name]}")
        ctype = "application/zip" if name.endswith(".zip") else "application/octet-stream"
        api("POST", f"{upload_url}?name={name}", data, content_type=ctype)
        print(f"uploaded {name} ({len(data) / 1e6:.1f} MB)")
    print(rel["html_url"])


if __name__ == "__main__":
    main()
