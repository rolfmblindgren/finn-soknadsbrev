#!/usr/bin/env python3
"""
Rebuild a fully auditable observation set for the Finn cover-letter scan.

The live scan originally kept only aggregate counters + a tool log. Industry and
classification text were not durably stored per ad. This script reconstructs:

  - originalClassification + matched from scan.log batch results
  - industry = first industry filter (same sort order as the BDK scanner)
    that contains the ad id
  - classificationText = re-fetched JobPosting description from finn.no

Output:
  data/observations.jsonl
  data/observations.manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".agent-serve" / "scan-state"
LOG = STATE / "scan.log"
OUT_DIR = ROOT / "data"
OUT_JSONL = OUT_DIR / "observations.jsonl"
OUT_MANIFEST = OUT_DIR / "observations.manifest.json"
SEARCH_API = (
    "https://www.finn.no/job/job-search-page/api/search/SEARCH_ID_JOB_FULLTIME"
)
UA = "FinnSoknadsbrevBot/0.1 (+rebuild-observations; reproducibility)"


def get_json(url: str, delay: float) -> dict:
    if delay:
        time.sleep(delay)
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_html(url: str, delay: float) -> str:
    if delay:
        time.sleep(delay)
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "text/html"}
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", "replace")


def load_labels_from_log() -> dict[str, dict]:
    if not LOG.exists():
        raise SystemExit(f"Missing scan log: {LOG}")
    text = LOG.read_text(encoding="utf-8", errors="replace")
    by_id: dict[str, dict] = {}
    for m in re.finditer(r'\{\s*"ok":\s*true[\s\S]*?\n\}', text):
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if obj.get("toolName") != "scan_jobs_batch":
            continue
        for item in obj.get("result", {}).get("batch") or []:
            ad_id = str(item.get("id") or "")
            if not ad_id:
                continue
            by_id[ad_id] = {
                "id": ad_id,
                "originalClassification": item.get("category"),
                "matched": item.get("matched"),
                "title": item.get("title"),
                "company": item.get("company"),
                "url": item.get("url") or f"https://www.finn.no/job/ad/{ad_id}",
                "error": item.get("error"),
            }
    return by_id


def list_industries(delay: float) -> list[dict]:
    data = get_json(f"{SEARCH_API}?page=1", delay)
    filt = next(f for f in data["filters"] if f.get("name") == "industry")
    industries = [
        {
            "name": str(i.get("display_name") or i.get("value")),
            "value": str(i.get("value")),
            "hits": int(i.get("hits") or 0),
        }
        for i in filt.get("filter_items") or []
        if i.get("value") is not None
    ]
    industries.sort(key=lambda x: x["value"])
    return industries


def assign_industries(
    labels: dict[str, dict], delay: float
) -> dict[str, dict]:
    """First-seen industry in scanner order (sorted by industry value)."""
    industries = list_industries(delay)
    remaining = set(labels)
    assigned: dict[str, dict] = {}
    print(f"industry walk: {len(industries)} filters, {len(remaining)} labeled ids", flush=True)
    for ind in industries:
        if not remaining:
            break
        page = 1
        last = 1
        while page <= last and remaining:
            data = get_json(
                f"{SEARCH_API}?page={page}&industry={ind['value']}", delay
            )
            meta = data.get("metadata") or {}
            last = int((meta.get("paging") or {}).get("last") or page)
            for doc in data.get("docs") or []:
                ad_id = str(doc.get("id"))
                if ad_id in remaining:
                    assigned[ad_id] = {
                        "industry": ind["name"],
                        "industryValue": ind["value"],
                    }
                    labels[ad_id].setdefault("title", doc.get("job_title") or doc.get("heading"))
                    labels[ad_id].setdefault("company", doc.get("company_name"))
                    if not labels[ad_id].get("url"):
                        labels[ad_id]["url"] = doc.get("canonical_url") or (
                            f"https://www.finn.no/job/ad/{ad_id}"
                        )
                    remaining.remove(ad_id)
            page += 1
        print(
            f"  {ind['name']}: assigned_total={len(assigned)} remaining={len(remaining)}",
            flush=True,
        )
    for ad_id in remaining:
        assigned[ad_id] = {"industry": None, "industryValue": None}
    return assigned


def unwrap_ld(data):
    if isinstance(data, dict) and "script:ld+json" in data:
        return data["script:ld+json"]
    return data


def html_to_text(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    for a, b in [
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&#39;", "'"),
        ("&quot;", '"'),
    ]:
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def fetch_description(ad_id: str, delay: float) -> tuple[str, str | None, str | None]:
    page = get_html(f"https://www.finn.no/job/ad/{ad_id}", delay)
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
                title = (item.get("title") or "").strip() or None
                org = item.get("hiringOrganization")
                company = org if isinstance(org, str) else (org or {}).get("name")
                return html_to_text(item.get("description") or ""), title, company
    return "", None, None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=0.12)
    parser.add_argument("--limit", type=int, default=0, help="optional cap for smoke tests")
    parser.add_argument(
        "--skip-text",
        action="store_true",
        help="only rebuild labels+industry (no description fetch)",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = load_labels_from_log()
    print(f"labels from log: {len(labels)} {Counter(v['originalClassification'] for v in labels.values())}", flush=True)

    industries = assign_industries(labels, args.delay)

    ids = sorted(labels)
    if args.limit:
        ids = ids[: args.limit]

    tmp = OUT_JSONL.with_suffix(".jsonl.partial")
    if tmp.exists():
        tmp.unlink()

    fetch_errors = 0
    with tmp.open("w", encoding="utf-8") as out:
        for n, ad_id in enumerate(ids, 1):
            base = labels[ad_id]
            ind = industries.get(ad_id) or {"industry": None, "industryValue": None}
            text = ""
            title = base.get("title")
            company = base.get("company")
            err = base.get("error")
            if not args.skip_text and base.get("originalClassification") != "error":
                try:
                    text, t2, c2 = fetch_description(ad_id, args.delay)
                    title = title or t2
                    company = company or c2
                    if not text:
                        fetch_errors += 1
                        err = (err or "") + " empty description on rebuild"
                except Exception as exc:  # noqa: BLE001
                    fetch_errors += 1
                    err = f"rebuild fetch failed: {exc}"
            record = {
                "id": ad_id,
                "url": base.get("url") or f"https://www.finn.no/job/ad/{ad_id}",
                "title": title,
                "company": company,
                "industry": ind.get("industry"),
                "industryValue": ind.get("industryValue"),
                "originalClassification": base.get("originalClassification"),
                "matched": base.get("matched"),
                "classificationText": text,
                "observedAt": None,
                "rebuiltAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "recordVersion": 1,
                "provenance": {
                    "originalClassificationSource": "scan.log batch results",
                    "industrySource": "re-walk of Finn industry filters in scanner order (first hit)",
                    "classificationTextSource": (
                        "re-fetched JobPosting JSON-LD"
                        if not args.skip_text
                        else "skipped"
                    ),
                    "note": (
                        "Original live scan did not persist per-ad text/industry; "
                        "classification label is from the historical tool log, "
                        "text/industry are reconstructed."
                    ),
                },
            }
            if err:
                record["error"] = err
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            if n % 50 == 0 or n == len(ids):
                print(f"text progress {n}/{len(ids)} fetch_errors={fetch_errors}", flush=True)

    tmp.replace(OUT_JSONL)
    counts = Counter()
    missing_text = 0
    missing_industry = 0
    with OUT_JSONL.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            counts[row["originalClassification"]] += 1
            if not row.get("classificationText"):
                missing_text += 1
            if not row.get("industry"):
                missing_industry += 1

    manifest = {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path": str(OUT_JSONL.relative_to(ROOT)),
        "nRecords": sum(counts.values()),
        "countsByOriginalClassification": dict(counts),
        "missingClassificationText": missing_text,
        "missingIndustry": missing_industry,
        "sha256": sha256_file(OUT_JSONL),
        "sources": {
            "labels": str(LOG.relative_to(ROOT)),
            "industry": "Finn search API industry filters",
            "text": "Finn job ad JobPosting JSON-LD",
        },
        "reconstructed": True,
        "limit": args.limit or None,
        "skipText": args.skip_text,
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
