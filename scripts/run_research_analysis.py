#!/usr/bin/env python3
"""Assemble and run full research analysis from numbered part files."""
from pathlib import Path
_here = Path(__file__).resolve()
_p = _here.parent / "_run_research_parts"
_src = "".join((_p / f"{i}.py").read_text(encoding="utf-8") for i in range(3))
exec(compile(_src, str(_here), "exec"), {"__name__": "__main__", "__file__": str(_here)})
