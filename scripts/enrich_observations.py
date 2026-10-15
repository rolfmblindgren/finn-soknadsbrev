#!/usr/bin/env python3
"""Enrich v2 observations with FINN filter membership + heuristics.

Adds sector, occupation tags, experience, education flags, agency flag.
Polite search-API pagination only; resumes via checkpoint.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

UA = "FinnSoknadsbrevBot/0.1 (+research; cover-letter)"
API = "https://www.finn.no/job/job-search-page/api/search/SEARCH_ID_JOB_FULLTIME"
ROOT = Path(__file__).resolve().parents[1]

AGENCY_COMPANY_PATTERNS = [
    r"\badecco\b", r"\bmanpower\b", r"\brandstad\b", r"\bstudent\s*consulting\b",
    r"\bkelly\s+services\b", r"\bexperis\b", r"\bproffice\b", r"\bacademic\s+work\b",
    r"\bjobzone\b", r"\bpersonalhuset\b", r"\bstart\s+people\b", r"\bcapus\b",
    r"\blayton\b", r"\buniq\s+partners\b", r"\bhays\b", r"\brobert\s+half\b",
    r"\bharvey\s+nash\b", r"\bambition\b", r"\bmatch\b", r"\bhead\s+energy\b",
    r"\bpersonnel\b", r"\bbemanning\b", r"\brecruit\b", r"\brekrutter",
    r"\bstaffing\b", r"\bkarrieresenter\b",
]

PUBLIC_COMPANY_PATTERNS = [
    r"\bkommune\b", r"\bfylkeskommune\b", r"\bstaten\b", r"\bdepartement",
    r"\bdirektorat", r"\btilsyn\b", r"\betaten\b", r"\bsykehus",
    r"\bhelse\s+(sør|vest|nord|midt)", r"\bhf\b", r"\bbufetat\b", r"\bnav\b",
    r"\bforsvaret\b", r"\bpolitiet\b", r"\buniversitet", r"\bhøgskol",
    r"\bhogskol", r"\boslomet\b", r"\bntnu\b", r"\buib\b", r"\buio\b",
    r"\buit\b", r"\bstortinget\b", r"\bstatsforvalter",
]

LEVEL_PATTERNS = {
    "leder": [r"\bleder\b", r"\bdirektør\b", r"\bdirector\b", r"\bmanager\b", r"\bsjef\b", r"\bhead\s+of\b"],
    "junior": [r"\bjunior\b", r"\btrainee\b", r"\bleærling\b", r"\blærling\b", r"\bgraduate\b", r"\bintern\b", r"\bpraktikant\b"],
    "senior": [r"\bsenior\b", r"\bprincipal\b", r"\bstaff\b"],
}


def get(params: dict, delay: float, retries: int = 5) -> dict:
    if delay:
        time.sleep(delay)
    qs = urllib.parse.urlencode(params)
    url = API + "?" + qs
    err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            err = e
            time.sleep(min(2**attempt, 16))
    raise RuntimeError(f"GET failed {url}: {err}")


def enumerate_params(params: dict, delay: float, keep: set[str] | None = None) -> set[str]:
    ids: set[str] = set()
    page = 1
    while True:
        q = dict(params)
        q["page"] = page
        d = get(q, delay)
        docs = d.get("docs") or []
        last = int(d.get("metadata", {}).get("paging", {}).get("last") or page)
        for doc in docs:
            i = str(doc["id"])
            if keep is None or i in keep:
                ids.add(i)
        if not docs or page >= last:
            break
        page += 1
    return ids


def any_re(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--observations", default=str(ROOT / "data/observations.v2.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "data/analysis/observations.enriched.jsonl"))
    ap.add_argument("--checkpoint", default=str(ROOT / "data/analysis/enrich.ckpt.json"))
    ap.add_argument("--delay", type=float, default=0.16)
    ap.add_argument("--skip-api", action="store_true")
    args = ap.parse_args()

    rows = []
    with open(args.observations) as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    keep = {r["id"] for r in rows}
    print(f"observations={len(rows)}", flush=True)

    ckpt_path = Path(args.checkpoint)
    ckpt_path.parent.mkdir(parents=True, exist_ok=True)
    ckpt: dict = {"sector": {}, "occupations": {}, "experience": {}, "education": {}, "bemanning_filter": [], "done": {}}
    if ckpt_path.exists():
        ckpt = json.loads(ckpt_path.read_text())
        print("resumed checkpoint", flush=True)

    if not args.skip_api:
        root = get({"page": 1}, args.delay)
        filters = {f["name"]: f.get("filter_items") or [] for f in (root.get("filters") or [])}
        catalog = root.get("metadata", {}).get("result_size", {})
        print("catalog", catalog, flush=True)

        if not ckpt.get("done", {}).get("occupation"):
            occ_map: dict[str, list[str]] = defaultdict(list)
            items = filters["occupation"]
            for i, item in enumerate(sorted(items, key=lambda x: str(x["value"]))):
                val = str(item["value"])
                name = item.get("display_name") or val
                ids = enumerate_params({"occupation": val}, args.delay, keep)
                for ad_id in ids:
                    occ_map[ad_id].append(name)
                print(f"[occ {i+1}/{len(items)}] {name[:40]:40} n={len(ids)}", flush=True)
            ckpt["occupations"] = dict(occ_map)
            ckpt.setdefault("done", {})["occupation"] = True
            ckpt_path.write_text(json.dumps(ckpt))

        if not ckpt.get("done", {}).get("sector"):
            sector_map: dict[str, str] = dict(ckpt.get("sector") or {})
            sectors = {str(i["value"]): i.get("display_name") or str(i["value"]) for i in filters["job_sector"]}
            for val, name in sectors.items():
                hits = next(int(i.get("hits") or 0) for i in filters["job_sector"] if str(i["value"]) == val)
                if hits > 2500:
                    continue
                ids = enumerate_params({"job_sector": val}, args.delay, keep)
                for ad_id in ids:
                    sector_map.setdefault(ad_id, name)
                print(f"[sector small] {name} n={len(ids)}", flush=True)
                ckpt["sector"] = sector_map
                ckpt_path.write_text(json.dumps(ckpt))

            large = [(str(i["value"]), i.get("display_name") or str(i["value"])) for i in filters["job_sector"] if int(i.get("hits") or 0) > 2500]
            occ_items = sorted(filters["occupation"], key=lambda x: str(x["value"]))
            done_pairs = set(ckpt.get("done", {}).get("sector_pairs") or [])
            for sval, sname in large:
                for i, item in enumerate(occ_items):
                    oval = str(item["value"])
                    key = f"{sval}|{oval}"
                    if key in done_pairs:
                        continue
                    ids = enumerate_params({"job_sector": sval, "occupation": oval}, args.delay, keep)
                    for ad_id in ids:
                        sector_map.setdefault(ad_id, sname)
                    done_pairs.add(key)
                    ckpt["sector"] = sector_map
                    ckpt.setdefault("done", {})["sector_pairs"] = sorted(done_pairs)
                    ckpt_path.write_text(json.dumps(ckpt))
                    if (i + 1) % 10 == 0 or i == 0:
                        print(f"[sector {sname} occ {i+1}/{len(occ_items)}] mapped={len(sector_map)}", flush=True)
            ckpt["sector"] = sector_map
            ckpt.setdefault("done", {})["sector"] = True
            ckpt_path.write_text(json.dumps(ckpt))

        if not ckpt.get("done", {}).get("experience"):
            exp_map: dict[str, list[str]] = defaultdict(list)
            items = filters["work_experience"]
            occ_items = sorted(filters["occupation"], key=lambda x: str(x["value"]))
            for item in items:
                val = str(item["value"])
                name = item.get("display_name") or val
                hits = int(item.get("hits") or 0)
                if hits <= 2500:
                    ids = enumerate_params({"work_experience": val}, args.delay, keep)
                else:
                    ids = set()
                    for oi, oitem in enumerate(occ_items):
                        oval = str(oitem["value"])
                        part = enumerate_params({"work_experience": val, "occupation": oval}, args.delay, keep)
                        ids |= part
                        if (oi + 1) % 20 == 0:
                            print(f"[exp {name} occ {oi+1}/{len(occ_items)}] n={len(ids)}", flush=True)
                for ad_id in ids:
                    exp_map[ad_id].append(name)
                print(f"[exp] {name} n={len(ids)}", flush=True)
            ckpt["experience"] = dict(exp_map)
            ckpt.setdefault("done", {})["experience"] = True
            ckpt_path.write_text(json.dumps(ckpt))

        if not ckpt.get("done", {}).get("education"):
            edu_map: dict[str, list[str]] = defaultdict(list)
            items = filters["education"]
            occ_items = sorted(filters["occupation"], key=lambda x: str(x["value"]))
            for item in items:
                val = str(item["value"])
                name = item.get("display_name") or val
                hits = int(item.get("hits") or 0)
                if hits <= 2500:
                    ids = enumerate_params({"education": val}, args.delay, keep)
                else:
                    ids = set()
                    for oi, oitem in enumerate(occ_items):
                        part = enumerate_params({"education": val, "occupation": str(oitem["value"])}, args.delay, keep)
                        ids |= part
                for ad_id in ids:
                    edu_map[ad_id].append(name)
                print(f"[edu] {name} n={len(ids)}", flush=True)
            ckpt["education"] = dict(edu_map)
            ckpt.setdefault("done", {})["education"] = True
            ckpt_path.write_text(json.dumps(ckpt))

        if not ckpt.get("done", {}).get("bemanning"):
            bem = next((i for i in filters.get("job_duration", []) if "bemanning" in (i.get("display_name") or "").lower() or str(i.get("value")) == "8901"), None)
            ids: list[str] = []
            if bem:
                ids = sorted(enumerate_params({"job_duration": str(bem["value"])}, args.delay, keep))
            ckpt["bemanning_filter"] = ids
            ckpt.setdefault("done", {})["bemanning"] = True
            ckpt_path.write_text(json.dumps(ckpt))
            print(f"[bemanning filter] n={len(ids)}", flush=True)

    sector = ckpt.get("sector") or {}
    occupations = ckpt.get("occupations") or {}
    experience = ckpt.get("experience") or {}
    education = ckpt.get("education") or {}
    bemanning_ids = set(ckpt.get("bemanning_filter") or [])

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_agency = n_public = 0
    with out_path.open("w") as out:
        for r in rows:
            ad_id = r["id"]
            company = (r.get("company") or "").strip()
            title = (r.get("title") or "").strip()
            agency_company = any_re(AGENCY_COMPANY_PATTERNS, company)
            agency_filter = ad_id in bemanning_ids
            is_agency = bool(agency_company or agency_filter)
            finn_sector = sector.get(ad_id)
            public_heuristic = any_re(PUBLIC_COMPANY_PATTERNS, company)
            if finn_sector == "Offentlig":
                sector_final = "Offentlig"
            elif finn_sector == "Privat":
                sector_final = "Privat"
            elif finn_sector:
                sector_final = finn_sector
            elif public_heuristic:
                sector_final = "Offentlig (heuristic)"
            else:
                sector_final = "Ukjent"
            levels = [lab for lab, pats in LEVEL_PATTERNS.items() if any_re(pats, title)]
            occs = occupations.get(ad_id) or []
            enriched = {
                **r,
                "enrichment": {
                    "finnSector": finn_sector,
                    "sector": sector_final,
                    "sectorSource": ("finn" if finn_sector else ("company_heuristic" if public_heuristic else None)),
                    "occupations": occs,
                    "occupationPrimary": occs[0] if occs else None,
                    "experienceTags": experience.get(ad_id) or [],
                    "educationTags": education.get(ad_id) or [],
                    "isRecruitmentAgency": is_agency,
                    "agencySignals": {"companyPattern": agency_company, "finnBemanningsbyraFilter": agency_filter},
                    "titleLevelTags": levels,
                    "hasIndustry": bool(r.get("industry")),
                },
            }
            if is_agency:
                n_agency += 1
            if sector_final.startswith("Offentlig"):
                n_public += 1
            out.write(json.dumps(enriched, ensure_ascii=False) + "\n")

    print(json.dumps({"out": str(out_path), "n": len(rows), "withSectorFinn": sum(1 for i in keep if i in sector), "agency": n_agency, "publicish": n_public, "withOccupation": sum(1 for i in keep if i in occupations)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
