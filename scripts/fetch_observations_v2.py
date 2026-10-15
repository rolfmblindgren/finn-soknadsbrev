#!/usr/bin/env python3
"""Download observations.v2.jsonl from FINN_OBSERVATIONS_V2_URL (or baked-in OSF URL)."""
from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "https://osf.io/download/6ad09bbb2f79cf3fe336520a/"
EXPECTED_SHA256 = "f993024e6d04e9158ebd285e8578adfe34f261a86617bb03909918b0e33951ed"
OUT = ROOT / "data" / "observations.v2.jsonl"


def main() -> int:
    url = os.environ.get("FINN_OBSERVATIONS_V2_URL") or DEFAULT_URL
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists() and OUT.stat().st_size > 0:
        h = hashlib.sha256(OUT.read_bytes()).hexdigest()
        if h == EXPECTED_SHA256:
            print(f"already present: {OUT} (sha256 ok)")
            return 0
        print(f"warning: existing file sha256={h}, re-downloading")
    print(f"downloading {url} -> {OUT}")
    urllib.request.urlretrieve(url, OUT)
    h = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"sha256={h} size={OUT.stat().st_size}")
    if h != EXPECTED_SHA256:
        print("ERROR: sha256 mismatch", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
