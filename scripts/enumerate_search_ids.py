#!/usr/bin/env python3
"""Enumerate FINN Job search result IDs for one or more filter dimensions.

Polite pagination only (search API). Does not fetch ad pages.
Supports resume via checkpoint JSON next to --out.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "FinnSoknadsbrevBot/0.1 (+research; cover-letter)"
API = "https://www.finn.no/job/job-search-page/api/search/SEARCH_ID_JOB_FULLTIME"


def get(params: dict, delay: float, retries: int = 5) -> dict:
    if delay > 0:
        time.sleep(delay)
    qs = urllib.parse.urlencode(params)
    url = API + "?" + qs
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": UA},
            )
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"GET failed after {retries} retries: {url}: {last_err}")


def enumerate_one_item(
    param: str, val: str, delay: float
) -> tuple[set[str], dict]:
    ids: set[str] = set()
    page = 1
    last = 1
    group_count = 0
    match_count = 0
    while True:
        d = get({"page": page, param: val}, delay)
        docs = d.get("docs") or []
        paging = d.get("metadata", {}).get("paging", {})
        rs = d.get("metadata", {}).get("result_size", {})
        last = int(paging.get("last") or page)
        group_count = int(rs.get("group_count") or 0)
        match_count = int(rs.get("match_count") or 0)
        for doc in docs:
            ids.add(str(doc["id"]))
        if not docs or page >= last:
            break
        page += 1
    meta = {
        "enumerated": len(ids),
        "lastPage": page,
        "groupCount": group_count,
        "matchCount": match_count,
        "pageCapHit": group_count > 2500 or last >= 50,
    }
    return ids, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--filters",
        default="industry",
        help="Comma-separated filter names",
    )
    ap.add_argument("--delay", type=float, default=0.18)
    ap.add_argument("--out", required=True, help="JSON summary path")
    ap.add_argument("--ids-out", help="Write all unique IDs one per line")
    ap.add_argument(
        "--prior-ids",
        help="Existing ID list (txt) included in combined union",
    )
    ap.add_argument(
        "--checkpoint",
        help="Checkpoint path (default: <out>.ckpt.json)",
    )
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ckpt_path = Path(args.checkpoint or (str(out_path) + ".ckpt.json"))

    root = get({"page": 1}, args.delay)
    catalog = root.get("metadata", {}).get("result_size", {})
    filters_by_name = {
        f.get("name"): f.get("filter_items") or []
        for f in (root.get("filters") or [])
    }

    prior: set[str] = set()
    if args.prior_ids:
        prior = {
            ln.strip()
            for ln in Path(args.prior_ids).read_text().splitlines()
            if ln.strip()
        }

    ckpt: dict = {"done": {}, "ids": {}}
    if ckpt_path.exists():
        ckpt = json.loads(ckpt_path.read_text())
        print(f"resuming checkpoint {ckpt_path}", flush=True)

    wanted = [x.strip() for x in args.filters.split(",") if x.strip()]
    all_ids: set[str] = set(prior)
    for filt, id_list in (ckpt.get("ids") or {}).items():
        all_ids.update(id_list)

    dimensions: dict[str, dict] = {}

    for name in wanted:
        items = filters_by_name.get(name)
        if items is None:
            raise SystemExit(f"Unknown filter {name!r}; have {sorted(filters_by_name)}")
        done_keys = set(ckpt.get("done", {}).get(name, []))
        union: set[str] = set(ckpt.get("ids", {}).get(name, []))
        per: list[dict] = []
        before_dim = len(all_ids)

        for i, item in enumerate(sorted(items, key=lambda x: str(x["value"]))):
            val = str(item["value"])
            disp = item.get("display_name") or val
            claimed = int(item.get("hits") or 0)
            key = val
            if key in done_keys:
                print(f"[{name} {i+1}/{len(items)}] {val} SKIP (cached)", flush=True)
                continue
            ids, meta = enumerate_one_item(name, val, args.delay)
            before = len(union)
            union |= ids
            all_ids |= ids
            row = {
                "value": val,
                "name": disp,
                "claimedHits": claimed,
                **meta,
                "newToUnion": len(union) - before,
            }
            per.append(row)
            ckpt.setdefault("done", {}).setdefault(name, []).append(key)
            ckpt.setdefault("ids", {})[name] = sorted(union)
            ckpt_path.write_text(json.dumps(ckpt))
            print(
                f"[{name} {i+1}/{len(items)}] {val} {disp[:36]:36} "
                f"claim={claimed:4} enum={meta['enumerated']:4} pages={meta['lastPage']:2} "
                f"new={row['newToUnion']:4} union={len(union)} combined={len(all_ids)}",
                flush=True,
            )

        dimensions[name] = {
            "unionSize": len(union),
            "newVsPriorCombined": len(all_ids) - before_dim,
            "sumClaimedHits": sum(int(i.get("hits") or 0) for i in items),
            "pageCapRisk": [r for r in per if r.get("pageCapHit")],
            "items": per,
        }
        print(
            f"== {name}: union={len(union)} combined={len(all_ids)} "
            f"catalog_group={catalog.get('group_count')}",
            flush=True,
        )

    out = {
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "catalog": catalog,
        "filters": wanted,
        "combinedUnionSize": len(all_ids),
        "gapVsGroupCount": int(catalog.get("group_count") or 0) - len(all_ids),
        "priorIdsIncluded": len(prior),
        "dimensions": {k: {kk: vv for kk, vv in v.items() if kk != "items"} | {"nItemsLogged": len(v.get("items") or [])} for k, v in dimensions.items()},
        "dimensionsFull": dimensions,
    }
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    if args.ids_out:
        Path(args.ids_out).write_text("\n".join(sorted(all_ids)) + "\n")
    print(
        json.dumps(
            {
                "combinedUnionSize": out["combinedUnionSize"],
                "gapVsGroupCount": out["gapVsGroupCount"],
                "catalog": catalog,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
