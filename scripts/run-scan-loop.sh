#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_ROOT="${STATE_ROOT:-$ROOT/.agent-serve/scan-state}"
LOG="${LOG:-$STATE_ROOT/scan.log}"
MAX_BATCHES="${MAX_BATCHES:-400}"
MAX_ADS="${MAX_ADS:-50}"
DELAY_MS="${DELAY_MS:-150}"

mkdir -p "$STATE_ROOT"
cd "$ROOT"

echo "scan start $(date -Is) state=$STATE_ROOT" | tee -a "$LOG"

for i in $(seq 1 "$MAX_BATCHES"); do
  echo "=== batch $i $(date -Is) ===" | tee -a "$LOG"
  OUT_FILE="$STATE_ROOT/last-batch.json.txt"
  npx --yes "@cursor/bdk@0.2.24" call scan_jobs_batch \
    --dir . \
    --state-root "$STATE_ROOT" \
    --input "{\"maxAds\":$MAX_ADS,\"delayMs\":$DELAY_MS}" \
    >"$OUT_FILE" 2>&1 || true
  cat "$OUT_FILE" >>"$LOG"

  set +e
  SUMMARY="$(python3 - "$i" "$OUT_FILE" <<'PY'
import json, re, sys
batch_no = sys.argv[1]
text = open(sys.argv[2], encoding="utf-8", errors="replace").read()
matches = list(re.finditer(r"\{[\s\S]*\}", text))
if not matches:
    print("PARSE_FAIL")
    sys.exit(2)
obj = None
for m in reversed(matches):
    try:
        candidate = json.loads(m.group(0))
    except json.JSONDecodeError:
        continue
    if isinstance(candidate, dict) and "result" in candidate:
        obj = candidate
        break
if obj is None:
    print("PARSE_FAIL")
    sys.exit(2)
if not obj.get("ok"):
    print("CALL_FAIL")
    sys.exit(3)
r = obj["result"]
s = r["summary"]
c = s["counts"]
print(
    f"batch={batch_no} processed={r['processedThisBatch']} "
    f"classified={s['classified']} unique={s['uniqueSeen']} "
    f"asks={c['asks']} silent={c['silent']} rejects={c['rejects']} errors={c['errors']} "
    f"status={s['status']} industry={s.get('currentIndustry')} page={s['page']}"
)
sys.exit(0 if s["status"] == "complete" else 1)
PY
)"
  status=$?
  set -e

  echo "$SUMMARY" | tee -a "$LOG"

  if [[ "$SUMMARY" == PARSE_FAIL* || "$SUMMARY" == CALL_FAIL* ]]; then
    echo "stopping due to failure" | tee -a "$LOG"
    exit 1
  fi
  if [[ $status -eq 0 ]]; then
    echo "COMPLETE $(date -Is)" | tee -a "$LOG"
    exit 0
  fi
done

echo "scan end $(date -Is) (max batches reached)" | tee -a "$LOG"
