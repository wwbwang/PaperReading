#!/usr/bin/env python3
"""Fetch and cache public Official_Review text without changing rating snapshots."""

import argparse
import json
import re
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.browser_reviews import BrowserReviewError, retrieve_pages

TEXT_FIELDS = {
    "summary": "论文概述", "strengths": "优点", "weaknesses": "不足", "questions": "问题与建议",
    "limitations": "局限性", "review": "具体评价", "main_review": "具体评价",
    "comments": "补充评价", "justification": "评分理由", "soundness_justification": "可靠性说明",
    "summary_of_the_review": "评价总结", "summary_of_the_paper": "论文概述",
    "paper_summary": "论文概述", "critical_strengths": "主要优点", "critical_weaknesses": "主要不足",
    "questions_for_authors": "作者需回应的问题", "flag_for_ethics_review": "伦理审查标记",
    "code_of_conduct": "行为准则声明",
}
_guard = threading.Lock()
_blocked_until = 0
_rate_limited_until = 0


class BrowserVerificationRequired(Exception):
    """OpenReview can return its verification HTML with HTTP 200."""


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # The website and background sync can finish the same paper concurrently.
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        temp = Path(handle.name)
        try:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            handle.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def unwrap(value):
    return value.get("value") if isinstance(value, dict) else value


def public_notes(notes, year, paper_id):
    """Strip private notes and private fields before writing any cache."""
    result = []
    for note in notes:
        if (note.get("forum") != paper_id or note.get("ddate")
                or "everyone" not in note.get("readers", [])
                or not any(i.startswith(f"ICLR.cc/{year}/Conference/") and i.endswith("/-/Official_Review")
                           for i in note.get("invitations", []))):
            continue
        clean = {k: note[k] for k in ("id", "forum", "readers", "invitations", "signatures", "mdate") if k in note}
        clean["content"] = {k: v for k, v in note.get("content", {}).items()
                            if not isinstance(v, dict) or "readers" not in v or "everyone" in v["readers"]}
        result.append(clean)
    return result


def normalize(notes, year, paper_id):
    """Keep only public official reviews for this forum and venue, keyed by alias."""
    reviews = []
    seen = set()
    for note in public_notes(notes, year, paper_id):
        note_id = note.get("id")
        if not note_id or note_id in seen:
            continue
        seen.add(note_id)
        aliases = []
        for signature in note.get("signatures", []):
            match = re.search(r"/(?:Anon)?Reviewer_([^/]+)$", signature)
            if match:
                aliases.append(match.group(1))
            elif "/Reviewers/" in signature:
                aliases.append(signature.rsplit("/", 1)[-1])
        content = note.get("content", {})
        sections = []
        for field, raw_value in content.items():
            if field in {"title", "rating", "confidence", "soundness", "presentation", "informativeness", "contribution"}:
                continue
            label = TEXT_FIELDS.get(field, field.replace("_", " ").capitalize())
            text = unwrap(raw_value)
            if isinstance(text, str) and text.strip():
                sections.append({"field": field, "label": label, "text": text})
        reviews.append({"id": note_id, "reviewer": aliases[0] if len(set(aliases)) == 1 else None,
                        "url": f"https://openreview.net/forum?id={paper_id}&noteId={note_id}",
                        "rating": unwrap(content.get("rating")), "modified_at": note.get("mdate"),
                        "sections": sections})
    return reviews


def review_result(year, paper_id, pages, *, transport, retrieved_at=None):
    reviews = normalize([note for page in pages for note in page["notes"]], year, paper_id)
    return {"status": "available" if any(r["sections"] for r in reviews) else "empty",
              "paper_id": paper_id, "year": year, "retrieved_at": retrieved_at or timestamp(),
              "source": "OpenReview 官方公开评审", "source_url": f"https://openreview.net/forum?id={paper_id}",
              "transport": transport, "reviews": reviews}


def store_reviews(year, paper_id, pages, root=ROOT, *, transport, retrieved_at=None):
    """Use the same public-only cache format for on-demand and batch retrieval."""
    pages = [{"notes": public_notes(page["notes"], year, paper_id)} for page in pages]
    result = review_result(year, paper_id, pages, transport=transport, retrieved_at=retrieved_at)
    save(root / f"iclr{year}/raw/review_text/{paper_id}.json", {
        "retrieved_at": result["retrieved_at"], "transport": transport, "pages": pages,
    })
    save(root / f"iclr{year}/review_text/{paper_id}.json", result)
    return result


def store_review_batch(year, papers, root=ROOT, *, retrieved_at):
    """Commit a whole public batch together, avoiding thousands of small files."""
    rows, results = [], []
    for paper in papers:
        notes = public_notes(paper["notes"], year, paper["id"])
        result = review_result(year, paper["id"], [{"notes": notes}], transport="browser", retrieved_at=retrieved_at)
        results.append(result)
        rows.append((paper["id"], datetime.fromisoformat(retrieved_at).timestamp(), json.dumps(result, ensure_ascii=False),
                     json.dumps({"retrieved_at": retrieved_at, "transport": "browser", "pages": [{"notes": notes}]}, ensure_ascii=False)))
    path = root / f"iclr{year}/review_text.sqlite3"
    with closing(sqlite3.connect(path, timeout=30)) as database, database:
        database.execute("CREATE TABLE IF NOT EXISTS reviews (paper_id TEXT PRIMARY KEY, cached_at REAL NOT NULL, result TEXT NOT NULL, raw TEXT NOT NULL)")
        database.executemany("INSERT OR REPLACE INTO reviews VALUES (?, ?, ?, ?)", rows)
    return results


