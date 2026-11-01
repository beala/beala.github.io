#!/usr/bin/env python3
"""Builds a static copy of the MeshCore web flasher that serves firmware from your own releases.

The official flasher (meshcore-dev/flasher.meshcore.io) is a static site, but it gets its firmware
list from a server endpoint, /releases. This script replaces that endpoint with static files:

  <out>/releases          JSON list of releases, as the flasher's /releases endpoint returns it
  <out>/fw/<tag>/<file>   firmware files from those releases (same origin, so the browser can fetch them)
  <out>/firmware/<file>   erase images and bootloaders referenced by the device catalog
  <out>/config.json       the official device catalog, cut down to the devices in settings.json

Usage: build.py <flasher checkout> <output dir>
Set GITHUB_TOKEN to avoid API rate limits.
"""
import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OFFICIAL_STATIC = "https://flasher.meshcore.io/firmware"


def fetch(url, accept=None):
    headers = {"User-Agent": "beala-flasher-build"}
    if accept:
        headers["Accept"] = accept
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as res:
        return res.read()


def release_source_key(firmware):
    return next((k for k in firmware if k.startswith("github")), None)


def main(flasher_dir, out_dir):
    settings = json.loads((HERE / "settings.json").read_text())
    flasher_dir, out = Path(flasher_dir), Path(out_dir)

    # 1. The flasher itself
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(flasher_dir, out, ignore=shutil.ignore_patterns(".git", ".github"))
    (out / ".nojekyll").touch()
    index = out / "index.html"
    index.write_text(re.sub(r"<title>.*?</title>", f"<title>{settings['title']}</title>", index.read_text(), count=1))

    # 2. Device catalog: only our devices, and only firmware that comes from GitHub releases
    config = json.loads((out / "config.json").read_text())
    by_name = {d["name"]: d for d in config["device"]}
    missing = [n for n in settings["devices"] if n not in by_name]
    if missing:
        sys.exit(f"Devices not in the flasher catalog (check the names): {missing}")
    devices = []
    for name in settings["devices"]:
        device = by_name[name]
        device["firmware"] = [fw for fw in device["firmware"] if release_source_key(fw)]
        devices.append(device)
    config["device"] = devices
    (out / "config.json").write_text(json.dumps(config, indent=1))

    patterns = [re.compile(p) for d in devices for fw in d["firmware"]
                for p in fw[release_source_key(fw)]["files"].values()]
    release_types = sorted({fw[release_source_key(fw)]["type"] for d in devices for fw in d["firmware"]})

    # 3. Erase images and bootloaders, copied from the official flasher
    static_files = set()
    for d in devices:
        if d.get("erase"):
            static_files.add(d["erase"])
        static_files.update(d.get("bootloader", []))
    (out / "firmware").mkdir(exist_ok=True)
    for name in sorted(static_files):
        try:
            (out / "firmware" / name).write_bytes(fetch(f"{OFFICIAL_STATIC}/{name}"))
            print(f"static   {name}")
        except Exception as e:  # keep going: the flasher still works, only that link breaks
            print(f"WARNING: could not copy {name}: {e}")

    # 4. Our releases, newest first
    api = f"https://api.github.com/repos/{settings['firmware_repo']}/releases?per_page=100"
    releases = [r for r in json.loads(fetch(api, "application/vnd.github+json"))
                if not r["draft"] and r["tag_name"].startswith(settings["release_tag_prefix"])]
    releases = releases[: settings["keep_releases"]]
    if not releases:
        sys.exit(f"No releases tagged {settings['release_tag_prefix']}* in {settings['firmware_repo']}")

    catalog = []
    for r in releases:
        tag = r["tag_name"]
        files = []
        for asset in r["assets"]:
            if not any(p.search(asset["name"]) for p in patterns):
                continue
            dest = out / "fw" / tag / asset["name"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(fetch(asset["browser_download_url"]))
            files.append({"name": asset["name"], "url": f"/fw/{tag}/{asset['name']}"})
        print(f"release  {tag}: {len(files)} files")
        # The flasher shows notes as plain text with URLs auto-linked, so flatten Markdown links
        notes = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1: \2", r["body"] or "")
        # One release holds every role, so list it once per release type the catalog asks for
        for t in release_types:
            catalog.append({"version": r["name"] or tag, "type": t, "name": r["name"] or tag,
                            "notes": notes, "files": files})

    (out / "releases").write_text(json.dumps(catalog))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
