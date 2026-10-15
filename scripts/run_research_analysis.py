#!/usr/bin/env python3
"""Assemble and run the full research analysis script from part files."""
from pathlib import Path

_parts = Path(__file__).resolve().parent / "_run_research_parts"
_src = (_parts / "a.py").read_text(encoding="utf-8") + (_parts / "b.py").read_text(
    encoding="utf-8"
)
_ns = {"__name__": "__main__", "__file__": str(Path(__file__).resolve())}
exec(compile(_src, __file__, "exec"), _ns)
