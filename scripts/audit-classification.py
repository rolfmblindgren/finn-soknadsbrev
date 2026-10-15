#!/usr/bin/env python3
"""Sample and audit cover-letter classifications against live Finn ad text."""

from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".agent-serve" / "scan-state"
LOG = STATE / "scan.log"
OUT_DIR = Path("/opt/cursor/artifacts")
OUT_JSON = OUT_DIR / "classification-audit.json"
SEED = 14
UA = "FinnSoknadsbrevBot/0.1 (+audit; cover-letter research)"

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
    r"skip\s+(?:the\s+)?cover\s+letter",
    r"do\s+not\s+send\s+(?:a\s+)?cover\s+letter",
    r"don'?t\s+send\s+(?:a\s+)?cover\s+letter",
    r"no\s+cover\s+letter",
    r"without\s+(?:a\s+)?cover\s+letter",
]

ASK_PATTERNS = [
    (r"\bsøknadsbrev\b", "søknadsbrev"),
    (r"\bmotivasjonsbrev\b", "motivasjonsbrev"),
    (r"\bcover\s*letters?\b", "cover letter"),
    (r"\bapplication\s+letters?\b", "application letter"),
    (r"\bsøknadstekst\b", "søknadstekst"),
    (r"\bpersonlig(?:e|t)?\s+søknad(?:en)?\b", "personlig søknad"),
    (r"\bpersonlig(?:e|t)?\s+brev\b", "personlig brev"),
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


def load_labeled_from_log() -> dict[str, dict[str, dict]]:
    text = LOG.read_text(encoding="utf-8", errors="replace")
    by_cat: dict[str, dict[str, dict]] = {
        "asks": {},
        "silent": {},
        "rejects": {},
        "error": {},
    }
    for m in re.finditer(r'\{\s*"ok":\s*true[\s\S]*?\n\}', text):
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if obj.get("toolName") != "scan_jobs_batch":
            continue
        for item in obj.get("result", {}).get("batch") or []:
            cat = item.get("category")
            if cat in by_cat and item.get("id"):
                by_cat[cat][str(item["id"])] = item
    return by_cat


def unwrap_ld(data):
    if isinstance(data, dict) and "script:ld+json" in data:
        return data["script:ld+json"]
    return data


def html_to_text(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def fetch_ad(ad_id: str) -> dict:
    url = f"https://www.finn.no/job/ad/{ad_id}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8", "replace")
    title = None
    company = None
    description = ""
    for m in re.finditer(
        r'<script type="application/ld\+json">(.*?)</script>', page, flags=re.S
    ):
        try:
            parsed = unwrap_ld(json.loads(m.group(1).strip()))
        except json.JSONDecodeError:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                title = (item.get("title") or "").strip() or title
                org = item.get("hiringOrganization")
                if isinstance(org, str):
                    company = org
                elif isinstance(org, dict):
                    company = org.get("name")
                description = html_to_text(item.get("description") or "")
                break
        if description:
            break
    return {
        "id": ad_id,
        "url": url,
        "title": title or f"Annonse {ad_id}",
        "company": company,
        "description": description,
    }


def gold_label(text: str) -> dict:
    norm = text.replace("\u00a0", " ")
    for pat in REJECT_PATTERNS:
        m = re.search(pat, norm, flags=re.I)
        if m:
            return {
                "gold": "rejects",
                "matched": m.group(0),
                "uncertain": False,
                "uncertainMatched": None,
            }
    for pat, name in ASK_PATTERNS:
        m = re.search(pat, norm, flags=re.I)
        if m:
            return {
                "gold": "asks",
                "matched": m.group(0),
                "uncertain": False,
                "uncertainMatched": None,
            }
    for pat, name in UNCERTAIN_PATTERNS:
        m = re.search(pat, norm, flags=re.I)
        if m:
            return {
                "gold": "silent",
                "matched": None,
                "uncertain": True,
                "uncertainMatched": m.group(0),
            }
    return {
        "gold": "silent",
        "matched": None,
        "uncertain": False,
        "uncertainMatched": None,
    }


def context_snippet(text: str, needle: str | None, width: int = 110) -> str | None:
    if not needle:
        return None
    low = text.lower()
    i = low.find(needle.lower())
    if i < 0:
        i = low.find(needle.split()[0].lower())
    if i < 0:
        return None
    start = max(0, i - width // 2)
    end = min(len(text), i + len(needle) + width // 2)
    snip = text[start:end].strip()
    if start > 0:
        snip = "…" + snip
    if end < len(text):
        snip = snip + "…"
    return snip


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    labeled = load_labeled_from_log()
    rng = random.Random(SEED)

    asks_ids = list(labeled["asks"])
    silent_ids = list(labeled["silent"])
    reject_ids = list(labeled["rejects"])
    rng.shuffle(asks_ids)
    rng.shuffle(silent_ids)

    sample = {
        "asks": asks_ids[:100],
        "silent": silent_ids[:100],
        "rejects": sorted(reject_ids),
    }

    population = {k: len(v) for k, v in labeled.items() if k != "error"}
    results = []
    errors = []

    plan = (
        [("asks", i) for i in sample["asks"]]
        + [("silent", i) for i in sample["silent"]]
        + [("rejects", i) for i in sample["rejects"]]
    )
    print(
        f"population={population} sample_sizes="
        f"asks={len(sample['asks'])} silent={len(sample['silent'])} rejects={len(sample['rejects'])}",
        flush=True,
    )

    for n, (pred, ad_id) in enumerate(plan, 1):
        meta = labeled[pred][ad_id]
        try:
            time.sleep(0.12)
            ad = fetch_ad(ad_id)
            if not ad["description"]:
                raise RuntimeError("empty description")
            gold = gold_label(ad["description"])
            row = {
                "id": ad_id,
                "url": ad["url"],
                "title": ad["title"],
                "company": ad["company"] or meta.get("company"),
                "predicted": pred,
                "gold": gold["gold"],
                "goldMatched": gold["matched"],
                "uncertain": gold["uncertain"],
                "uncertainMatched": gold["uncertainMatched"],
                "predictedMatched": meta.get("matched"),
                "correct": pred == gold["gold"],
                "snippet": context_snippet(
                    ad["description"],
                    gold["matched"] or gold["uncertainMatched"] or meta.get("matched"),
                ),
                "descLen": len(ad["description"]),
            }
            results.append(row)
        except Exception as exc:  # noqa: BLE001
            errors.append({"id": ad_id, "predicted": pred, "error": str(exc)})
        if n % 25 == 0 or n == len(plan):
            print(f"progress {n}/{len(plan)} ok={len(results)} err={len(errors)}", flush=True)

    by_pred = {k: [r for r in results if r["predicted"] == k] for k in ("asks", "silent", "rejects")}
    confusion = Counter((r["predicted"], r["gold"]) for r in results)
    mis = [r for r in results if not r["correct"]]
    uncertain = [r for r in results if r["uncertain"]]

    synonym_keys = [
        "motivasjonsbrev",
        "søknadstekst",
        "personlig søknad",
        "personlig brev",
        "fortell hvorfor du søker",
        "beskriv hvorfor du søker",
        "cover letter",
    ]
    synonym_hits = {k: [] for k in synonym_keys}
    for r in results:
        blob = f"{r.get('goldMatched') or ''} {r.get('uncertainMatched') or ''} {r.get('predictedMatched') or ''}".lower()
        for key in synonym_keys:
            if key in blob:
                synonym_hits[key].append(
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "predicted": r["predicted"],
                        "gold": r["gold"],
                        "matched": r.get("goldMatched") or r.get("uncertainMatched"),
                        "url": r["url"],
                    }
                )

    def rate(pred: str, gold: str) -> float:
        rows = by_pred[pred]
        if not rows:
            return 0.0
        return sum(1 for r in rows if r["gold"] == gold) / len(rows)

    pop_asks = population["asks"]
    pop_silent = population["silent"]
    pop_rejects = population["rejects"]

    est = {
        "asks": pop_asks * rate("asks", "asks")
        + pop_silent * rate("silent", "asks")
        + pop_rejects * rate("rejects", "asks"),
        "silent": pop_asks * rate("asks", "silent")
        + pop_silent * rate("silent", "silent")
        + pop_rejects * rate("rejects", "silent"),
        "rejects": pop_asks * rate("asks", "rejects")
        + pop_silent * rate("silent", "rejects")
        + pop_rejects * rate("rejects", "rejects"),
    }
    est_total = sum(est.values()) or 1

    def mis_rate(pred: str) -> tuple[float, int, int]:
        rows = by_pred[pred]
        wrong = sum(1 for r in rows if not r["correct"])
        n = len(rows)
        p = wrong / n if n else 0.0
        se = (p * (1 - p) / n) ** 0.5 if n else 0.0
        return p, max(0.0, p - 1.96 * se), min(1.0, p + 1.96 * se)

    report = {
        "meta": {
            "seed": SEED,
            "populationFromLog": population,
            "sampleSizes": {k: len(v) for k, v in sample.items()},
            "audited": len(results),
            "fetchErrors": len(errors),
            "goldAskIncludes": [name for _, name in ASK_PATTERNS],
            "uncertainSignals": [name for _, name in UNCERTAIN_PATTERNS],
        },
        "accuracyByPredicted": {
            pred: {
                "n": len(by_pred[pred]),
                "correct": sum(1 for r in by_pred[pred] if r["correct"]),
                "accuracy": round(
                    sum(1 for r in by_pred[pred] if r["correct"]) / len(by_pred[pred]), 3
                )
                if by_pred[pred]
                else None,
                "misclassificationRate": round(mis_rate(pred)[0], 3),
                "misclassificationRate95CI": [
                    round(mis_rate(pred)[1], 3),
                    round(mis_rate(pred)[2], 3),
                ],
                "goldBreakdown": dict(Counter(r["gold"] for r in by_pred[pred])),
            }
            for pred in ("asks", "silent", "rejects")
        },
        "confusionPredictedToGold": {
            f"{a}->{b}": n for (a, b), n in sorted(confusion.items())
        },
        "estimatedCorrectedPopulation": {
            "counts": {k: round(v) for k, v in est.items()},
            "percentages": {k: round(100 * v / est_total, 1) for k, v in est.items()},
            "method": "Reweighted predicted population by sample gold rates; rejects fully audited from recovered log IDs.",
        },
        "originalPopulation": {
            "counts": population,
            "percentages": {
                k: round(100 * v / sum(population.values()), 1)
                for k, v in population.items()
            },
        },
        "misclassifications": [
            {
                "id": r["id"],
                "title": r["title"],
                "company": r["company"],
                "url": r["url"],
                "predicted": r["predicted"],
                "gold": r["gold"],
                "matched": r["goldMatched"],
                "snippet": r["snippet"],
            }
            for r in mis
        ],
        "uncertainCases": [
            {
                "id": r["id"],
                "title": r["title"],
                "company": r["company"],
                "url": r["url"],
                "predicted": r["predicted"],
                "gold": r["gold"],
                "uncertainMatched": r["uncertainMatched"],
                "snippet": r["snippet"],
            }
            for r in uncertain
        ],
        "synonymHitsInAuditSample": {k: v for k, v in synonym_hits.items() if v},
        "fetchErrors": errors,
        "samples": {
            "asks": [r for r in results if r["predicted"] == "asks"][:20],
            "silent": [r for r in results if r["predicted"] == "silent"][:20],
            "rejects": [r for r in results if r["predicted"] == "rejects"],
        },
    }

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    project_out = STATE / "classification-audit.json"
    project_out.write_text(OUT_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    print("Wrote", OUT_JSON)
    print("accuracy", report["accuracyByPredicted"])
    print("miscount", len(mis), "uncertain", len(uncertain))
    print("corrected", report["estimatedCorrectedPopulation"])


if __name__ == "__main__":
    main()
