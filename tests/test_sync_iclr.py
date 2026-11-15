"""Test year separation and reviewer-score normalization."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sync", Path(__file__).resolve().parents[1] / "scripts" / "sync_iclr.py"
)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
PROVENANCE = {"source": "papercopilot", "retrieved_at": "2026-11-15T00:00:00+00:00"}


def record(**overrides):
    row = {"id": "abc123", "title": "Paper", "abstract": "Abstract", "track": "main",
           "status": "Reject", "reviewers": "A;B;C", "rating": "0;;6",
           "confidence": "2;3;4", "soundness": "1;2;3", "presentation": "1;2;3",
           "contribution": "1;2;3"}
    row.update(overrides)
    return row


class ScoresTest(unittest.TestCase):
    def test_zero_and_missing_remain_distinct_and_aligned(self):
        paper, reviews = sync.normalize_mirror(record(), PROVENANCE)
        self.assertEqual([r["rating"] for r in reviews], [0, None, 6])
        self.assertEqual(reviews[1]["reviewer"], "B")
        with tempfile.TemporaryDirectory() as directory:
            manifest = sync.export([record()], PROVENANCE, Path(directory), "main", year=2026)
            paper = json.loads((Path(directory) / "papers.jsonl").read_text())
            self.assertEqual(paper["rating_mean"], 3)
            self.assertEqual(manifest["rating_count"], 2)

    def test_no_reviews_does_not_create_a_phantom_review(self):
        row = record(**{k: "" for k in ["reviewers", "rating", "confidence", "soundness", "presentation", "contribution"]})
        self.assertEqual(sync.normalize_mirror(row, PROVENANCE)[1], [])

    def test_misalignment_is_rejected(self):
        with self.assertRaises(ValueError):
            sync.normalize_mirror(record(rating="2;4"), PROVENANCE)

    def test_only_official_reviews_are_extracted(self):
        row = {"id": "abc123", "content": {"title": {"value": "Paper"}, "abstract": {"value": "Text"}},
               "details": {"directReplies": [
                   {"id": "r1", "invitations": ["venue/Submission1/-/Official_Review"],
                    "content": {"rating": {"value": "0: strong reject"}}},
                   {"id": "c1", "invitations": ["venue/Submission1/-/Official_Comment"],
                    "content": {"rating": {"value": "10: strong accept"}}}]}}
        _, reviews = sync.normalize_official(row, PROVENANCE)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["rating"], 0)

    def test_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                sync.export([record(), record()], PROVENANCE, Path(directory), "main", year=2026)

    def test_main_scope_excludes_workshops(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = sync.export([record(), record(id="workshop", track="workshop_x")],
                                   PROVENANCE, Path(directory), "main", year=2026)
            self.assertEqual(manifest["paper_count"], 1)

    def test_2027_preserves_new_fields_and_missing_optional_fields(self):
        row = record(rating="1;;4", informativeness="2;3;4")
        row.pop("contribution")
        _, reviews = sync.normalize_mirror(row, PROVENANCE)
        self.assertEqual([r["rating"] for r in reviews], [1, None, 4])
        self.assertEqual([r["informativeness"] for r in reviews], [2, 3, 4])
        self.assertEqual([r["contribution"] for r in reviews], [None] * 3)
        with tempfile.TemporaryDirectory() as directory:
            manifest = sync.export([row], PROVENANCE, Path(directory), "main", year=2027)
            self.assertEqual(manifest["conference"], "ICLR 2027")
            self.assertEqual(manifest["rating_scale"]["values"], [1, 2, 3, 4])
            self.assertFalse(any("pre-rebuttal" in item for item in manifest["limitations"]))

    def test_2027_rejects_2026_scores_and_mismatched_year(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                sync.export([record()], PROVENANCE, Path(directory), "main", year=2027)
            with self.assertRaises(ValueError):
                sync.export([record()], {**PROVENANCE, "conference": "ICLR 2026"}, Path(directory), "main", year=2027)


if __name__ == "__main__":
    unittest.main()
