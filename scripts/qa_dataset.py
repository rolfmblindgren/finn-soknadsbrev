#!/usr/bin/env python3
"""Punkt 1: QA og dekningsdokumentasjon for fryst originaldatasett."""

from __future__ import annotations

import json
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIG = ROOT / "data" / "original" / "observations.v1.jsonl"
OUT = ROOT / "data" / "qa" / "dataset_qa.json"
SEARCH = "https://www.finn.no/job/job-search-page/api/search/SEARCH_ID_JOB_FULLTIME"
UA = "FinnSoknadsbrevBot/0.1 (+qa-coverage)"


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    rows = [json.loads(l) for l in ORIG.read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [r["id"] for r in rows]
    id_counts = Counter(ids)

    missing = {
        "id": sum(1 for r in rows if not r.get("id")),
        "url": sum(1 for r in rows if not r.get("url")),
        "industry": sum(1 for r in rows if not r.get("industry")),
        "industryValue": sum(1 for r in rows if not r.get("industryValue")),
        "classificationText": sum(1 for r in rows if not r.get("classificationText")),
        "originalClassification": sum(1 for r in rows if not r.get("originalClassification")),
        "title": sum(1 for r in rows if not r.get("title")),
        "company": sum(1 for r in rows if not r.get("company")),
    }

    class_counts = Counter(r.get("originalClassification") for r in rows)
    by_industry = Counter(r.get("industry") or "(mangler)" for r in rows)
    by_industry_value = Counter(r.get("industryValue") or "(mangler)" for r in rows)

    catalog = get_json(f"{SEARCH}?page=1")
    meta = catalog.get("metadata") or {}
    result_size = meta.get("result_size") or {}
    paging = meta.get("paging") or {}
    industry_filter = next(f for f in catalog["filters"] if f.get("name") == "industry")
    live_industries = []
    for item in industry_filter.get("filter_items") or []:
        live_industries.append(
            {
                "name": item.get("display_name"),
                "value": str(item.get("value")),
                "hits": int(item.get("hits") or 0),
            }
        )
    live_industries.sort(key=lambda x: x["value"])

    collected_by_value = defaultdict(set)
    for r in rows:
        if r.get("industryValue"):
            collected_by_value[str(r["industryValue"])].add(r["id"])

    industry_coverage = []
    for ind in live_industries:
        collected_n = len(collected_by_value.get(ind["value"], set()))
        industry_coverage.append(
            {
                "name": ind["name"],
                "value": ind["value"],
                "liveHits": ind["hits"],
                "collectedUniqueIds": collected_n,
                "ratioCollectedToLiveHits": round(collected_n / ind["hits"], 3)
                if ind["hits"]
                else None,
            }
        )

    page_cap_risk = [x for x in industry_coverage if (x["liveHits"] or 0) > 2500]

    data_values = set(by_industry_value) - {"(mangler)"}
    live_values = {x["value"] for x in live_industries}
    only_in_data = sorted(data_values - live_values)
    only_in_live = sorted(live_values - data_values)

    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset": {
            "path": "data/original/observations.v1.jsonl",
            "nRecords": len(rows),
            "uniqueFinnIds": len(id_counts),
            "duplicateIdRows": sum(c - 1 for c in id_counts.values() if c > 1),
            "duplicateIds": sorted([i for i, c in id_counts.items() if c > 1])[:50],
            "classificationCounts": dict(class_counts),
            "missingValues": missing,
            "nIndustriesPresent": len([k for k in by_industry if k != "(mangler)"]),
        },
        "collectionMethod": {
            "source": "FINN Jobb public search API + JobPosting JSON-LD on ad pages",
            "searchEndpoint": SEARCH,
            "strategy": (
                "Iterate all industry filters (sorted by value), paginate each filter, "
                "dedupe by FINN id (first industry filter wins), classify from ad description text."
            ),
            "scanCompletedAtApprox": "2026-10-14T20:21:25Z",
            "datasetFrozenAt": json.loads(
                (ROOT / "data" / "original" / "freeze.json").read_text()
            ).get("frozenAt"),
            "sha256": json.loads(
                (ROOT / "data" / "original" / "freeze.json").read_text()
            ).get("sha256"),
        },
        "liveCatalogSnapshot": {
            "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "matchCount": result_size.get("match_count"),
            "groupCount": result_size.get("group_count"),
            "unfilteredPagingLast": paging.get("last"),
            "rowsPerPageAssumed": 50,
            "unfilteredMaxViaPagination": 50 * int(paging.get("last") or 0),
            "nIndustryFilters": len(live_industries),
        },
        "coverageAssessment": {
            "collectedVsLiveGroupCount": {
                "collectedUniqueIds": len(id_counts),
                "liveGroupCount": result_size.get("group_count"),
                "liveMatchCount": result_size.get("match_count"),
                "note": (
                    "FINN exposes match_count and group_count; industry hits align with group-style counts. "
                    "Collected unique ids are not expected to equal match_count. "
                    "Comparison to group_count is the more relevant coverage benchmark."
                ),
            },
            "pageCapRiskIndustriesLiveHitsGt2500": page_cap_risk,
            "industryFiltersOnlyInLive": only_in_live,
            "industryValuesOnlyInData": only_in_data,
            "industryCoverageTable": industry_coverage,
            "sumLiveIndustryHits": sum(i["hits"] for i in live_industries),
            "sumCollectedAcrossIndustries": sum(
                len(s) for s in collected_by_value.values()
            ),
            "limitations": [
                "Ads without industry assignment in data: counted under missing industry.",
                "An ad can appear in multiple industry filters on FINN; we store first-seen industry only.",
                "Unfiltered search is capped at 50 pages (~2500 docs); industry sharding was used to expand coverage.",
                "Live catalog snapshot is after collection; market churn means some ads disappeared (404) and new ones appeared.",
                "Classification text was re-fetched for early rows; text may differ slightly from text at first classify time.",
            ],
        },
        "industryDistributionCollected": [
            {"industry": k, "n": v}
            for k, v in sorted(by_industry.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "wrote": str(OUT.relative_to(ROOT)),
                "nRecords": len(rows),
                "uniqueIds": len(id_counts),
                "duplicates": report["dataset"]["duplicateIdRows"],
                "missing": missing,
                "liveGroupCount": result_size.get("group_count"),
                "liveMatchCount": result_size.get("match_count"),
                "pageCapRisk": len(page_cap_risk),
                "nIndustries": report["dataset"]["nIndustriesPresent"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
