#!/usr/bin/env python3
"""Export a deterministic stratified audit sample from scan.log labels.

Default locks the log prefix to the 2026-10-14 audit population
(asks=373, silent=6139, rejects=37) so the sample is reproducible.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / ".agent-serve" / "scan-state" / "scan.log"
OUT = ROOT / "data" / "audit-sample.json"

# Population counts at the moment of the first formal audit.
DEFAULT_LOCK = {"asks": 373, "silent": 6139, "rejects": 37}


def iter_batch_items(text: str):
    for m in re.finditer(r'\{\s*"ok":\s*true[\s\S]*?\n\}', text):
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if obj.get("toolName") != "scan_jobs_batch":
            continue
        for item in obj.get("result", {}).get("batch") or []:
            yield item


def load_labels_locked(lock: dict[str, int] | None) -> dict[str, list[str]]:
    text = LOG.read_text(encoding="utf-8", errors="replace")
    by_cat: dict[str, dict[str, dict]] = {
        "asks": {},
        "silent": {},
        "rejects": {},
        "error": {},
    }
    for item in iter_batch_items(text):
        cat = item.get("category")
        ad_id = str(item.get("id") or "")
        if cat not in by_cat or not ad_id or ad_id in by_cat[cat]:
            continue
        by_cat[cat][ad_id] = item
        if lock and all(len(by_cat[k]) >= lock[k] for k in lock):
            break
    if lock:
        for k, n in lock.items():
            if len(by_cat[k]) < n:
                raise SystemExit(
                    f"Cannot lock population: have {len(by_cat[k])} {k}, need {n}"
                )
            # Truncate to exact locked sizes in first-seen order
            by_cat[k] = dict(list(by_cat[k].items())[:n])
    # Preserve first-seen insertion order (do NOT sort before shuffle).
    return {k: list(v.keys()) for k, v in by_cat.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=14)
    parser.add_argument("--asks", type=int, default=100)
    parser.add_argument("--silent", type=int, default=100)
    parser.add_argument(
        "--lock-audit-population",
        action="store_true",
        default=True,
        help="Lock log prefix to asks=373,silent=6139,rejects=37 (default on)",
    )
    parser.add_argument(
        "--no-lock-audit-population",
        action="store_true",
        help="Use the full current scan.log population instead",
    )
    args = parser.parse_args()

    lock = None if args.no_lock_audit_population else DEFAULT_LOCK
    labels = load_labels_locked(lock)
    rng = random.Random(args.seed)

    asks = list(labels["asks"])
    silent = list(labels["silent"])
    rejects = list(labels["rejects"])
    rng.shuffle(asks)
    rng.shuffle(silent)

    doc = {
        "method": {
            "type": "stratified_random_within_predicted_class",
            "seed": args.seed,
            "generator": (
                "Python random.Random(seed); list.shuffle on first-seen "
                "scan.log insertion order; take first n"
            ),
            "populationSource": str(LOG.relative_to(ROOT)),
            "populationLock": lock,
            "wasRandom": True,
            "randomDetails": (
                "Independent shuffle within asks and within silent. "
                "Rejects audited as a census (all ids in the locked population)."
            ),
            "strata": {
                "asks": {
                    "populationSize": len(labels["asks"]),
                    "sampleSize": min(args.asks, len(asks)),
                    "method": f"SRS within asks, n={args.asks}",
                },
                "silent": {
                    "populationSize": len(labels["silent"]),
                    "sampleSize": min(args.silent, len(silent)),
                    "method": f"SRS within silent, n={args.silent}",
                },
                "rejects": {
                    "populationSize": len(rejects),
                    "sampleSize": len(rejects),
                    "method": "census (all rejects ids)",
                },
            },
            "notes": [
                "Not a single SRS over all ads.",
                "Observed proportions must be computed on data/observations.jsonl.",
                "Corrected point estimates and CIs are audit products, not raw observations.",
                "A later ad-hoc silent synonym scan used a different shuffle over a larger population; it is NOT this control sample.",
            ],
        },
        "populationCounts": {k: len(v) for k, v in labels.items()},
        "sampleIds": {
            "asks": asks[: args.asks],
            "silent": silent[: args.silent],
            "rejects": rejects,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "wrote": str(OUT.relative_to(ROOT)),
                "population": doc["populationCounts"],
                "sampleSizes": {k: len(v) for k, v in doc["sampleIds"].items()},
                "seed": args.seed,
                "lock": lock,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
