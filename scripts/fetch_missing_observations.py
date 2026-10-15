#!/usr/bin/env python3
"""Fetch and classify FINN ads missing from the frozen v1 dataset.

Keeps observations.v1.jsonl immutable. Writes new rows to:
  data/incremental/observations.v2add.jsonl
and merges into:
  data/observations.v2.jsonl  (= v1 + additions, unique by id)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path

UA = "FinnSoknadsbrevBot/0.1 (+research; cover-letter)"
ROOT = Path(__file__).resolve().parents[1]

REJECT_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"tar\s+ikke\s+imot\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev)",
        r"ikke\s+sende?\s+inn\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev)",
        r"ikke\s+send(?:e)?\s+(?:inn\s+)?(?:et\s+)?(?:søknadsbrev|motivasjonsbrev)",
        r"ønsker\s+ikke\s+(?:å\s+motta\s+)?(?:et\s+)?(?:søknadsbrev|motivasjonsbrev)",
        r"vil\s+ikke\s+ha\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev)",
        r"ber\s+ikke\s+om\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev)",
        r"uten\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev)",
        r"ingen\s+(?:søknadsbrev|motivasjonsbrev)",
        r"(?:søknadsbrev|motivasjonsbrev)\s+er\s+ikke\s+(?:nødvendig|ønskelig|påkrevd|ønsket)",
        r"ikke\s+(?:nødvendig|ønskelig|påkrevd)\s+med\s+(?:søknadsbrev|motivasjonsbrev)",
        r"trenger\s+ikke\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev)",
        r"trenger\s+ikke\s+skrive\s+(?:et\s+)?(?:søknadsbrev|motivasjonsbrev|søknad)",
        r"skip\s+(?:the\s+)?cover\s+letter",
        r"do\s+not\s+send\s+(?:a\s+)?cover\s+letter",
        r"don'?t\s+send\s+(?:a\s+)?cover\s+letter",
        r"don'?t\s+want\s+(?:a\s+)?cover\s+letter",
        r"no\s+cover\s+letter(?:s)?(?:\s+(?:please|needed|required))?",
        r"without\s+(?:a\s+)?cover\s+letter",
        r"cover\s+letter(?:s)?\s+(?:is|are)\s+not\s+(?:required|needed|wanted)",
    ]
]
ASK_PATTERN = re.compile(
    r"\b(søknadsbrev|motivasjonsbrev|cover\s*letters?|application\s+letters?)\b",
    re.I,
)


def classify(text: str) -> tuple[str, str | None]:
    normalized = text.replace("\u00a0", " ")
    for pattern in REJECT_PATTERNS:
        m = pattern.search(normalized)
        if m:
            return "rejects", m.group(0)
    m = ASK_PATTERN.search(normalized)
    if m:
        return "asks", m.group(0)
    return "silent", None


def html_to_text(html: str) -> str:
    s = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    for a, b in [
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&#39;", "'"),
        ("&quot;", '"'),
    ]:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


class _DivExtractor(HTMLParser):
    """Extract inner HTML of the first element matching attr predicate."""

    def __init__(self, pred):
        super().__init__(convert_charrefs=False)
        self.pred = pred
        self.capturing = False
        self.depth = 0
        self.chunks: list[str] = []
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        attr_d = dict(attrs)
        if not self.capturing and self.pred(tag, attr_d):
            self.capturing = True
            self.depth = 1
            return
        if self.capturing:
            self.depth += 1
            attr_s = "".join(f' {k}="{v}"' for k, v in attrs)
            self.chunks.append(f"<{tag}{attr_s}>")

    def handle_endtag(self, tag):
        if self.done or not self.capturing:
            return
        self.depth -= 1
        if self.depth == 0:
            self.capturing = False
            self.done = True
            return
        self.chunks.append(f"</{tag}>")

    def handle_data(self, data):
        if self.capturing:
            self.chunks.append(data)

    def handle_entityref(self, name):
        if self.capturing:
            self.chunks.append(f"&{name};")

    def handle_charref(self, name):
        if self.capturing:
            self.chunks.append(f"&#{name};")


def extract_description_html(page: str) -> tuple[str, str]:
    """Return (html, source) where source is jsonld|ad-description|import-decoration|empty."""
    for m in re.finditer(
        r'<script type="application/ld\+json">([\s\S]*?)</script>', page, re.I
    ):
        try:
            parsed = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "script:ld+json" in parsed:
            parsed = parsed["script:ld+json"]
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item.get("description") or "", "jsonld"

    def pred_ad(_tag, attrs):
        return attrs.get("data-testid") == "ad-description" or attrs.get("id") == "ad-description"

    p = _DivExtractor(pred_ad)
    p.feed(page)
    html = "".join(p.chunks)
    if html_to_text(html):
        return html, "ad-description"

    def pred_import(tag, attrs):
        return tag == "div" and "import-decoration" in (attrs.get("class") or "")

    p2 = _DivExtractor(pred_import)
    p2.feed(page)
    html2 = "".join(p2.chunks)
    if html_to_text(html2):
        return html2, "import-decoration"
    return "", "empty"


def extract_meta(page: str, ad_id: str) -> tuple[str, str | None]:
    title = f"Annonse {ad_id}"
    m = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", page, re.I)
    if m:
        t = html_to_text(m.group(1))
        if t:
            title = t
    else:
        m = re.search(r"<title>([^|<]+)", page, re.I)
        if m:
            title = m.group(1).strip()
    company = None
    for pat in [
        r'data-testid="company-name"[^>]*>([\s\S]*?)</',
        r'itemprop="hiringOrganization"[^>]*>[\s\S]*?itemprop="name"[^>]*>([\s\S]*?)</',
    ]:
        m = re.search(pat, page, re.I)
        if m:
            company = html_to_text(m.group(1)) or None
            if company:
                break
    return title, company


def fetch_ad(ad_id: str) -> dict:
    url = f"https://www.finn.no/job/ad/{ad_id}"
    req = urllib.request.Request(
        url, headers={"Accept": "text/html", "User-Agent": UA}
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            page = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return {
            "id": ad_id,
            "url": url,
            "title": f"Annonse {ad_id}",
            "company": None,
            "industry": None,
            "industryValue": None,
            "originalClassification": "error",
            "matched": None,
            "classificationText": "",
            "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "recordVersion": 1,
            "error": f"HTTP {e.code}",
            "provenance": {"source": "coverage_gap_fill", "fetch": "ad_page"},
        }
    except Exception as e:
        return {
            "id": ad_id,
            "url": url,
            "title": f"Annonse {ad_id}",
            "company": None,
            "industry": None,
            "industryValue": None,
            "originalClassification": "error",
            "matched": None,
            "classificationText": "",
            "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "recordVersion": 1,
            "error": str(e)[:200],
            "provenance": {"source": "coverage_gap_fill", "fetch": "ad_page"},
        }

    desc_html, source = extract_description_html(page)
    text = html_to_text(desc_html)
    title, company = extract_meta(page, ad_id)
    if not text:
        return {
            "id": ad_id,
            "url": url,
            "title": title,
            "company": company,
            "industry": None,
            "industryValue": None,
            "originalClassification": "error",
            "matched": None,
            "classificationText": "",
            "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "recordVersion": 1,
            "error": f"No description ({source})",
            "provenance": {"source": "coverage_gap_fill", "fetch": "ad_page", "textSource": source},
        }
    cat, matched = classify(text)
    return {
        "id": ad_id,
        "url": url,
        "title": title,
        "company": company,
        "industry": None,
        "industryValue": None,
        "originalClassification": cat,
        "matched": matched,
        "classificationText": text,
        "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "recordVersion": 1,
        "provenance": {
            "source": "coverage_gap_fill",
            "fetch": "ad_page",
            "textSource": source,
            "note": "industry null when discovered outside industry filters",
        },
    }


def load_ids(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--missing-ids", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--out",
        default=str(ROOT / "data/incremental/observations.v2add.jsonl"),
    )
    ap.add_argument(
        "--merge-v1",
        default=str(ROOT / "data/original/observations.v1.jsonl"),
    )
    ap.add_argument(
        "--merged-out",
        default=str(ROOT / "data/observations.v2.jsonl"),
    )
    args = ap.parse_args()

    ids = load_ids(Path(args.missing_ids))
    if args.limit:
        ids = ids[: args.limit]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    if out_path.exists():
        with out_path.open() as f:
            for line in f:
                if line.strip():
                    done.add(json.loads(line)["id"])
    todo = [i for i in ids if i not in done]
    print(
        f"missing list={len(ids)} already_fetched={len(done)} todo={len(todo)}",
        flush=True,
    )

    ok = err = 0
    with out_path.open("a") as out, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_ad, i): i for i in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            if rec["originalClassification"] == "error":
                err += 1
            else:
                ok += 1
            if n % 25 == 0 or n == len(todo):
                print(f"fetched {n}/{len(todo)} ok={ok} err={err}", flush=True)

    v1_ids: set[str] = set()
    merged_path = Path(args.merged_out)
    with merged_path.open("w") as mout, open(args.merge_v1) as vin:
        for line in vin:
            if not line.strip():
                continue
            mout.write(line if line.endswith("\n") else line + "\n")
            v1_ids.add(json.loads(line)["id"])
        added = 0
        with out_path.open() as ain:
            for line in ain:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec["id"] in v1_ids:
                    continue
                mout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                added += 1
    h = hashlib.sha256(merged_path.read_bytes()).hexdigest()
    print(f"merged {len(v1_ids)}+{added} -> {merged_path} sha256={h}", flush=True)


if __name__ == "__main__":
    main()
