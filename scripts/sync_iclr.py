#!/usr/bin/env python3
"""Fetch public ICLR submissions and export inspectable paper/review tables."""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

REPO = "papercopilot/paperlists"
DOCS = "https://docs.openreview.net/how-to-guides/data-retrieval-and-modification/how-to-get-all-notes-for-submissions-reviews-rebuttals-etc"
ROOT = Path(__file__).resolve().parents[1]
REVIEW_FIELDS = ["rating", "confidence", "soundness", "presentation", "contribution", "informativeness"]


def now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temp.replace(path)


class Fetcher:
    def __init__(self, no_env_proxy=False, retries=3):
        self.opener = build_opener(ProxyHandler({})) if no_env_proxy else build_opener()
        self.retries = retries

    def get(self, url):
        for attempt in range(self.retries):
            try:
                request = Request(url, headers={"User-Agent": "PaperReading-public-metadata/1.0"})
                with self.opener.open(request, timeout=60) as response:
                    return response.read()
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt + 1 == self.retries:
                    raise
                retry_after = exc.headers.get("Retry-After", "")
                delay = int(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1)
            except (URLError, TimeoutError):
                if attempt + 1 == self.retries:
                    raise
                delay = 2 ** (attempt + 1)
            print(f"Request failed; retrying in {min(delay, 60)}s", file=sys.stderr, flush=True)
            time.sleep(min(delay, 60))

    def json(self, url):
        return json.loads(self.get(url))


def mirror_records(fetcher, raw, refresh, year=2027):
    path = raw / "papercopilot.json"
    provenance_path = raw / "papercopilot_source.json"
    if not path.exists() or refresh or not provenance_path.exists():
        commit_url = f"https://api.github.com/repos/{REPO}/commits?" + urlencode(
            {"path": f"iclr/iclr{year}.json", "per_page": 1}
        )
        commit = fetcher.json(commit_url)[0]
        sha = commit["sha"]
        pointer = fetcher.get(
            f"https://raw.githubusercontent.com/{REPO}/{sha}/iclr/iclr{year}.json"
        ).decode()
        expected_hash = re.search(r"oid sha256:([a-f0-9]{64})", pointer).group(1)
        expected_size = int(re.search(r"size (\d+)", pointer).group(1))
        url = f"https://media.githubusercontent.com/media/{REPO}/{sha}/iclr/iclr{year}.json"
        cached = path.read_bytes() if path.exists() else b""
        if hashlib.sha256(cached).hexdigest() != expected_hash:
            print("Downloading pinned Paper Copilot snapshot", flush=True)
            cached = fetcher.get(url)
            if len(cached) != expected_size or hashlib.sha256(cached).hexdigest() != expected_hash:
                raise ValueError("Mirror download does not match its Git LFS pointer")
            temporary = path.with_suffix(".json.part")
            temporary.write_bytes(cached)
            temporary.replace(path)
        save_json(provenance_path, {
            "source": "papercopilot", "conference": f"ICLR {year}", "repository": f"https://github.com/{REPO}",
            "commit": sha, "source_commit_time": commit["commit"]["committer"]["date"],
            "url": url, "sha256": expected_hash, "bytes": expected_size,
            "retrieved_at": now(), "upstream_collection_time": None,
            "official_coverage_verified": False,
        })
    provenance = json.loads(provenance_path.read_text())
    if f"iclr{year}.json" not in provenance["url"]:
        raise ValueError("Cached mirror belongs to a different conference year")
    contents = path.read_bytes()
    if hashlib.sha256(contents).hexdigest() != provenance["sha256"]:
        raise ValueError("Cached mirror checksum mismatch")
    return json.loads(contents), provenance


