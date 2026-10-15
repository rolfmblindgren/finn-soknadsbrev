#!/usr/bin/env python3
"""Loader: reassembles run_research_analysis from base64 parts."""
from __future__ import annotations
import base64
from pathlib import Path

_parts_dir = Path(__file__).resolve().parent / "_run_research_parts"
_code = b"".join(
    base64.b64decode(p.read_text(encoding="ascii"))
    for p in sorted(_parts_dir.glob("*.b64"))
)
exec(compile(_code, str(Path(__file__).resolve()), "exec"), globals())