def cached_review(year, paper_id, root=ROOT):
    path = root / f"iclr{year}/review_text/{paper_id}.json"
    cached = json.loads(path.read_text()) if path.exists() else None
    cached_at = datetime.fromisoformat(cached["retrieved_at"]).timestamp() if cached else 0
    database_path = root / f"iclr{year}/review_text.sqlite3"
    if database_path.exists():
        with closing(sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True, timeout=5)) as database:
            row = database.execute("SELECT cached_at, result FROM reviews WHERE paper_id = ?", (paper_id,)).fetchone()
        if row and row[0] > cached_at:
            cached_at, cached = row[0], json.loads(row[1])
    return cached, cached_at


def retrieve(year, paper_id, root=ROOT, *, refresh=False, input_path=None):
    """One public forum request at a time; do not retry browser challenges in a loop."""
    global _blocked_until, _rate_limited_until
    if year not in (2026, 2027) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", paper_id):
        raise ValueError("Invalid year or forum ID")
    raw_dir = root / f"iclr{year}/raw/review_text"
    # Local cached reviews must not queue behind unrelated network requests.
    cached, cached_at = cached_review(year, paper_id, root)
    if not refresh and input_path is None and cached and time.time() - cached_at < 21600:
        return cached, 200
    with _guard:
        cached, cached_at = cached_review(year, paper_id, root)
        if not refresh and input_path is None and cached and time.time() - cached_at < 21600:
            return cached, 200
        if input_path is None and time.time() < _rate_limited_until:
            if cached and cached.get("status") == "available":
                return {**cached, "stale": True, "message": "OpenReview 正在限流，显示上次成功获取的公开评价。"}, 200
            return {"status": "blocked", "paper_id": paper_id, "reviews": [],
                    "browser_status": "rate_limited", "message": "OpenReview 正在限流，请一分钟后重试。"}, 503
        pages, notes, offset = [], [], 0
        transport = "http"
        try:
            if input_path is not None:
                payload = json.loads(input_path.read_text())
                notes = payload["notes"] if isinstance(payload, dict) else payload
                pages = [payload]
            else:
                if time.time() < _blocked_until:
                    raise BrowserVerificationRequired()
                opener = build_opener(ProxyHandler({}))
                while True:
                    url = "https://api2.openreview.net/notes?" + urlencode({"forum": paper_id, "limit": 1000, "offset": offset, "count": "true"})
                    request = Request(url, headers={"User-Agent": "PaperReading-public-reviews/1.0", "Accept": "application/json"})
                    with opener.open(request, timeout=15) as response:
                        payload = response.read()
                        if "text/html" in response.headers.get("Content-Type", "") and (b"cf-turnstile" in payload or b"Verifying your browser" in payload):
                            raise BrowserVerificationRequired()
                        page = json.loads(payload)
                    pages.append(page)
                    notes.extend(page["notes"])
                    offset += len(page["notes"])
                    if offset >= page["count"]:
                        break
                    if not page["notes"]:
                        raise ValueError("Review pagination ended early")
        except (HTTPError, URLError, TimeoutError, BrowserVerificationRequired, ValueError, KeyError) as error:
            if input_path is not None:
                raise
            verification = isinstance(error, BrowserVerificationRequired)
            code = error.code if isinstance(error, HTTPError) else 200 if verification else None
            blocked = verification or code in (403, 429)
            if blocked and time.time() >= _blocked_until:
                _blocked_until = time.time() + (60 if code == 429 else 900)
            failure = {"source": "openreview", "year": year, "paper_id": paper_id,
                       "retrieved_at": timestamp(), "http_status": code, "error": type(error).__name__}
            save(raw_dir / "last_error.json", failure)
            try:
                if code == 429:
                    raise BrowserReviewError("rate_limited", "OpenReview 正在限流，请一分钟后重试。")
                pages = retrieve_pages(year, paper_id)
                notes = [note for page in pages for note in page["notes"]]
                transport = "browser"
            except BrowserReviewError as browser_error:
                save(raw_dir / "last_error.json", {**failure, "browser_status": browser_error.status})
                if browser_error.status == "rate_limited":
                    _rate_limited_until = time.time() + 60
                message = str(browser_error)
                if cached and cached.get("status") == "available":
                    return {**cached, "stale": True, "message": "本次更新失败，显示上次成功获取的公开评价。"}, 200
                return {"status": "blocked" if blocked else "unavailable", "paper_id": paper_id,
                        "reviews": [], "browser_status": browser_error.status, "message": message}, 503
        pages = [{"notes": page["notes"] if isinstance(page, dict) else page} for page in pages]
        return store_reviews(year, paper_id, pages, root, transport=transport), 200


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, choices=[2026, 2027], default=2027)
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--input", type=Path, help="Import an exported public OpenReview notes JSON")
    args = parser.parse_args()
    result, status = retrieve(args.year, args.paper_id, refresh=args.refresh, input_path=args.input)
    print(json.dumps({k: v for k, v in result.items() if k != "reviews"}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if status == 200 else 1)


if __name__ == "__main__":
    main()
