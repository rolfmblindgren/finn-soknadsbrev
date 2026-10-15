#!/usr/bin/env python3
"""Finish observation collection: reuse partial + host files, fetch missing texts."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".agent-serve" / "scan-state"
LOG = STATE / "scan.log"
HOST_OBS_DIR = (
    STATE
    / "finn-soknadsbrev"
    / "files"
    / "deployment"
    / "scan"
    / "observations"
)
PARTIAL = ROOT / "data" / "observations.jsonl.partial"
OUT = ROOT / "data" / "observations.jsonl"
MANIFEST = ROOT / "data" / "observations.manifest.json"
INDUSTRY_CACHE = ROOT / "data" / "industry-cache.json"
SEARCH_API = (
    "https://www.finn.no/job/job-search-page/api/search/SEARCH_ID_JOB_FULLTIME"
)
UA = "FinnSoknadsbrevBot/0.1 (+complete-observations)"
WORKERS = 8
print_lock = threading.Lock()


def _open(url: str, accept: str, timeout: int = 60, retries: int = 4):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": accept}
            )
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


def get_json(url: str) -> dict:
    with _open(url, "application/json") as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_html(url: str) -> str:
    with _open(url, "text/html") as resp:
        return resp.read().decode("utf-8", "replace")

def load_labels_from_log() -> dict[str, dict]:
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


def load_existing() -> dict[str, dict]:
    existing: dict[str, dict] = {}
    if PARTIAL.exists():
        for line in PARTIAL.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            existing[str(row["id"])] = row
    if HOST_OBS_DIR.exists():
        for path in HOST_OBS_DIR.glob("*.json"):
            row = json.loads(path.read_text(encoding="utf-8"))
            ad_id = str(row["id"])
            prev = existing.get(ad_id)
            if prev and prev.get("classificationText") and not row.get(
                "classificationText"
            ):
                continue
            existing[ad_id] = {
                "id": ad_id,
                "url": row.get("url") or f"https://www.finn.no/job/ad/{ad_id}",
                "title": row.get("title"),
                "company": row.get("company"),
                "industry": row.get("industry"),
                "industryValue": row.get("industryValue"),
                "originalClassification": row.get("originalClassification"),
                "matched": row.get("matched"),
                "classificationText": row.get("classificationText") or "",
                "observedAt": row.get("observedAt"),
                "rebuiltAt": row.get("rebuiltAt"),
                "recordVersion": 1,
                "error": row.get("error"),
            }
    return existing


def list_industries() -> list[dict]:
    data = get_json(f"{SEARCH_API}?page=1")
    filt = next(f for f in data["filters"] if f.get("name") == "industry")
    industries = [
        {
            "name": str(i.get("display_name") or i.get("value")),
            "value": str(i.get("value")),
        }
        for i in filt.get("filter_items") or []
        if i.get("value") is not None
    ]
    industries.sort(key=lambda x: x["value"])
    return industries


def fill_missing_industries(rows: dict[str, dict]) -> None:
    cache: dict[str, dict] = {}
    if INDUSTRY_CACHE.exists():
        cache = json.loads(INDUSTRY_CACHE.read_text(encoding="utf-8"))
        for ad_id, info in cache.items():
            if ad_id in rows and not rows[ad_id].get("industry"):
                rows[ad_id]["industry"] = info.get("industry")
                rows[ad_id]["industryValue"] = info.get("industryValue")

    missing = {i for i, r in rows.items() if not r.get("industry")}
    if not missing:
        print("industry: none missing", flush=True)
        return
    print(f"industry: filling {len(missing)}", flush=True)
    try:
        industries = list_industries()
    except Exception as exc:  # noqa: BLE001
        print(f"industry: list failed ({exc}); continuing without", flush=True)
        return
    for ind in industries:
        if not missing:
            break
        page = 1
        last = 1
        while page <= last and missing:
            try:
                data = get_json(
                    f"{SEARCH_API}?page={page}&industry={ind['value']}"
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  {ind['name']} page={page} error={exc}; skip filter",
                    flush=True,
                )
                break
            last = int(
                (data.get("metadata") or {}).get("paging", {}).get("last") or page
            )
            for doc in data.get("docs") or []:
                ad_id = str(doc.get("id"))
                if ad_id in missing:
                    rows[ad_id]["industry"] = ind["name"]
                    rows[ad_id]["industryValue"] = ind["value"]
                    cache[ad_id] = {
                        "industry": ind["name"],
                        "industryValue": ind["value"],
                    }
                    missing.remove(ad_id)
            page += 1
        INDUSTRY_CACHE.write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  {ind['name']}: remaining_missing={len(missing)}", flush=True)
    print(f"industry: done remaining_missing={len(missing)}", flush=True)


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


def fetch_description(ad_id: str) -> tuple[str, str | None, str | None, str | None]:
    try:
        page = get_html(f"https://www.finn.no/job/ad/{ad_id}")
    except Exception as exc:  # noqa: BLE001
        return "", None, None, f"fetch failed: {exc}"
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
                text = html_to_text(item.get("description") or "")
                err = None if text else "empty description"
                return text, title, company, err
    return "", None, None, "no JobPosting JSON-LD"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    labels = load_labels_from_log()
    rows = load_existing()
    print(
        f"labels_in_log={len(labels)} existing_rows={len(rows)} "
        f"with_text={sum(1 for r in rows.values() if r.get('classificationText'))}",
        flush=True,
    )

    for ad_id, base in labels.items():
        if ad_id not in rows:
            rows[ad_id] = {
                "id": ad_id,
                "url": base.get("url") or f"https://www.finn.no/job/ad/{ad_id}",
                "title": base.get("title"),
                "company": base.get("company"),
                "industry": None,
                "industryValue": None,
                "originalClassification": base.get("originalClassification"),
                "matched": base.get("matched"),
                "classificationText": "",
                "observedAt": None,
                "rebuiltAt": None,
                "recordVersion": 1,
                "error": base.get("error"),
            }
        else:
            if base.get("originalClassification") and not rows[ad_id].get(
                "originalClassification"
            ):
                rows[ad_id]["originalClassification"] = base["originalClassification"]
            if base.get("matched") and rows[ad_id].get("matched") is None:
                rows[ad_id]["matched"] = base.get("matched")

    need_text = [
        ad_id
        for ad_id, row in rows.items()
        if not row.get("classificationText")
        and row.get("originalClassification") != "error"
    ]
    print(f"need_text={len(need_text)} workers={WORKERS}", flush=True)

    done = 0
    errors = 0

    def work(ad_id: str):
        return ad_id, fetch_description(ad_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(work, ad_id) for ad_id in need_text]
        for fut in concurrent.futures.as_completed(futures):
            ad_id, (text, title, company, err) = fut.result()
            row = rows[ad_id]
            row["classificationText"] = text
            if title:
                row["title"] = row.get("title") or title
            if company:
                row["company"] = row.get("company") or company
            row["rebuiltAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if err:
                row["error"] = err
                errors += 1
            done += 1
            if done % 100 == 0 or done == len(need_text):
                with print_lock:
                    print(
                        f"text progress {done}/{len(need_text)} fetch_errors={errors}",
                        flush=True,
                    )
            if done % 250 == 0:
                _write_jsonl(PARTIAL, rows)

    _write_jsonl(PARTIAL, rows)
    fill_missing_industries(rows)
    _write_jsonl(OUT, rows)
    if PARTIAL.exists():
        PARTIAL.unlink()

    counts = Counter(r.get("originalClassification") for r in rows.values())
    missing_text = sum(1 for r in rows.values() if not r.get("classificationText"))
    missing_industry = sum(1 for r in rows.values() if not r.get("industry"))
    manifest = {
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path": "data/observations.jsonl",
        "nRecords": len(rows),
        "countsByOriginalClassification": dict(counts),
        "missingClassificationText": missing_text,
        "missingIndustry": missing_industry,
        "sha256": sha256_file(OUT),
        "reusedPartial": True,
        "reusedHostObservations": HOST_OBS_DIR.exists(),
        "scanStatus": "complete",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


def _write_jsonl(path: Path, rows: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as out:
        for ad_id in sorted(rows):
            out.write(json.dumps(rows[ad_id], ensure_ascii=False) + "\n")
    tmp.replace(path)


if __name__ == "__main__":
    main()
