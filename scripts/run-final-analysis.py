#!/usr/bin/env python3
"""Final cover-letter classification analysis on data/observations.jsonl."""

from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBS = ROOT / "data" / "observations.jsonl"
OUT_DIR = ROOT / "data"
ARTIFACT_DIR = Path("/opt/cursor/artifacts")
SEED = 14
ASKS_N = 100
SILENT_N = 100

REJECT_PATTERNS = [
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
    r"ikke\s+send(?:e)?\s+(?:inn\s+)?(?:et\s+)?(?:tradisjonelt\s+)?søknadsbrev",
    r"skip\s+(?:the\s+)?cover\s+letter",
    r"do\s+not\s+send\s+(?:a\s+)?(?:formal\s+)?cover\s+letter",
    r"don'?t\s+send\s+(?:a\s+)?(?:formal\s+)?cover\s+letter",
    r"don'?t\s+want\s+(?:a\s+)?cover\s+letter",
    r"(?:a\s+)?(?:formal\s+)?cover\s+letter(?:s)?\s+(?:is|are)\s+not\s+(?:required|needed|wanted)",
    r"no\s+cover\s+letter(?:s)?(?:\s+(?:please|needed|required))?",
    r"without\s+(?:a\s+)?(?:formal\s+)?cover\s+letter",
]

ASK_PATTERNS = [
    (r"søknadsbrev\w*", "søknadsbrev"),
    (r"motivasjonsbrev\w*", "motivasjonsbrev"),
    (r"cover\s*letters?", "cover letter"),
    (r"application\s+letters?", "application letter"),
    (r"søknadstekst\w*", "søknadstekst"),
    (r"personlig(?:e|t)?\s+søknad(?:en|er)?", "personlig søknad"),
    (r"personlig(?:e|t)?\s+brev", "personlig brev"),
    (r"fortell(?:er)?\s+(?:oss\s+)?hvorfor\s+du\s+søker", "fortell hvorfor du søker"),
    (r"beskriv\s+hvorfor\s+du\s+søker", "beskriv hvorfor du søker"),
    (r"motiver\s+(?:kort\s+)?hvorfor\s+du\s+søker", "motiver hvorfor du søker"),
    (r"hvorfor\s+du\s+(?:ønsker\s+å\s+)?søke(?:r)?\s+(?:på\s+)?stillingen", "hvorfor du søker stillingen"),
    (r"why\s+you\s+(?:are\s+)?apply(?:ing)?", "why you are applying"),
    (r"letter\s+of\s+motivation", "letter of motivation"),
]

