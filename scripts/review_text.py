#!/usr/bin/env python3
"""Fetch and cache public Official_Review text without changing rating snapshots."""

import argparse
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
TEXT_FIELDS = {
    "summary": "论文概述", "strengths": "优点", "weaknesses": "不足", "questions": "问题与建议",
    "limitations": "局限性", "review": "具体评价", "main_review": "具体评价",
    "comments": "补充评价", "justification": "评分理由", "soundness_justification": "可靠性说明",
    "summary_of_the_review": "评价总结", "summary_of_the_paper": "论文概述",
}
_guard = threading.Lock()
_blocked_until = 0


class BrowserVerificationRequired(Exception):
    """OpenReview can return its verification HTML with HTTP 200."""


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


def unwrap(value):
    return value.get("value") if isinstance(value, dict) else value


def normalize(notes, year, paper_id):
    """Keep only public official reviews for this forum and venue, keyed by alias."""
    reviews = []
    seen = set()
    for note in notes:
        invitations = note.get("invitations", [])
        if note.get("forum") != paper_id or note.get("ddate") or "everyone" not in note.get("readers", []):
            continue
        if not any(i.startswith(f"ICLR.cc/{year}/Conference/") and i.endswith("/-/Official_Review") for i in invitations):
            continue
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


def retrieve(year, paper_id, root=ROOT, *, refresh=False, input_path=None):
    """One public forum request at a time; do not retry browser challenges in a loop."""
    global _blocked_until
    if year not in (2026, 2027) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", paper_id):
        raise ValueError("Invalid year or forum ID")
    cache = root / f"iclr{year}/review_text/{paper_id}.json"
    raw_dir = root / f"iclr{year}/raw/review_text"
    with _guard:
        if not refresh and input_path is None and cache.exists() and time.time() - cache.stat().st_mtime < 21600:
            return json.loads(cache.read_text()), 200
        if input_path is None and time.time() < _blocked_until:
            return {"status": "blocked", "paper_id": paper_id, "reviews": [],
                    "message": "OpenReview 暂时要求浏览器验证或限制访问，尚未取得评价正文。请在 OpenReview 查看。"}, 503
        pages, notes, offset = [], [], 0
        try:
            if input_path is not None:
                payload = json.loads(input_path.read_text())
                notes = payload["notes"] if isinstance(payload, dict) else payload
                pages = [payload]
            else:
                opener = build_opener(ProxyHandler({}))
                while True:
                    url = "https://api2.openreview.net/notes?" + urlencode({"forum": paper_id, "limit": 1000, "offset": offset})
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
        except (HTTPError, URLError, TimeoutError, BrowserVerificationRequired) as error:
            verification = isinstance(error, BrowserVerificationRequired)
            code = error.code if isinstance(error, HTTPError) else 200 if verification else None
            blocked = verification or code in (403, 429)
            if blocked:
                _blocked_until = time.time() + (60 if code == 429 else 900)
            failure = {"source": "openreview", "year": year, "paper_id": paper_id,
                       "retrieved_at": timestamp(), "http_status": code, "error": type(error).__name__}
            save(raw_dir / "last_error.json", failure)
            return {"status": "blocked" if blocked else "unavailable", "paper_id": paper_id,
                    "reviews": [], "message": "OpenReview 要求浏览器验证，当前未能取得评价正文。可打开 OpenReview 完成验证或登录查看。" if verification or code == 403 else "暂时无法连接 OpenReview 获取评价正文，请稍后重试。"}, 503
        reviews = normalize(notes, year, paper_id)
        result = {"status": "available" if any(r["sections"] for r in reviews) else "empty",
                  "paper_id": paper_id, "year": year, "retrieved_at": timestamp(),
                  "source": "OpenReview 官方公开评审", "source_url": f"https://openreview.net/forum?id={paper_id}",
                  "reviews": reviews}
        save(raw_dir / f"{paper_id}.json", {"retrieved_at": result["retrieved_at"], "pages": pages})
        save(cache, result)
        return result, 200


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
