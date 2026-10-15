#!/usr/bin/env bash
# Cloud Agent install: Node deps + observations.v2.jsonl (from FINN_OBSERVATIONS_V2_URL or OSF default).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f package-lock.json ]]; then
  npm ci
else
  npm install
fi

python3 scripts/fetch_observations_v2.py

# Optional: stitch forskningsrapport parts if only parts exist (GitHub MCP upload)
if [[ ! -f reports/forskningsrapport.md ]] && ls reports/forskningsrapport.md.part.* >/dev/null 2>&1; then
  cat reports/forskningsrapport.md.part.* > reports/forskningsrapport.md
  echo "stitched reports/forskningsrapport.md"
fi

# Unpack gzip+b64 analysis sidecars if present and targets missing
if [[ -f scripts/unpack_gz_sidecars.py ]]; then
  python3 scripts/unpack_gz_sidecars.py || true
fi

echo "cloud-agent-install: done"