def official_records(fetcher, raw, refresh, page_size, year=2027):
    venue = f"ICLR.cc/{year}/Conference"
    directory = raw / "openreview"
    directory.mkdir(exist_ok=True)
    records, offset, expected = [], 0, None
    while True:
        path = directory / f"{offset:08d}.json"
        if path.exists() and not refresh:
            page = json.loads(path.read_text())
        else:
            params = {"invitation": f"{venue}/-/Submission", "details": "directReplies",
                      "limit": page_size, "offset": offset, "sort": "number:asc"}
            url = "https://api2.openreview.net/notes?" + urlencode(params)
            page = fetcher.json(url)
            page["_retrieved_at"] = now()
            save_json(path, page)
            time.sleep(1)
        notes = page["notes"]
        expected = page["count"] if expected is None else expected
        if page["count"] != expected:
            raise ValueError("Official count changed during pagination; rerun with --refresh")
        records.extend(notes)
        offset += len(notes)
        print(f"OpenReview: {offset}/{expected}", flush=True)
        if offset >= expected:
            break
        if not notes:
            raise ValueError("Official pagination ended before the reported count")
    if len({row["id"] for row in records}) != expected:
        raise ValueError("Official pagination contains duplicates or missing records")
    times = [json.loads(p.read_text())["_retrieved_at"] for p in directory.glob("*.json")]
    return records, {"source": "openreview", "url": "https://api2.openreview.net/notes",
                     "conference": f"ICLR {year}", "invitation": f"{venue}/-/Submission", "api_reported_count": expected,
                     "retrieved_at": max(times), "oldest_cached_page_at": min(times),
                     "official_coverage_verified": True, "documentation": DOCS}


def value(content, key, default=None):
    item = content.get(key, default)
    return item.get("value", default) if isinstance(item, dict) else item


def numeric(raw):
    if raw is None or str(raw).strip().lower() in ("", "null", "none", "nan", "n/a"):
        return None
    match = re.match(r"^\s*(-?\d+(?:\.\d+)?)(?:\s*:.*)?\s*$", str(raw))
    if not match:
        raise ValueError(f"Unrecognized review score: {raw!r}")
    number = float(match.group(1))
    return int(number) if number.is_integer() else number


def base_paper(forum, title, abstract, status, track, source, retrieved_at):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", forum):
        raise ValueError(f"Invalid OpenReview forum ID: {forum!r}")
    return {"id": forum, "title": title, "abstract": abstract,
            "paper_url": f"https://openreview.net/forum?id={forum}",
            "pdf_url": f"https://openreview.net/pdf?id={forum}",
            "status": status, "track": track, "source": source,
            "retrieved_at": retrieved_at}


def normalize_mirror(row, provenance):
    forum = row.get("openreview_forum") or row["id"]
    paper = base_paper(forum, row["title"], row.get("abstract") or None,
                       row.get("status"), row.get("track", "main"),
                       "papercopilot", provenance["retrieved_at"])
    fields = ["reviewers", *REVIEW_FIELDS]
    parts = {k: str(row.get(k) or "").split(";") for k in fields}
    count = len(parts["reviewers"]) if row.get("reviewers") else 0
    for field in fields[1:]:
        if not row.get(field):
            parts[field] = [""] * count
    if count and any(len(p) != count for p in parts.values()):
        raise ValueError(f"Reviewer fields are misaligned for {forum}")
    reviews = []
    for i in range(count):
        review = {"paper_id": forum, "review_index": i + 1, "review_id": None,
                  "reviewer": parts["reviewers"][i] or None, "review_url": None}
        for field in fields[1:]:
            review[field] = numeric(parts[field][i])
            review[field + "_raw"] = parts[field][i] or None
        reviews.append(review)
    return paper, reviews


def normalize_official(row, provenance):
    content = row["content"]
    paper = base_paper(row["id"], value(content, "title"), value(content, "abstract"),
                       value(content, "venue"), "main", "openreview", provenance["retrieved_at"])
    reviews = []
    for reply in row.get("details", {}).get("directReplies", []):
        invitations = reply.get("invitations", [])
        if not any(i.endswith("/-/Official_Review") for i in invitations):
            continue
        review = {"paper_id": row["id"], "review_index": len(reviews) + 1,
                  "review_id": reply["id"], "reviewer": ";".join(reply.get("signatures", [])),
                  "review_url": f"https://openreview.net/forum?id={row['id']}&noteId={reply['id']}"}
        for field in REVIEW_FIELDS:
            raw = value(reply["content"], field)
            review[field], review[field + "_raw"] = numeric(raw), raw
        reviews.append(review)
    return paper, reviews


