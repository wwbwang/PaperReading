#!/usr/bin/env python3
"""Independently reconcile exported metadata and scores with the saved source."""

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def validate(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    allowed_ratings = manifest.get("rating_scale", {}).get("values", [0, 2, 4, 6, 8, 10])
    papers = [json.loads(line) for line in (directory / "papers.jsonl").read_text().splitlines()]
    by_id = {paper["id"]: paper for paper in papers}
    assert len(by_id) == len(papers) == manifest["paper_count"], "Duplicate or missing papers"
    with (directory / "papers.csv").open(encoding="utf-8-sig", newline="") as handle:
        csv_papers = {row["id"]: row for row in csv.DictReader(handle)}
    with (directory / "reviews.csv").open(encoding="utf-8-sig", newline="") as handle:
        reviews = list(csv.DictReader(handle))
    assert len(reviews) == manifest["review_count"], "Review count mismatch"
    assert len({(r["paper_id"], r["review_index"]) for r in reviews}) == len(reviews)
    assert csv_papers.keys() == by_id.keys(), "CSV/JSONL paper IDs disagree"
    for review in reviews:
        paper = by_id[review["paper_id"]]
        index = int(review["review_index"]) - 1
        expected = paper["reviews"][index]
        assert review["reviewer"] == (expected["reviewer"] or ""), "Reviewer mismatch"
        for field in ["rating", "confidence", "soundness", "presentation", "contribution", "informativeness"]:
            actual = float(review[field]) if review.get(field) else None
            assert actual == expected.get(field), f"CSV/JSONL {field} mismatch"
    for paper in papers:
        assert paper["title"] and paper["paper_url"] and paper["pdf_url"]
        row = csv_papers[paper["id"]]
        assert row["title"] == paper["title"] and row["abstract"] == (paper["abstract"] or "")
        assert json.loads(row["ratings"]) == paper["ratings"]
        scores = [score for score in paper["ratings"] if score is not None]
        if scores:
            assert math.isclose(math.fsum(scores) / len(scores), paper["rating_mean"])
        else:
            assert paper["rating_mean"] is None and paper["rating_missing"]
        if paper["track"] == "main":
            assert all(score in allowed_ratings for score in scores), "Unexpected main-track rating"
        if "conference" in paper:
            assert paper["conference"] == manifest["conference"], "Mixed conference years"
    source_matches = None
    if manifest["provenance"]["source"] == "papercopilot":
        raw_path = directory / "raw" / "papercopilot.json"
        assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == manifest["provenance"]["sha256"]
        source = json.loads(raw_path.read_text())
        if manifest["scope"] == "main":
            source = [row for row in source if row.get("track", "main") == "main"]
        assert {r.get("openreview_forum") or r["id"] for r in source} == by_id.keys()
        for row in source:
            paper = by_id[row.get("openreview_forum") or row["id"]]
            assert paper["title"] == row["title"] and paper["abstract"] == (row.get("abstract") or None)
            expected = [] if not row.get("reviewers") else [
                None if token.strip().lower() in ("", "null", "none", "nan", "n/a") else float(token)
                for token in row["rating"].split(";")
            ]
            assert paper["ratings"] == expected, f"Source rating mismatch: {paper['id']}"
            for field in ["confidence", "soundness", "presentation", "contribution", "informativeness"]:
                tokens = str(row.get(field)).split(";") if row.get(field) else [""] * len(paper["reviews"])
                numbers = [None if t.strip().lower() in ("", "null", "none", "nan", "n/a")
                           else float(t) for t in tokens]
                assert [r.get(field) for r in paper["reviews"]] == numbers
        source_matches = len(source)
    for name, expected in manifest["output_sha256"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected
    report = {"validated_at": datetime.now(timezone.utc).isoformat(), "passed": True,
              "conference": manifest["conference"], "paper_count": len(papers), "review_count": len(reviews),
              "source_papers_reconciled": source_matches,
              "missing_abstracts": sum(not p["abstract"] for p in papers),
              "papers_without_ratings": sum(p["rating_missing"] for p in papers),
              "zero_ratings": sum(r["rating"] == 0 for p in papers for r in p["reviews"]),
              "statuses": dict(Counter(p["status"] for p in papers)),
              "official_full_coverage_verified": manifest["provenance"]["official_coverage_verified"],
              "pdf_accessibility_verified": False}
    (directory / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path,
                        default=Path(__file__).resolve().parents[1] / "iclr2027")
    validate(parser.parse_args().directory)
