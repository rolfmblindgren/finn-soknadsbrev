#!/usr/bin/env python3
"""Unpack gzip+base64 sidecars (possibly split into .00/.01/…) into target paths."""
from __future__ import annotations
import base64, gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    "data/analysis/research_results.json",
    "data/analysis/research_results_active.json",
    "data/qa/validation_report.json",
    "reports/forskningsrapport.md",
    "data/qa/missing_ids.txt",
]

def load_b64(side_base: Path) -> str:
    # Prefer single file, else concatenate numbered parts side_base.00, .01, ...
    if side_base.exists():
        return side_base.read_text(encoding="ascii")
    parts = sorted(side_base.parent.glob(side_base.name + ".*"))
    # filter .00 .01 numeric suffixes
    numbered = [p for p in parts if p.name.rsplit(".", 1)[-1].isdigit()]
    if not numbered:
        raise FileNotFoundError(side_base)
    return "".join(p.read_text(encoding="ascii") for p in sorted(numbered, key=lambda p: int(p.name.rsplit(".", 1)[-1])))

def main() -> None:
    for rel in TARGETS:
        side = ROOT / (rel + ".gz.b64")
        try:
            b64 = load_b64(side)
        except FileNotFoundError:
            print("skip missing", side.relative_to(ROOT))
            continue
        target = ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = gzip.decompress(base64.b64decode(b64))
        target.write_bytes(raw)
        print("wrote", target.relative_to(ROOT), len(raw), "bytes")

if __name__ == "__main__":
    main()
