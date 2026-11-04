#!/usr/bin/env python3
"""Builds a static copy of the MeshCore web flasher that serves firmware from your own releases.

The official flasher (meshcore-dev/flasher.meshcore.io) is a static site, but it gets its firmware
list from a server endpoint, /releases. This script replaces that endpoint with static files:

  <out>/releases          JSON list of releases, as the flasher's /releases endpoint returns it
  <out>/fw/<tag>/<file>   firmware files from those releases (same origin, so the browser can fetch them)
  <out>/firmware/<file>   erase images and bootloaders referenced by the device catalog
  <out>/config.json       the official device catalog, cut down to the devices in settings.json
  <out>/docs/             docs page (flasher/docs), with the latest build filled in

Usage: build.py <flasher checkout> <output dir>
Set GITHUB_TOKEN to avoid API rate limits.
"""
import html
import json
import os
import re
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
OFFICIAL_STATIC = "https://flasher.meshcore.io/firmware"


# Errors worth another try: rate limiting and server-side failures. Anything else (404, 401, 403,
# a bad URL) fails at once, since trying again won't change the answer.
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_WAITS = [5, 15, 30]   # seconds before each retry, so at most 4 attempts


def fetch(url, accept=None):
    headers = {"User-Agent": "fluxcore-flasher-build"}
    if accept:
        headers["Accept"] = accept
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as res:
                return res.read()
        except urllib.error.HTTPError as e:
            if e.code not in RETRY_STATUS or attempt == len(RETRY_WAITS):
                raise
            wait = RETRY_WAITS[attempt]
            if e.code == 429 and (e.headers.get("Retry-After") or "").isdigit():
                wait = min(int(e.headers["Retry-After"]), 60)
            reason = f"HTTP {e.code}"
        except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
            if attempt == len(RETRY_WAITS):
                raise
            wait = RETRY_WAITS[attempt]
            reason = str(getattr(e, "reason", e))
        print(f"fetch {url}: {reason}, retrying in {wait} s", file=sys.stderr)
        time.sleep(wait)


# Links to the docs and the home page, pinned to a corner of the flasher
CORNER_LINKS = ('<div class="fc-corner"><a href="https://fluxcore.party/">fluxcore.party</a>'
                '<a class="fc-primary" href="/docs/">Docs &amp; what\'s different</a></div>')

# FluxCore logo, in place of the MeshCore logo image in the flasher's header
LOGO_OLD = '<img :src="`/img/${logoFile}`" v-if="!isIframe"> <span>flasher</span>'
LOGO_NEW = ('<span class="fc-logo"><a href="https://fluxcore.party/">fluxcore<span class="fc-cursor"></span></a>'
            '<span class="fc-sub">flasher</span></span>')


def theme(page):
    """Restyles the flasher page to match fluxcore.party (flasher/theme/fluxcore.css)."""
    for old, new in [
        ('<link href="/css/flasher.css" rel="stylesheet">',
         '<link href="/css/flasher.css" rel="stylesheet">\n  <link href="/css/fluxcore.css" rel="stylesheet">'),
        ('<body class="dark">', '<body class="light fluxcore">'),
        (LOGO_OLD, LOGO_NEW),
    ]:
        if old not in page:
            print(f"WARNING: flasher page changed, theme step skipped: {old}")
        page = page.replace(old, new, 1)
    return page.replace("</body>", CORNER_LINKS + "</body>", 1)


def latest_build_html(release):
    """Summary of a release for the docs page: its name, and the branches it was built from."""
    name = html.escape(release["name"] or release["tag_name"])
    out = f'<p><a href="{html.escape(release["html_url"])}"><strong>{name}</strong></a>'
    out += f' &middot; tag <code>{html.escape(release["tag_name"])}</code></p>'
    body = release["body"] or ""
    branches = re.findall(r"^- \[([^\]]+)\]\((https?://[^)\s]+)\)", body, re.M)
    since = re.search(r"^Changes since (\S+):", body, re.M)
    if branches:   # older releases, built from upstream dev plus a list of branches
        out += "<p>Built from upstream <code>dev</code> plus:</p><ul>"
        out += "".join(f'<li><a href="{html.escape(u)}"><code>{html.escape(b)}</code></a></li>' for b, u in branches)
        out += "</ul>"
    elif since:    # releases from beala/main list what changed since the previous one
        changes = re.findall(r"^- (.+)$", body[since.end():], re.M)
        out += f"<p>Changes since <code>{html.escape(since.group(1))}</code>:</p><ul>"
        out += "".join(f"<li>{html.escape(c)}</li>" for c in changes)
        out += "</ul>"
    diff = re.search(r"https://github\.com/\S+/compare/\S+", release["body"] or "")
    if diff:
        out += f'<p><a href="{html.escape(diff.group(0))}">Full diff against upstream</a></p>'
    return out


def release_label(release):
    """'2026-11-02 14:05 UTC (fd14442)': date and time, so builds from the same day can be told apart."""
    when = (release.get("published_at") or release["created_at"]).replace("T", " ")[:16]
    sha = release["tag_name"].split("-", 1)[-1]
    return f"{when} UTC ({sha})"


def release_source_key(firmware):
    return next((k for k in firmware if k.startswith("github")), None)


def main(flasher_dir, out_dir):
    settings = json.loads((HERE / "settings.json").read_text())
    flasher_dir, out = Path(flasher_dir), Path(out_dir)

    # 1. The flasher itself
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(flasher_dir, out, ignore=shutil.ignore_patterns(".git", ".github"))
    index = out / "index.html"
    page = re.sub(r"<title>.*?</title>", f"<title>{settings['title']}</title>", index.read_text(), count=1)
    page = theme(page)
    index.write_text(page)
    shutil.copy(HERE / "theme" / "fluxcore.css", out / "css" / "fluxcore.css")
    # The flasher keeps its state in the URL path (/device/role/version). There are no files at those
    # paths: Cloudflare serves index.html for them (not_found_handling in flasher/wrangler.jsonc).
    # The release list and catalog are fetched by script, and a host may let browsers cache them for
    # minutes (a hard refresh doesn't cover script fetches). Revalidate every time instead: the
    # browser keeps its copy and only re-downloads when the file changed.
    util = out / "js" / "util.js"
    code = util.read_text()
    if "const res = await fetch(url);" in code:
        util.write_text(code.replace("const res = await fetch(url);", "const res = await fetch(url, { cache: 'no-cache' });", 1))
    else:
        print("WARNING: flasher's fetchJson changed, release list may be cached for up to 10 minutes")

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
    # GitHub's order isn't reliably by date, and the flasher shows them in the order given
    # (first one selected), so sort by when each was published, newest first.
    releases.sort(key=lambda r: r.get("published_at") or r["created_at"], reverse=True)
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
            label = release_label(r)
            catalog.append({"version": label, "type": t, "name": label,
                            "notes": notes, "files": files})

    (out / "releases").write_text(json.dumps(catalog))

    # 5. Docs page
    docs = out / "docs"
    shutil.copytree(HERE / "docs", docs)
    page = (docs / "index.html").read_text()
    (docs / "index.html").write_text(page.replace("<!--LATEST-->", latest_build_html(releases[0])))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