UNCERTAIN_PATTERNS = [
    (r"fortell\s+(?:litt\s+)?om\s+deg\s+selv", "fortell om deg selv"),
    (r"motivasjon(?:en)?\s+for\s+(?:å\s+)?søke", "motivasjon for å søke"),
    (r"hva\s+motiverer\s+deg", "hva motiverer deg"),
    (r"beskriv\s+din\s+motivasjon", "beskriv din motivasjon"),
    (r"kort\s+motivasjon", "kort motivasjon"),
    (r"legg\s+ved\s+(?:en\s+)?motivasjon", "legg ved motivasjon"),
]


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def snippet(text: str, needle: str | None, width: int = 120) -> str | None:
    if not needle or not text:
        return None
    i = text.lower().find(needle.lower())
    if i < 0:
        token = re.split(r"\s+", needle.strip())[0]
        i = text.lower().find(token.lower())
    if i < 0:
        return None
    a, b = max(0, i - width // 2), min(len(text), i + len(needle) + width // 2)
    s = text[a:b].strip()
    if a:
        s = "…" + s
    if b < len(text):
        s = s + "…"
    return s


def gold_label(text: str) -> dict:
    norm = (text or "").replace("\u00a0", " ")
    for pat in REJECT_PATTERNS:
        m = re.search(pat, norm, flags=re.I)
        if m:
            return {"gold": "rejects", "matched": m.group(0), "uncertain": False, "uncertainMatched": None}
    for pat, _name in ASK_PATTERNS:
        m = re.search(pat, norm, flags=re.I)
        if m:
            return {"gold": "asks", "matched": m.group(0), "uncertain": False, "uncertainMatched": None}
    for pat, _name in UNCERTAIN_PATTERNS:
        m = re.search(pat, norm, flags=re.I)
        if m:
            return {"gold": "silent", "matched": None, "uncertain": True, "uncertainMatched": m.group(0)}
    return {"gold": "silent", "matched": None, "uncertain": False, "uncertainMatched": None}


def load_rows() -> list[dict]:
    rows = []
    for line in OBS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main() -> None:
    rows = load_rows()
    analyzable = [r for r in rows if r.get("originalClassification") != "error"]
    by_pred: dict[str, list[dict]] = {"asks": [], "silent": [], "rejects": []}
    for r in analyzable:
        cat = r.get("originalClassification")
        if cat in by_pred:
            by_pred[cat].append(r)

    n = len(analyzable)
    observed = {k: len(v) for k, v in by_pred.items()}
    observed_pct = {k: round(100 * v / n, 2) for k, v in observed.items()}

    rng = random.Random(SEED)
    asks_pop = list(by_pred["asks"])
    silent_pop = list(by_pred["silent"])
    rejects_pop = list(by_pred["rejects"])
    asks_pop.sort(key=lambda r: r["id"])
    silent_pop.sort(key=lambda r: r["id"])
    rejects_pop.sort(key=lambda r: r["id"])
    rng.shuffle(asks_pop)
    rng.shuffle(silent_pop)

    sample = {
        "asks": asks_pop[:ASKS_N],
        "silent": silent_pop[:SILENT_N],
        "rejects": rejects_pop,
    }

    sample_doc = {
        "method": {
            "type": "stratified_random_within_predicted_class",
            "seed": SEED,
            "generator": "Python random.Random(seed); sort by id; shuffle; take first n",
            "populationSource": "data/observations.jsonl (full completed scan)",
            "wasRandom": True,
            "strata": {
                "asks": {"populationSize": len(asks_pop), "sampleSize": len(sample["asks"]), "method": f"SRS within asks, n={ASKS_N}"},
                "silent": {"populationSize": len(silent_pop), "sampleSize": len(sample["silent"]), "method": f"SRS within silent, n={SILENT_N}"},
                "rejects": {"populationSize": len(rejects_pop), "sampleSize": len(sample["rejects"]), "method": "census (all rejects)"},
            },
        },
        "sampleIds": {k: [r["id"] for r in v] for k, v in sample.items()},
    }
    (OUT_DIR / "analysis-sample.json").write_text(json.dumps(sample_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    audited = []
    for pred, items in sample.items():
        for r in items:
            g = gold_label(r.get("classificationText") or "")
            audited.append({
                "id": r["id"], "url": r.get("url"), "title": r.get("title"), "company": r.get("company"),
                "industry": r.get("industry"), "predicted": pred, "gold": g["gold"], "goldMatched": g["matched"],
                "uncertain": g["uncertain"], "uncertainMatched": g["uncertainMatched"],
                "predictedMatched": r.get("matched"), "correct": pred == g["gold"],
                "snippet": snippet(r.get("classificationText") or "", g["matched"] or g["uncertainMatched"] or r.get("matched")),
            })

    full_silent_misses = []
    full_reject_fps = []
    synonym_census = Counter()
    for r in by_pred["silent"]:
        g = gold_label(r.get("classificationText") or "")
        if g["gold"] == "asks":
            full_silent_misses.append({
                "id": r["id"], "url": r.get("url"), "title": r.get("title"), "company": r.get("company"),
                "industry": r.get("industry"), "matched": g["matched"],
                "snippet": snippet(r.get("classificationText") or "", g["matched"]),
            })
            key = (g["matched"] or "").lower()
            if "motivasjonsbrev" in key: synonym_census["motivasjonsbrev"] += 1
            elif "søknadstekst" in key: synonym_census["søknadstekst"] += 1
            elif "personlig søknad" in key or "personlig brev" in key: synonym_census["personlig søknad/brev"] += 1
            elif "søknadsbrev" in key: synonym_census["søknadsbrev(bøying/annet)"] += 1
            elif "cover" in key or "application" in key: synonym_census["cover/application letter"] += 1
            elif "hvorfor" in key or "why" in key: synonym_census["hvorfor-du-søker"] += 1
            else: synonym_census["annet_ask_signal"] += 1

    for r in by_pred["rejects"]:
        g = gold_label(r.get("classificationText") or "")
        if g["gold"] != "rejects":
            full_reject_fps.append({
                "id": r["id"], "url": r.get("url"), "title": r.get("title"), "predicted": "rejects",
                "gold": g["gold"], "matched": g["matched"],
                "snippet": snippet(r.get("classificationText") or "", g["matched"] or r.get("matched")),
            })

    acc = {}
    for pred in ("asks", "silent", "rejects"):
        subset = [a for a in audited if a["predicted"] == pred]
        correct = sum(1 for a in subset if a["correct"])
        wrong = len(subset) - correct
        lo, hi = wilson_ci(wrong, len(subset))
        acc[pred] = {
            "n": len(subset), "correct": correct,
            "accuracy": round(correct / len(subset), 4) if subset else None,
            "misclassificationRate": round(wrong / len(subset), 4) if subset else None,
            "misclassificationRateWilson95CI": [round(lo, 4), round(hi, 4)],
            "goldBreakdown": dict(Counter(a["gold"] for a in subset)),
        }

    silent_to_asks = len(full_silent_misses)
    silent_to_asks_rate = silent_to_asks / observed["silent"] if observed["silent"] else 0
    asks_subset = [a for a in audited if a["predicted"] == "asks"]
    asks_fp = sum(1 for a in asks_subset if a["gold"] != "asks")
    asks_tp_rate = 1 - (asks_fp / len(asks_subset) if asks_subset else 0)
    asks_fp_lo, asks_fp_hi = wilson_ci(asks_fp, len(asks_subset)) if asks_subset else (0, 0)
    rejects_fp = len(full_reject_fps)
    rejects_tp = observed["rejects"] - rejects_fp
    asks_to_rejects_rate = (sum(1 for a in asks_subset if a["gold"] == "rejects") / len(asks_subset) if asks_subset else 0)
    silent_to_rejects = sum(1 for r in by_pred["silent"] if gold_label(r.get("classificationText") or "")["gold"] == "rejects")
    corr_asks = observed["asks"] * asks_tp_rate + silent_to_asks + sum(1 for x in full_reject_fps if x["gold"] == "asks")
    corr_rejects = rejects_tp + observed["asks"] * asks_to_rejects_rate + silent_to_rejects
    corr_silent = n - corr_asks - corr_rejects
    corr_total = corr_asks + corr_silent + corr_rejects
    asks_tp_lo, asks_tp_hi = 1 - asks_fp_hi, 1 - asks_fp_lo
    corr_asks_lo = observed["asks"] * asks_tp_lo + silent_to_asks + sum(1 for x in full_reject_fps if x["gold"] == "asks")
    corr_asks_hi = observed["asks"] * asks_tp_hi + silent_to_asks + sum(1 for x in full_reject_fps if x["gold"] == "asks")

    mis = [a for a in audited if not a["correct"]]
    uncertain = [a for a in audited if a["uncertain"]]
    synonym_keys = ["motivasjonsbrev", "søknadstekst", "personlig søknad", "personlig brev", "fortell hvorfor du søker", "beskriv hvorfor du søker", "cover letter", "søknadsbrev"]
    synonym_in_sample = {k: [] for k in synonym_keys}
    for a in audited:
        blob = f"{a.get('goldMatched') or ''} {a.get('uncertainMatched') or ''} {a.get('predictedMatched') or ''}".lower()
        for k in synonym_keys:
            if k in blob:
                synonym_in_sample[k].append({"id": a["id"], "title": a["title"], "predicted": a["predicted"], "gold": a["gold"], "matched": a.get("goldMatched") or a.get("uncertainMatched"), "url": a["url"]})

    report = {
        "meta": {
            "observationsPath": "data/observations.jsonl", "nAnalyzable": n,
            "nExcludedError": sum(1 for r in rows if r.get("originalClassification") == "error"),
            "seed": SEED, "goldAskSignals": [name for _, name in ASK_PATTERNS], "goldRejectFirst": True,
            "notes": [
                "Observed shares are raw counts / N from observations.jsonl.",
                "Control sample is stratified SRS within predicted class on the FULL final population.",
                "Silent→asks undercount uses a full-population gold pass (census), not only the n=100 sample.",
                "Rejects false positives also from full-population gold pass.",
                "Asks false-positive rate estimated from n=100 sample with Wilson CI.",
            ],
        },
        "observed": {"counts": observed, "percentages": observed_pct, "N": n},
        "controlSample": {
            "method": sample_doc["method"], "accuracyByPredicted": acc,
            "misclassifications": mis, "uncertainCases": uncertain,
            "synonymHitsInSample": {k: v for k, v in synonym_in_sample.items() if v},
        },
        "fullPopulationGoldPass": {
            "silentToAsksCount": silent_to_asks, "silentToAsksRate": round(silent_to_asks_rate, 4),
            "silentToAsksBySignal": dict(synonym_census), "silentToAsksExamples": full_silent_misses[:25],
            "rejectsFalsePositivesCount": rejects_fp, "rejectsFalsePositives": full_reject_fps[:25],
            "silentToRejectsCount": silent_to_rejects,
        },
        "correctedEstimates": {
            "method": "corr_asks = asks*sample_TP_rate + census(silent→asks) + census(rejects→asks); corr_rejects = census(true rejects) + asks*sample(asks→rejects) + census(silent→rejects); corr_silent = N - corr_asks - corr_rejects",
            "pointCounts": {"asks": round(corr_asks), "silent": round(corr_silent), "rejects": round(corr_rejects)},
            "pointPercentages": {"asks": round(100 * corr_asks / corr_total, 2), "silent": round(100 * corr_silent / corr_total, 2), "rejects": round(100 * corr_rejects / corr_total, 2)},
            "asksCountRangeFromAsksFpWilson": [round(corr_asks_lo), round(corr_asks_hi)],
            "asksPctRangeFromAsksFpWilson": [round(100 * corr_asks_lo / n, 2), round(100 * corr_asks_hi / n, 2)],
            "caveat": "Range only propagates Wilson uncertainty on asks false-positive rate from the n=100 asks sample. Silent→asks and rejects FP are treated as census (0 sampling error) given full stored texts.",
        },
    }

    out_path = OUT_DIR / "analysis-report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "analysis-report.json").write_text(out_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps({"observed": report["observed"], "sampleAccuracy": acc, "silentToAsksCensus": silent_to_asks, "rejectsFP": rejects_fp, "corrected": report["correctedEstimates"]["pointPercentages"], "asksRangePct": report["correctedEstimates"]["asksPctRangeFromAsksFpWilson"], "misInSample": len(mis), "uncertainInSample": len(uncertain), "wrote": str(out_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
