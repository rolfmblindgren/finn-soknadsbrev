#!/usr/bin/env python3
"""Punkt 2: Stratifisert kontrollutvalg og validering av klassifisering."""

from __future__ import annotations

import json
import math
import random
import re
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIG = ROOT / "data" / "original" / "observations.v1.jsonl"
OUT_SAMPLE = ROOT / "data" / "qa" / "validation_sample.json"
OUT_REPORT = ROOT / "data" / "qa" / "validation_report.json"
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
    r"(?:a\s+)?(?:formal\s+)?cover\s+letter(?:s)?\s+(?:is|are)\s+not\s+(?:required|needed|wanted)",
    r"do\s+not\s+send\s+(?:a\s+)?(?:formal\s+)?cover\s+letter",
    r"don'?t\s+send\s+(?:a\s+)?(?:formal\s+)?cover\s+letter",
    r"no\s+cover\s+letter",
    r"without\s+(?:a\s+)?(?:formal\s+)?cover\s+letter",
    r"skip\s+(?:the\s+)?cover\s+letter",
]

OPTIONAL_PATTERNS = [
    r"søknadsbrev\s+er\s+valgfritt",
    r"valgfritt\s+søknadsbrev",
    r"gjerne\s+(?:et\s+)?søknadsbrev",
    r"(?:søknadsbrev|motivasjonsbrev|søknadstekst)\s+er\s+ikke\s+påkrevd(?:\s*,?\s*men)?",
    r"optional\s+cover\s+letter",
    r"cover\s+letter\s+(?:is\s+)?optional",
]