def export(records, provenance, output, track, year=2027):
    if provenance.get("conference", f"ICLR {year}") != f"ICLR {year}":
        raise ValueError("Source conference does not match the requested year")
    scale = {"min": 1, "max": 4, "values": [1, 2, 3, 4]} if year == 2027 else {"min": 0, "max": 10, "values": [0, 2, 4, 6, 8, 10]}
    papers, reviews = [], []
    normalize = normalize_mirror if provenance["source"] == "papercopilot" else normalize_official
    for row in records:
        if track == "main" and row.get("track", "main") != "main":
            continue
        paper, children = normalize(row, provenance)
        ratings = [r["rating"] for r in children if r["rating"] is not None]
        if paper["track"] == "main" and any(rating not in scale["values"] for rating in ratings):
            raise ValueError(f"Unexpected ICLR {year} rating for {paper['id']}: {ratings}")
        paper.update({"conference": f"ICLR {year}", "review_count": len(children), "rating_count": len(ratings),
                      "ratings": [r["rating"] for r in children],
                      "rating_mean": sum(ratings) / len(ratings) if ratings else None,
                      "rating_missing": not ratings, "reviews": children})
        papers.append(paper)
        reviews.extend(children)
    papers.sort(key=lambda p: p["id"])
    if not papers or len({p["id"] for p in papers}) != len(papers):
        raise ValueError("Empty export or duplicate paper IDs")
    if any(not p["title"] for p in papers):
        raise ValueError("Missing paper title")
    with (output / "papers.jsonl").open("w", encoding="utf-8") as handle:
        for paper in papers:
            handle.write(json.dumps(paper, ensure_ascii=False) + "\n")
    with (output / "papers.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [k for k in papers[0] if k != "reviews"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for paper in papers:
            writer.writerow({k: json.dumps(paper[k]) if k == "ratings" else paper[k] for k in fields})
    review_fields = ["paper_id", "review_index", "review_id", "reviewer", "review_url"]
    for field in REVIEW_FIELDS:
        review_fields += [field, field + "_raw"]
    with (output / "reviews.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review_fields)
        writer.writeheader()
        writer.writerows(reviews)
    manifest = {"conference": f"ICLR {year}", "year": year, "rating_scale": scale, "scope": track, "generated_at": now(),
                "provenance": provenance, "source_record_count": len(records),
                "paper_count": len(papers), "review_count": len(reviews),
                "rating_count": sum(r["rating"] is not None for r in reviews),
                "papers_without_ratings": sum(p["rating_missing"] for p in papers),
                "papers_without_abstract": sum(not p["abstract"] for p in papers),
                "zero_ratings_preserved": sum(r["rating"] == 0 for r in reviews),
                "statuses": dict(Counter(p["status"] for p in papers)),
                "tracks": dict(Counter(p["track"] for p in papers)),
                "limitations": [
                    "Coverage of a mirror is not proof of the official public submission total.",
                    "PDF URLs are constructed from forum IDs; PDF accessibility was not batch-verified.",
                    "Mirror reviewer aliases have no review note IDs or review modification times.",
                    "Scores are snapshot values, not a reconstructed review history.",
                    ("ICLR 2027 is in its review/discussion period in this snapshot; scores can change and Active is not an acceptance decision."
                     if year == 2027 else "ICLR 2026 reset reviews to the pre-rebuttal state after its security incident."),
                ]}
    for name in ["papers.jsonl", "papers.csv", "reviews.csv"]:
        manifest.setdefault("output_sha256", {})[name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
    save_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, choices=[2026, 2027], default=2027)
    parser.add_argument("--source", choices=["openreview", "papercopilot"], default="openreview")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--track", choices=["main", "all"], default="main")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch source instead of reusing cached pages")
    parser.add_argument("--no-env-proxy", action="store_true")
    parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()
    args.output = args.output or ROOT / f"iclr{args.year}"
    if args.source == "openreview" and args.track != "main":
        parser.error("The official crawler covers the main conference; use papercopilot for workshop records")
    if not 1 <= args.page_size <= 1000:
        parser.error("--page-size must be between 1 and 1000")
    args.output.mkdir(parents=True, exist_ok=True)
    raw = args.output / "raw"
    raw.mkdir(exist_ok=True)
    fetcher = Fetcher(args.no_env_proxy)
    try:
        if args.source == "openreview":
            records, provenance = official_records(fetcher, raw, args.refresh, args.page_size, args.year)
        else:
            records, provenance = mirror_records(fetcher, raw, args.refresh, args.year)
        manifest = export(records, provenance, args.output, args.track, args.year)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        error = {"source": args.source, "failed_at": now(), "error": message}
        if isinstance(exc, HTTPError):
            error.update(http_status=exc.code, response=exc.read().decode(errors="replace")[:2000])
        save_json(raw / "last_error.json", error)
        print(message, file=sys.stderr)
        return 1
    print(json.dumps({k: manifest[k] for k in ["paper_count", "review_count", "papers_without_ratings"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
