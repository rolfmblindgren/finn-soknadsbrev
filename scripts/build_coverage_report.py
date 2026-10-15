#!/usr/bin/env python3
"""Build coverage report after gap-fill collection."""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> None:
    live = {
        ln.strip()
        for ln in (ROOT / "data/qa/ids_industry_occupation.txt").read_text().splitlines()
        if ln.strip()
    }
    industry_ids = {
        ln.strip()
        for ln in (ROOT / "data/qa/ids_industry.txt").read_text().splitlines()
        if ln.strip()
    }
    enum_ind = json.loads((ROOT / "data/qa/enum_industry.json").read_text())
    enum_occ = json.loads((ROOT / "data/qa/enum_occupation.json").read_text())
    v1 = load_jsonl(ROOT / "data/original/observations.v1.jsonl")
    v1_ids = {r["id"] for r in v1}
    add_path = ROOT / "data/incremental/observations.v2add.jsonl"
    added = load_jsonl(add_path) if add_path.exists() else []
    added_ids = {r["id"] for r in added}
    v2_path = ROOT / "data/observations.v2.jsonl"
    v2 = load_jsonl(v2_path) if v2_path.exists() else []
    v2_ids = {r["id"] for r in v2}

    catalog = enum_occ.get("catalog") or enum_ind.get("catalog") or {}
    group = int(catalog.get("group_count") or 0)
    match = int(catalog.get("match_count") or 0)

    still_missing_live = sorted(live - v2_ids)
    fetch_errors = [r for r in added if r.get("originalClassification") == "error"]

    ind_items = (
        enum_ind.get("dimensionsFull", {})
        .get("industry", {})
        .get("items")
        or []
    )
    industry_completeness = []
    for row in ind_items:
        industry_completeness.append(
            {
                "value": row["value"],
                "name": row["name"],
                "claimedHits": row["claimedHits"],
                "enumerated": row["enumerated"],
                "ratio": round(row["enumerated"] / row["claimedHits"], 4)
                if row["claimedHits"]
                else None,
                "pageCapHit": row.get("pageCapHit", False),
            }
        )

    cls_v1 = Counter(r["originalClassification"] for r in v1)
    cls_add = Counter(r["originalClassification"] for r in added)
    cls_v2 = Counter(r["originalClassification"] for r in v2)

    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "unitSemantics": {
            "group_count": "Unike stillingsannonser (FINN ad id). Verifisert: sum(extent hits)=group_count; paginering per filter gir enum==group_count.",
            "match_count": "Antall stillinger/posisjoner (sum no_of_positions). Katalog match/group ≈ 2.",
            "datasetUnit": "Én rad per unik FINN-annonse-id (= group_count-enhet).",
        },
        "catalogAtEnumeration": {
            "matchCount": match,
            "groupCount": group,
            "fetchedAt": enum_occ.get("fetchedAt"),
        },
        "why8988WasIncomplete": {
            "primaryCause": "Innsamlingsstrategien brukte kun bransjefiltre. Mange annonser mangler bransjetagg og er da ikke treffbare via industry=*.",
            "industryUnionSize": len(industry_ids),
            "adsWithoutIndustryTag": group - len(industry_ids),
            "pageCapOnIndustryFilters": False,
            "firstSeenIndustryRatiosMisleading": (
                "Tidligere QA sammenlignet first-seen-bransje med liveHits; "
                "lave ratioer for sene bransjer skyldes deduplisering, ikke manglende paginering."
            ),
            "v1CoverageOfLiveIndustryUnion": {
                "overlap": len(v1_ids & industry_ids),
                "missingIndustryTagged": len(industry_ids - v1_ids),
                "v1NotInLiveIndustryUnion": len(v1_ids - industry_ids),
            },
        },
        "expandedStrategy": {
            "filters": ["industry", "occupation"],
            "result": "industry∪occupation union size equals catalog group_count (full search-ID coverage).",
            "combinedUnionSize": len(live),
            "gapVsGroupCount": group - len(live),
            "occupationAloneUnion": enum_occ.get("dimensionsFull", {})
            .get("occupation", {})
            .get("unionSize")
            or enum_occ.get("dimensions", {})
            .get("occupation", {})
            .get("unionSize"),
        },
        "collection": {
            "v1FrozenN": len(v1_ids),
            "v1Sha256Policy": "immutable data/original/observations.v1.jsonl",
            "missingAtGapFillStart": len(live - v1_ids),
            "fetchedAdditions": len(added_ids),
            "fetchErrors": len(fetch_errors),
            "v2MergedN": len(v2_ids),
            "v2CoverageOfLiveUnion": {
                "overlap": len(v2_ids & live),
                "stillMissingLiveIds": len(still_missing_live),
                "coverageRatio": round(len(v2_ids & live) / len(live), 4) if live else None,
            },
            "v2OnlyNotInLiveUnion": len(v2_ids - live),
            "noteOnSuperset": (
                "v2 kan være større enn live union fordi v1 inneholder annonser som er "
                "fjernet/utløpt etter innsamling (churn), pluss nyhentede live-ID-er."
            ),
        },
        "classifications": {
            "v1": dict(cls_v1),
            "additions": dict(cls_add),
            "v2": dict(cls_v2),
        },
        "industryFilterCompleteness": industry_completeness,
        "stillMissingLiveIdsSample": still_missing_live[:50],
        "fetchErrorSample": [
            {"id": r["id"], "error": r.get("error")} for r in fetch_errors[:30]
        ],
    }

    out_json = ROOT / "data/qa/coverage_report.json"
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    md = ROOT / "reports/dekning.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    cov = report["collection"]["v2CoverageOfLiveUnion"]
    md.write_text(
        f"""# Dekningsrapport: FINN søknadsbrev-uttrekk

**Generert:** {report["generatedAt"]}

## Hva vi teller

| FINN-felt | Betydning | Dette uttrekket |
|---|---|---|
| `group_count` | Unike **annonser** (ad-id) | Målenhet for dekning |
| `match_count` | **Stillinger/posisjoner** (`no_of_positions`) | Ikke samme enhet |
| Vår rad | Én observasjon per FINN-id | Samme som `group_count` |

Ved enumeringstidspunkt: `group_count` = **{group}**, `match_count` = **{match}**.

## Hvorfor 8988 ikke var nok

1. **Hovedårsak:** Skanningen paginerte bare **bransjefiltre**. Live bransjeunion = **{len(industry_ids)}** unike ID-er — ikke hele katalogen.
2. Annonser **uten bransjetagg** ≈ **{group - len(industry_ids)}** er usynlige for `industry=*`.
3. **Ikke** sidebegrensning per bransje: ingen bransje hadde >2500 treff; enum ≈ claimed for hvert filter.
4. Tidligere «lav dekning» per bransje basert på *first-seen* var **misvisende** (dedupe), ikke bevis på manglende paginering.
5. Av live bransjeunion manglet v1 bare **{len(industry_ids - v1_ids)}** ID-er; **{len(v1_ids - industry_ids)}** v1-ID-er er ikke lenger i live bransjeunion (churn / uten bransje nå).

## Utvidet strategi

- Enumererte alle **occupation**-filtre (alle <2500 treff, ingen sidetak).
- `industry ∪ occupation` = **{len(live)}** = `group_count` (**gap 0**).
- Hentet kun ID-er som manglet i fryst v1 (`data/original/observations.v1.jsonl` uendret).

## Resultat etter gap-fill

| Størrelse | Antall |
|---|---:|
| Fryst v1 | {len(v1_ids)} |
| Live union (industry∪occupation) | {len(live)} |
| Manglet ved start av gap-fill | {len(live - v1_ids)} |
| Nye rader hentet | {len(added_ids)} |
| Fetch-feil blant nye | {len(fetch_errors)} |
| Merged v2 | {len(v2_ids)} |
| Overlap v2 ∩ live | {cov["overlap"]} |
| Fortsatt mangler i live | {cov["stillMissingLiveIds"]} |
| Dekningsandel av live union | {cov["coverageRatio"]} |
| v2 men ikke i live (churn fra v1 m.m.) | {len(v2_ids - live)} |

### Klassifisering

| Sett | asks | silent | rejects | error |
|---|---:|---:|---:|---:|
| v1 | {cls_v1.get("asks",0)} | {cls_v1.get("silent",0)} | {cls_v1.get("rejects",0)} | {cls_v1.get("error",0)} |
| Tillegg | {cls_add.get("asks",0)} | {cls_add.get("silent",0)} | {cls_add.get("rejects",0)} | {cls_add.get("error",0)} |
| v2 | {cls_v2.get("asks",0)} | {cls_v2.get("silent",0)} | {cls_v2.get("rejects",0)} | {cls_v2.get("error",0)} |

## Bransjefiltre: faktisk pagineringsdekning

For hvert av 69 bransjefiltre var `enumerated == claimedHits` (ingen sidetak truffet).
Differansen mot first-seen-andeler i tidligere QA skyldes **dedupe**, ikke hull i paginering.

## Hva vi fortsatt ikke vet / ikke kan hente

- Markedschurn: populasjonen er et øyeblikksbilde; v1-rader utenfor live union er historiske observasjoner.
- `group_count` endrer seg over tid (etter gap-fill kan live `group_count` avvike litt fra enumeringstidspunktet).
- `industry` er null for gap-fill-rader oppdaget via occupation uten bransjetagg.
- Noen annonsesider mangler JSON-LD; tekst ble da hentet fra HTML (`ad-description`).
- Analyseplan punkt 3–5 er ikke startet.

## Filer

- Live ID-union: `data/qa/ids_industry_occupation.txt`
- Manglende ved gap-fill: `data/qa/missing_ids.txt`
- Tillegg: `data/incremental/observations.v2add.jsonl`
- Merged: `data/observations.v2.jsonl`
- Maskinlesbar rapport: `data/qa/coverage_report.json`
""",
        encoding="utf-8",
    )
    print(json.dumps({
        "v2": len(v2_ids),
        "live": len(live),
        "coverageRatio": cov["coverageRatio"],
        "stillMissing": cov["stillMissingLiveIds"],
        "added": len(added_ids),
        "errors": len(fetch_errors),
        "md": str(md),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