REQUIRED_PATTERNS = [
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
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def snippet(text: str, needle: str | None, width: int = 130) -> str | None:
    if not text or not needle:
        return None
    i = text.lower().find(needle.lower())
    if i < 0:
        i = text.lower().find(needle.split()[0].lower())
    if i < 0:
        return None
    a, b = max(0, i - width // 2), min(len(text), i + len(needle) + width // 2)
    s = text[a:b].strip()
    return ("…" if a else "") + s + ("…" if b < len(text) else "")


def gold_label_4way(text: str) -> dict:
    norm = (text or "").replace("\u00a0", " ")
    for pat in REJECT_PATTERNS:
        m = re.search(pat, norm, flags=re.I)
        if m:
            return {"gold4": "explicit_reject", "gold3": "rejects", "matched": m.group(0), "uncertain": False, "uncertainMatched": None}
    for pat in OPTIONAL_PATTERNS:
        m = re.search(pat, norm, flags=re.I)
        if m:
            return {"gold4": "optional", "gold3": "asks", "matched": m.group(0), "uncertain": False, "uncertainMatched": None}
    for pat, _name in REQUIRED_PATTERNS:
        m = re.search(pat, norm, flags=re.I)
        if m:
            return {"gold4": "required", "gold3": "asks", "matched": m.group(0), "uncertain": False, "uncertainMatched": None}
    for pat, _name in UNCERTAIN_PATTERNS:
        m = re.search(pat, norm, flags=re.I)
        if m:
            return {"gold4": "uncertain", "gold3": "uncertain", "matched": None, "uncertain": True, "uncertainMatched": m.group(0)}
    return {"gold4": "no_info", "gold3": "silent", "matched": None, "uncertain": False, "uncertainMatched": None}


def main() -> None:
    rows = [json.loads(l) for l in ORIG.read_text(encoding="utf-8").splitlines() if l.strip()]
    analyzable = [r for r in rows if r.get("originalClassification") in {"asks", "silent", "rejects"}]
    by_pred = {"asks": [], "silent": [], "rejects": []}
    for r in analyzable:
        by_pred[r["originalClassification"]].append(r)

    N = {k: len(v) for k, v in by_pred.items()}
    N_tot = sum(N.values())
    W = {k: N[k] / N_tot for k in N}

    rng = random.Random(SEED)
    for k in by_pred:
        by_pred[k] = sorted(by_pred[k], key=lambda r: r["id"])
    asks = list(by_pred["asks"])
    silent = list(by_pred["silent"])
    rejects = list(by_pred["rejects"])
    rng.shuffle(asks)
    rng.shuffle(silent)

    sample = {"asks": asks[:ASKS_N], "silent": silent[:SILENT_N], "rejects": rejects}
    sample_ids = {k: [r["id"] for r in v] for k, v in sample.items()}

    sample_doc = {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": {
            "type": "stratified_random_within_predicted_class",
            "seed": SEED,
            "generator": "Python random.Random(seed); sort by id; shuffle; take first n",
            "populationSource": "data/original/observations.v1.jsonl",
            "wasRandom": True,
            "strata": {
                "asks": {"populationSize": N["asks"], "sampleSize": len(sample["asks"]), "weight": W["asks"], "method": f"SRS, n={ASKS_N}"},
                "silent": {"populationSize": N["silent"], "sampleSize": len(sample["silent"]), "weight": W["silent"], "method": f"SRS, n={SILENT_N}"},
                "rejects": {"populationSize": N["rejects"], "sampleSize": len(sample["rejects"]), "weight": W["rejects"], "method": "census"},
            },
        },
        "sampleIds": sample_ids,
    }
    OUT_SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    OUT_SAMPLE.write_text(json.dumps(sample_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    audited = []
    for pred, items in sample.items():
        for r in items:
            g = gold_label_4way(r.get("classificationText") or "")
            agree = None if g["uncertain"] else (pred == g["gold3"])
            audited.append({
                "id": r["id"], "url": r.get("url"), "title": r.get("title"), "company": r.get("company"),
                "industry": r.get("industry"), "predicted3": pred, "gold4": g["gold4"], "gold3": g["gold3"],
                "matched": g["matched"], "uncertain": g["uncertain"], "uncertainMatched": g["uncertainMatched"],
                "predictedMatched": r.get("matched"), "agree3": agree,
                "snippet": snippet(r.get("classificationText") or "", g["matched"] or g["uncertainMatched"] or r.get("matched")),
            })

    stratum_stats = {}
    for pred in ("asks", "silent", "rejects"):
        subset = [a for a in audited if a["predicted3"] == pred]
        certain = [a for a in subset if a["agree3"] is not None]
        uncertain_n = sum(1 for a in subset if a["uncertain"])
        wrong = [a for a in certain if not a["agree3"]]
        right = [a for a in certain if a["agree3"]]
        err = len(wrong) / len(certain) if certain else 0.0
        lo, hi = wilson_ci(len(wrong), len(certain))
        transitions = Counter((pred, a["gold3"]) for a in certain)
        gold4 = Counter(a["gold4"] for a in subset)
        stratum_stats[pred] = {
            "nSampled": len(subset), "nCertain": len(certain), "nUncertain": uncertain_n,
            "nCorrect": len(right), "nIncorrect": len(wrong),
            "errorRate": round(err, 4), "errorRateWilson95CI": [round(lo, 4), round(hi, 4)],
            "accuracy": round(1 - err, 4) if certain else None,
            "gold4Breakdown": dict(gold4),
            "transitionsToGold3": {f"{a}->{b}": c for (a, b), c in transitions.items()},
            "incorrectExamples": wrong,
        }

    e_hat = sum(W[h] * stratum_stats[h]["errorRate"] for h in W)
    e_lo = sum(W[h] * stratum_stats[h]["errorRateWilson95CI"][0] for h in W)
    e_hi = sum(W[h] * stratum_stats[h]["errorRateWilson95CI"][1] for h in W)

    silent_to_required, silent_to_optional, silent_to_reject, silent_uncertain = [], [], [], []
    for r in by_pred["silent"]:
        g = gold_label_4way(r.get("classificationText") or "")
        row = {"id": r["id"], "url": r.get("url"), "title": r.get("title"), "industry": r.get("industry"),
               "gold4": g["gold4"], "matched": g["matched"] or g["uncertainMatched"],
               "snippet": snippet(r.get("classificationText") or "", g["matched"] or g["uncertainMatched"])}
        if g["gold4"] == "required": silent_to_required.append(row)
        elif g["gold4"] == "optional": silent_to_optional.append(row)
        elif g["gold4"] == "explicit_reject": silent_to_reject.append(row)
        elif g["gold4"] == "uncertain": silent_uncertain.append(row)

    rejects_fp = []
    for r in by_pred["rejects"]:
        g = gold_label_4way(r.get("classificationText") or "")
        if g["gold4"] != "explicit_reject" and not g["uncertain"]:
            rejects_fp.append({"id": r["id"], "url": r.get("url"), "title": r.get("title"), "gold4": g["gold4"],
                               "matched": g["matched"], "snippet": snippet(r.get("classificationText") or "", g["matched"] or r.get("matched"))})

    asks_sample = [a for a in audited if a["predicted3"] == "asks" and a["agree3"] is not None]
    asks_to_reject_rate = sum(1 for a in asks_sample if a["gold3"] == "rejects") / len(asks_sample) if asks_sample else 0
    asks_keep_rate = sum(1 for a in asks_sample if a["gold3"] == "asks") / len(asks_sample) if asks_sample else 0
    asks_fp_lo, asks_fp_hi = wilson_ci(sum(1 for a in asks_sample if a["gold3"] != "asks"), len(asks_sample))

    corr_asks = N["asks"] * asks_keep_rate + len(silent_to_required) + len(silent_to_optional) + sum(1 for x in rejects_fp if x["gold4"] in {"required", "optional"})
    corr_rejects = (N["rejects"] - len(rejects_fp)) + N["asks"] * asks_to_reject_rate + len(silent_to_reject)
    corr_silent = N_tot - corr_asks - corr_rejects
    corr_asks_lo = N["asks"] * (1 - asks_fp_hi) + len(silent_to_required) + len(silent_to_optional) + sum(1 for x in rejects_fp if x["gold4"] in {"required", "optional"})
    corr_asks_hi = N["asks"] * (1 - asks_fp_lo) + len(silent_to_required) + len(silent_to_optional) + sum(1 for x in rejects_fp if x["gold4"] in {"required", "optional"})

    uncertain_cases = [a for a in audited if a["uncertain"]]
    mis = [a for a in audited if a["agree3"] is False]

    synonym_keys = ["motivasjonsbrev", "søknadstekst", "personlig søknad", "personlig brev", "fortell hvorfor", "cover letter", "søknadsbrev"]
    synonym_hits = {k: [] for k in synonym_keys}
    for a in audited:
        blob = f"{a.get('matched') or ''} {a.get('uncertainMatched') or ''} {a.get('predictedMatched') or ''}".lower()
        for k in synonym_keys:
            if k in blob:
                synonym_hits[k].append({"id": a["id"], "predicted3": a["predicted3"], "gold4": a["gold4"],
                                        "matched": a.get("matched") or a.get("uncertainMatched"), "url": a["url"], "title": a["title"]})

    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "population": {"N": N_tot, "byPredicted3": N, "stratumWeights": W},
        "sampleFile": "data/qa/validation_sample.json",
        "labelSchema": {
            "predicted3": ["asks", "silent", "rejects"],
            "gold4": ["required", "optional", "explicit_reject", "no_info", "uncertain"],
            "mappingNote": "required/optional collapse to asks for 3-way agreement; uncertain is never counted as a secure error or secure correct.",
        },
        "stratumValidation": stratum_stats,
        "overallStratifiedErrorRate": {
            "estimate": round(e_hat, 4),
            "approxWeightedWilson95CI": [round(e_lo, 4), round(e_hi, 4)],
            "method": "sum_h W_h * e_h with W_h = N_h/N; CI = weighted stratum Wilson bounds (approximate)",
        },
        "observedShares3": {"asks": round(100 * N["asks"] / N_tot, 2), "silent": round(100 * N["silent"] / N_tot, 2), "rejects": round(100 * N["rejects"] / N_tot, 2)},
        "correctedShares3": {
            "method": "corr_asks = asks*sample_keep_rate + census(silent→required/optional) + census(rejects→required/optional); corr_rejects = census(true rejects) + asks*sample(asks→reject) + census(silent→explicit_reject); uncertain silent left in silent; not promoted to asks",
            "pointCounts": {"asks": round(corr_asks), "silent": round(corr_silent), "rejects": round(corr_rejects)},
            "pointPercentages": {"asks": round(100 * corr_asks / N_tot, 2), "silent": round(100 * corr_silent / N_tot, 2), "rejects": round(100 * corr_rejects / N_tot, 2)},
            "asksPercentRangeFromAsksFpWilson": [round(100 * corr_asks_lo / N_tot, 2), round(100 * corr_asks_hi / N_tot, 2)],
        },
        "fullPopulationSilentPass": {
            "toRequired": len(silent_to_required), "toOptional": len(silent_to_optional),
            "toExplicitReject": len(silent_to_reject), "uncertain": len(silent_uncertain),
            "examplesRequired": silent_to_required[:20], "examplesOptional": silent_to_optional[:10],
            "examplesReject": silent_to_reject[:10], "examplesUncertain": silent_uncertain[:15],
        },
        "fullPopulationRejectsPass": {"falsePositives": len(rejects_fp), "examples": rejects_fp[:20]},
        "misclassificationsInSample": mis,
        "uncertainInSample": uncertain_cases,
        "synonymHitsInSample": {k: v for k, v in synonym_hits.items() if v},
        "interpretationGuards": [
            "Observed shares ≠ corrected estimates.",
            "Uncertain cases are documented and excluded from secure accuracy denominators.",
            "Optional cover-letter language is rare and collapsed to asks for 3-way correction, but counted separately in gold4.",
            "Silent→required census uses stored texts; market churn may still affect a few ads.",
        ],
    }
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "sample": str(OUT_SAMPLE.relative_to(ROOT)), "report": str(OUT_REPORT.relative_to(ROOT)),
        "N": N_tot, "stratumError": {k: v["errorRate"] for k, v in stratum_stats.items()},
        "stratifiedError": report["overallStratifiedErrorRate"],
        "observed": report["observedShares3"], "corrected": report["correctedShares3"]["pointPercentages"],
        "asksRange": report["correctedShares3"]["asksPercentRangeFromAsksFpWilson"],
        "silentToRequired": len(silent_to_required), "silentUncertain": len(silent_uncertain),
        "uncertainInSample": len(uncertain_cases), "misInSample": len(mis),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
