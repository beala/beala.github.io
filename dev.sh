#!/usr/bin/env bash
# Live preview of fluxcore.party at http://localhost:3000. The browser reloads when you save
# the landing page, the docs or the flasher theme.
#
# Builds the site in a few seconds (no firmware download: the preview fetches firmware from
# GitHub when the flasher asks for it), swaps the built landing page, docs and theme for links
# to your source files, and runs it with wrangler behind browser-sync.
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
# Serve the source files directly (the docs' "latest build" box stays empty in the preview)
ln -sf "$PWD/landing/index.html" _site/index.html
ln -sf "$PWD/flasher/docs/index.html" _site/docs/index.html
ln -sf "$PWD/flasher/theme/fluxcore.css" _site/flash/css/fluxcore.css

npx -y wrangler@4 dev --port 8787 --var PREVIEW:1 --var "FIRMWARE_REPO:$(jq -r .firmware_repo flasher/settings.json)" &
trap 'kill $! 2>/dev/null' EXIT
npx -y browser-sync@3 start --proxy localhost:8787 --port 3000 --no-open --no-notify --no-ui \
  --files landing flasher/docs flasher/theme
