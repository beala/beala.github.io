#!/usr/bin/env bash
# Live preview of fluxcore.party at http://localhost:8787
#
# Builds the site in a few seconds (no firmware download: the preview fetches firmware from
# GitHub when the flasher asks for it), then copies your edits to the landing page, the docs and
# the flasher theme into the preview as you save. Refresh the browser to see them.
# Changes to build.py or settings.json need a restart (Ctrl+C, then ./dev.sh again).
set -euo pipefail
cd "$(dirname "$0")"

# The upstream flasher, at the commit the site uses
COMMIT=$(jq -r .flasher_commit flasher/settings.json)
REPO=$(jq -r .flasher_repo flasher/settings.json)
if [ "$(git -C .flasher rev-parse HEAD 2>/dev/null)" != "$COMMIT" ]; then
  rm -rf .flasher && git init -q .flasher
  git -C .flasher fetch -q --depth 1 "$REPO" "$COMMIT" && git -C .flasher checkout -q FETCH_HEAD
fi

rm -rf _site
GITHUB_TOKEN=${GITHUB_TOKEN:-$(gh auth token 2>/dev/null || true)} python3 flasher/build.py --preview .flasher _site >/dev/null

# Copy edits into the preview as they're saved
python3 - <<'EOF' &
import re, shutil, time
from pathlib import Path
pairs = {}  # source file -> preview file
for f in Path("landing").rglob("*"):
    if f.is_file(): pairs[f] = Path("_site") / f.relative_to("landing")
for f in Path("flasher/docs").rglob("*"):
    if f.is_file(): pairs[f] = Path("_site/docs") / f.relative_to("flasher/docs")
pairs[Path("flasher/theme/fluxcore.css")] = Path("_site/flash/css/fluxcore.css")
# Keep the "latest build" box the full build filled into the docs
built = Path("_site/docs/index.html").read_text()
src = Path("flasher/docs/index.html").read_text()
a, b = src.split("<!--LATEST-->") if "<!--LATEST-->" in src else (src, "")
latest = built[len(a):len(built) - len(b)] if b and built.startswith(a) and built.endswith(b) else ""
seen = {f: f.stat().st_mtime for f in pairs}
while True:
    time.sleep(0.5)
    for f, dest in pairs.items():
        m = f.stat().st_mtime
        if m != seen[f]:
            seen[f] = m
            if f.name == "index.html" and f.parent.as_posix() == "flasher/docs":
                dest.write_text(f.read_text().replace("<!--LATEST-->", latest))
            else:
                shutil.copy(f, dest)
            print(f"updated {dest}", flush=True)
EOF
WATCHER=$!
trap 'kill $WATCHER 2>/dev/null' EXIT

npx -y wrangler@4 dev --port 8787 --var PREVIEW:1 --var "FIRMWARE_REPO:$(jq -r .firmware_repo flasher/settings.json)"
