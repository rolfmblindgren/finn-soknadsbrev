#!/usr/bin/env python3
"""Punkt 3–5: Variasjon, hypoteser, rapport, delbart datasett, figurer.

Leser data/analysis/observations.enriched.jsonl (eller bygger heuristisk
fallback fra observations.v2.jsonl). Skriver reproduserbare artefakter under
data/analysis/ og reports/.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENRICHED = ROOT / "data/analysis/observations.enriched.jsonl"
V2 = ROOT / "data/observations.v2.jsonl"
VAL_REPORT = ROOT / "data/qa/validation_report.json"
OUT_DIR = ROOT / "data/analysis"
REPORT = ROOT / "reports/forskningsrapport.md"
FIG_DIR = ROOT / "reports/figures"

# Gold4 patterns (aligned with validate_classification.py)
REJECT_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"tar\s+ikke\s+imot\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev|søknadstekst)",
        r"ikke\s+sende?\s+inn\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev|søknadstekst)",
        r"ikke\s+send(?:e)?\s+(?:inn\s+)?(?:et\s+)?(?:søknadsbrev|motivasjonsbrev|søknadstekst)",
        r"ønsker\s+ikke\s+(?:å\s+motta\s+)?(?:et\s+)?(?:søknadsbrev|motivasjonsbrev|søknadstekst)",
        r"vil\s+ikke\s+ha\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev|søknadstekst)",
        r"ber\s+ikke\s+om\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev|søknadstekst|personlig\s+søknad)",
        r"uten\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev|søknadstekst)",
        r"ingen\s+(?:søknadsbrev|motivasjonsbrev|søknadstekst)",
        r"(?:søknadsbrev|motivasjonsbrev|søknadstekst)\s+er\s+ikke\s+(?:nødvendig|ønskelig|påkrevd|ønsket)",
        r"ikke\s+(?:nødvendig|ønskelig|påkrevd)\s+med\s+(?:søknadsbrev|motivasjonsbrev|søknadstekst)",
        r"trenger\s+ikke\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev|søknadstekst)",
        r"trenger\s+ikke\s+(?:å\s+)?skrive\s+(?:en\s+)?(?:lang\s+)?søknad",
        r"fremfor\s+å\s+be\s+deg\s+skrive\s+(?:en\s+)?søknadstekst",
        r"ikke\s+skal\s+laste\s+opp\s+(?:en\s+)?(?:separat\s+)?søknadstekst",
        r"skal\s+ikke\s+laste\s+opp\s+(?:en\s+)?(?:separat\s+)?søknadstekst",
        r"ikke\s+bruk\s+mye\s+tid\s+på\s+søknadstekst",
        r"utvalgsspørsmålene\s+erstatter",
        r"skip\s+(?:the\s+)?cover\s+letter",
        r"do\s+not\s+send\s+(?:a\s+)?(?:formal\s+)?cover\s+letter",
        r"don'?t\s+send\s+(?:a\s+)?(?:formal\s+)?cover\s+letter",
        r"no\s+cover\s+letter",
        r"without\s+(?:a\s+)?(?:formal\s+)?cover\s+letter",
        r"cover\s+letter(?:s)?\s+(?:is|are)\s+not\s+(?:required|needed|wanted)",
    ]
]
OPTIONAL_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"søknadsbrev\s+er\s+valgfritt",
        r"valgfritt\s+søknadsbrev",
        r"optional\s+cover\s+letter",
        r"cover\s+letter\s+(?:is\s+)?optional",
    ]
]
REQUIRED_PATTERNS = [
    (re.compile(p, re.I), lab)
    for p, lab in [
        (r"søknadsbrev\w*", "søknadsbrev"),
        (r"motivasjonsbrev\w*", "motivasjonsbrev"),
        (r"cover\s*letters?", "cover letter"),
        (r"application\s+letters?", "application letter"),
        (r"søknadstekst\w*", "søknadstekst"),
        (r"personlig(?:e|t)?\s+søknad(?:en|er)?", "personlig søknad"),
        (r"personlig(?:e|t)?\s+brev", "personlig brev"),
        (r"fortell(?:er)?\s+(?:oss\s+)?hvorfor\s+du\s+søker", "fortell hvorfor du søker"),
        (r"beskriv\s+hvorfor\s+du\s+søker", "beskriv hvorfor du søker"),
        (r"letter\s+of\s+motivation", "letter of motivation"),
    ]
]
UNCERTAIN_PATTERNS = [
    (re.compile(p, re.I), lab)
    for p, lab in [
        (r"fortell\s+(?:litt\s+)?om\s+deg\s+selv", "fortell om deg selv"),
        (r"motivasjon(?:en)?\s+for\s+(?:å\s+)?søke", "motivasjon for å søke"),
        (r"hva\s+motiverer\s+deg", "hva motiverer deg"),
        (r"beskriv\s+din\s+motivasjon", "beskriv din motivasjon"),
        (r"kort\s+motivasjon", "kort motivasjon"),
    ]
]


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def gold4(text: str) -> tuple[str, str | None]:
    t = (text or "").replace("\u00a0", " ")
    for p in REJECT_PATTERNS:
        m = p.search(t)
        if m:
            return "explicit_reject", m.group(0)
    for p in OPTIONAL_PATTERNS:
        m = p.search(t)
        if m:
            return "optional", m.group(0)
    for p, lab in REQUIRED_PATTERNS:
        m = p.search(t)
        if m:
            return "required", lab
    for p, lab in UNCERTAIN_PATTERNS:
        m = p.search(t)
        if m:
            return "uncertain", lab
    return "no_info", None


def gold3(g4: str) -> str:
    return {
        "required": "asks",
        "optional": "asks",
        "explicit_reject": "rejects",
        "no_info": "silent",
        "uncertain": "uncertain",
    }[g4]


def load_rows() -> list[dict]:
    enrich_map: dict = {}
    side = ROOT / "data/analysis/enrichment_by_id.json"
    if ENRICHED.exists():
        rows = []
        with ENRICHED.open() as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        return rows
    if side.exists():
        enrich_map = json.loads(side.read_text())
    rows = []
    with V2.open() as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            r["enrichment"] = enrich_map.get(r["id"]) or {
                "sector": "Ukjent",
                "finnSector": None,
                "occupations": [],
                "occupationPrimary": None,
                "experienceTags": [],
                "educationTags": [],
                "isRecruitmentAgency": False,
                "agencySignals": {},
                "titleLevelTags": [],
                "hasIndustry": bool(r.get("industry")),
            }
            rows.append(r)
    return rows

def rate_table(rows: list[dict], key_fn, min_n: int = 30) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        k = key_fn(r)
        if k is None or k == "":
            k = "Ukjent"
        groups[str(k)].append(r)
    out = []
    for k, rs in groups.items():
        n = len(rs)
        asks = sum(1 for r in rs if r["analysis3"] == "asks")
        rejects = sum(1 for r in rs if r["analysis3"] == "rejects")
        silent = sum(1 for r in rs if r["analysis3"] == "silent")
        uncertain = sum(1 for r in rs if r["analysis3"] == "uncertain")
        certain = [r for r in rs if r["analysis3"] != "uncertain"]
        n_c = len(certain)
        asks_c = sum(1 for r in certain if r["analysis3"] == "asks")
        p = asks_c / n_c if n_c else 0.0
        lo, hi = wilson_ci(asks_c, n_c)
        out.append(
            {
                "group": k,
                "n": n,
                "asks": asks,
                "silent": silent,
                "rejects": rejects,
                "uncertain": uncertain,
                "asksShareCertain": round(p, 4),
                "asksWilson95": [round(lo, 4), round(hi, 4)],
                "rejectsShare": round(rejects / n, 4) if n else 0.0,
                "silentShare": round(silent / n, 4) if n else 0.0,
                "includedInComparisons": n >= min_n,
            }
        )
    out.sort(key=lambda x: (-x["n"], x["group"]))
    return out


def log_loss(y, p):
    eps = 1e-9
    return -sum(
        yi * math.log(max(min(pi, 1 - eps), eps))
        + (1 - yi) * math.log(max(min(1 - pi, 1 - eps), eps))
        for yi, pi in zip(y, p)
    ) / len(y)


def sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1 / (1 + ez)
    ez = math.exp(z)
    return ez / (1 + ez)


def fit_logit(X: list[list[float]], y: list[int], l2: float = 0.5, iters: int = 25):
    """L2-regularized logistic regression via IRLS/Newton (no sklearn)."""
    n = len(y)
    p = len(X[0])
    base = sum(y) / max(n, 1)
    base = min(max(base, 1e-4), 1 - 1e-4)
    w = [math.log(base / (1 - base))] + [0.0] * (p - 1)

    def hessian_and_grad():
        H = [[0.0] * p for _ in range(p)]
        g = [0.0] * p
        for i in range(n):
            z = sum(w[j] * X[i][j] for j in range(p))
            pred = sigmoid(z)
            err = pred - y[i]
            v = pred * (1 - pred)
            for j in range(p):
                g[j] += err * X[i][j]
                for k in range(p):
                    H[j][k] += v * X[i][j] * X[i][k]
        for j in range(p):
            if j > 0:
                g[j] += l2 * w[j]
                H[j][j] += l2
        return H, g

    def solve(H, g):
        A = [H[i][:] + [g[i]] for i in range(p)]
        for i in range(p):
            piv = i
            for r in range(i + 1, p):
                if abs(A[r][i]) > abs(A[piv][i]):
                    piv = r
            A[i], A[piv] = A[piv], A[i]
            if abs(A[i][i]) < 1e-12:
                continue
            for r in range(i + 1, p):
                f = A[r][i] / A[i][i]
                for c in range(i, p + 1):
                    A[r][c] -= f * A[i][c]
        x = [0.0] * p
        for i in range(p - 1, -1, -1):
            if abs(A[i][i]) < 1e-12:
                x[i] = 0.0
                continue
            s = A[i][p]
            for c in range(i + 1, p):
                s -= A[i][c] * x[c]
            x[i] = s / A[i][i]
        return x

    for _ in range(iters):
        H, g = hessian_and_grad()
        step = solve(H, g)
        for j in range(p):
            w[j] -= step[j]
        if max(abs(s) for s in step) < 1e-8:
