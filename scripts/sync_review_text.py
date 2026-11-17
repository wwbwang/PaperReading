#!/usr/bin/env python3
"""Resume public review backfills using the existing logged-in browser."""

import argparse
import fcntl
import hashlib
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.browser_reviews import BrowserReviewError, retrieve_submission_page
from scripts.review_text import save, store_review_batch, timestamp


def sync_year(year, root=ROOT, *, page_size=100, delay=1, max_pages=None, refresh=False):
    targets = {json.loads(line)["id"] for line in (root / f"iclr{year}/papers.jsonl").open()}
    fingerprint = hashlib.sha256("\n".join(sorted(targets)).encode()).hexdigest()
    directory = root / f"iclr{year}/raw/review_sync"
    state_path = root / f".runtime/review-sync/{year}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() and not refresh else {
        "year": year, "status": "running", "offset": 0, "api_count": None,
        "snapshot": fingerprint, "page_size": page_size, "total_papers": len(targets),
        "covered_papers": 0, "papers_with_text": 0, "papers_without_text": 0,
        "reviews": 0, "outside_snapshot": 0, "started_at": timestamp(),
        "run_id": uuid.uuid4().hex,
        "storage": "sqlite-v1",
    }
    if state["snapshot"] != fingerprint:
        raise ValueError("Snapshot changed; use --refresh to start a new pass")
    if state["status"] == "complete":
        print(json.dumps(state, ensure_ascii=False), flush=True)
        return state
    seen, covered = set(), set()
    # Reconstruct committed IDs from page journals; uncommitted pages are replayed.
    offset = 0
    while offset < state["offset"]:
        page = json.loads((directory / f"{offset:08d}.json").read_text())
        if page.get("run_id") != state["run_id"] or page["received"] <= 0:
            raise ValueError("Invalid saved pagination; restart with --refresh")
        ids = {paper["id"] for paper in page["papers"]}
        if len(ids) != len(page["papers"]) or seen & ids:
            raise ValueError("Duplicate submission in saved pagination; restart with --refresh")
        seen |= ids
        covered |= ids & targets
        if state.get("storage") != "sqlite-v1":
            store_review_batch(year, [paper for paper in page["papers"] if paper["id"] in targets],
                               root, retrieved_at=page["retrieved_at"])
        offset += page["received"]
    if offset != state["offset"]:
        raise ValueError("Saved pagination does not match committed offset")
    state["storage"] = "sqlite-v1"
    state["page_size"] = page_size
    state.update(status="running", error=None, message=None, interrupted=False, updated_at=timestamp())
    save(state_path, state)
    pages = 0
    try:
        while state["api_count"] is None or state["offset"] < state["api_count"]:
            if max_pages is not None and pages >= max_pages:
                state["status"] = "paused"
                break
            page_path = directory / f'{state["offset"]:08d}.json'
            page = json.loads(page_path.read_text()) if page_path.exists() else None
            if page is None or page.get("run_id") != state["run_id"]:
                page = retrieve_submission_page(year, state["offset"], page_size)
                page["retrieved_at"] = timestamp()
                page["run_id"] = state["run_id"]
                save(page_path, page)
            if state["api_count"] is not None and page["count"] != state["api_count"]:
                raise ValueError("Official submission count changed during pagination; restart with --refresh")
            if page["received"] <= 0 or page["received"] > page_size or state["offset"] + page["received"] > page["count"]:
                raise ValueError("Official pagination ended early or returned an invalid count")
            ids = [paper["id"] for paper in page["papers"]]
            if len(set(ids)) != len(ids) or seen.intersection(ids):
                raise ValueError("Official pagination contains duplicate submissions; restart with --refresh")
            results = store_review_batch(year, [paper for paper in page["papers"] if paper["id"] in targets],
                                         root, retrieved_at=page["retrieved_at"])
            with_text = sum(result["status"] == "available" for result in results)
            reviews = sum(bool(review["sections"]) for result in results for review in result["reviews"])
            seen.update(ids)
            covered.update(targets.intersection(ids))
            count = len(targets.intersection(ids))
            state.update(offset=state["offset"] + page["received"], api_count=page["count"],
                         covered_papers=len(covered), papers_with_text=state["papers_with_text"] + with_text,
                         papers_without_text=state["papers_without_text"] + count - with_text,
                         reviews=state["reviews"] + reviews, outside_snapshot=len(seen - targets),
                         updated_at=timestamp())
            save(state_path, state)
            print(f'ICLR {year}: {state["offset"]}/{state["api_count"]} submissions; '
                  f'{state["papers_with_text"]} papers with text, {state["reviews"]} reviews', flush=True)
            pages += 1
            if state["offset"] < state["api_count"]:
                time.sleep(delay)
        else:
            missing = sorted(targets - covered)
            save(directory / "coverage.json", {"year": year, "verified_at": timestamp(),
                 "api_count": state["api_count"], "unique_public_submissions": len(seen),
                 "snapshot_papers": len(targets), "covered_papers": len(covered), "missing_ids": missing,
                 "outside_snapshot_ids": sorted(seen - targets)})
            state["status"] = "complete" if not missing and len(seen) == state["api_count"] else "partial"
    except BrowserReviewError as error:
        state.update(status="blocked", error=error.status, message=str(error))
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        state.update(status="error", error=type(error).__name__, message=str(error))
    except KeyboardInterrupt:
        state.update(status="paused", interrupted=True, message="Interrupted; rerun the same command to resume")
    state["updated_at"] = timestamp()
    save(state_path, state)
    print(json.dumps(state, ensure_ascii=False), flush=True)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, choices=[2026, 2027], nargs="+", default=[2027, 2026])
    parser.add_argument("--page-size", type=int, choices=range(1, 251), metavar="1..250", default=100)
    parser.add_argument("--delay", type=float, default=1, help="Seconds between batches (minimum 1)")
    parser.add_argument("--max-pages", type=int, help="Pause each year after this many additional pages")
    parser.add_argument("--refresh", action="store_true", help="Start a new pass instead of resuming")
    parser.add_argument("--status", action="store_true", help="Print saved progress without fetching")
    args = parser.parse_args()
    if args.delay < 1 or (args.max_pages is not None and args.max_pages < 1):
        parser.error("--delay must be at least 1; --max-pages must be positive")
    years = list(dict.fromkeys(args.year))
    directory = ROOT / ".runtime/review-sync"
    if args.status:
        for year in years:
            path = directory / f"{year}.json"
            print(path.read_text() if path.exists() else json.dumps({"year": year, "status": "not_started"}))
        return
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "worker.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, "A review sync is already running; use --status to inspect progress.\n")
        for year in years:
            result = sync_year(year, page_size=args.page_size, delay=args.delay,
                               max_pages=args.max_pages, refresh=args.refresh)
            if result.get("interrupted"):
                raise SystemExit(130)
            if result["status"] not in ("complete", "partial", "paused"):
                raise SystemExit(1)


if __name__ == "__main__":
    main()
