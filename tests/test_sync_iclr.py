"""Test year separation and reviewer-score normalization."""

import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
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
    def test_official_venue_ids_preserve_decisions_and_acceptance_counts(self):
        from scripts.build_library import decision_counts
        for year in (2026, 2027):
            venue = f"ICLR.cc/{year}/Conference"
            cases = [(venue, f"ICLR {year} Poster", "Poster"),
                     (venue, f"ICLR {year} Oral", "Oral"),
                     (venue, f"ICLR {year}", "Accepted"),
                     (venue + "/Submission", f"Submitted to ICLR {year}", "Active"),
                     (venue + "/Rejected_Submission", f"Submitted to ICLR {year}", "Reject"),
                     (venue + "/Withdrawn_Submission", "Withdrawn", "Withdraw"),
                     (venue + "/Desk_Rejected_Submission", "Desk Rejected", "Desk Reject")]
            papers = []
            for venue_id, label, expected in cases:
                with self.subTest(year=year, expected=expected):
                    row = {"id": "paper", "content": {"title": {"value": "Title"},
                           "venue": {"value": label}, "venueid": {"value": venue_id}}}
                    paper, _ = sync.normalize_official(row, {**PROVENANCE, "conference": f"ICLR {year}"})
                    self.assertEqual(paper["status"], expected)
                    self.assertEqual(paper["venue_raw"], label)
                    self.assertEqual(paper["venue_id"], venue_id)
                    papers.append(paper)
            counts = decision_counts(papers)
            self.assertEqual(counts["acceptedPaperCount"], 3)
            self.assertEqual(counts["pendingDecisionCount"], 1)
            self.assertIsNone(counts["totalPaperCount"])

    def test_ambiguous_official_labels_do_not_imply_acceptance(self):
        self.assertEqual(sync.official_status({"venue": {"value": "Submitted to ICLR 2027"}}, 2027),
                         "Submitted to ICLR 2027")
        self.assertEqual(sync.official_status({"venue": {"value": "ICLR 2026 Poster"}}, 2027),
                         "ICLR 2026 Poster")
        self.assertEqual(sync.official_status({}, 2027), "Unknown")

    def test_public_authors_survive_official_and_mirror_normalization(self):
        row = {"id": "abc123", "readers": ["everyone"], "content": {
            "title": {"value": "Paper"}, "abstract": {"value": "Text"},
            "authors": {"value": [" Alice Li ", "李明", "Alice Li"], "readers": ["everyone"]}}}
        paper, _ = sync.normalize_official(row, PROVENANCE)
        self.assertEqual(paper["authors"], ["Alice Li", "李明", "Alice Li"])
        row["content"]["authors"]["readers"] = ["Conference/Authors"]
        self.assertEqual(sync.normalize_official(row, PROVENANCE)[0]["authors"], [])
        row["content"]["authors"] = {"value": ["Anonymous"]}
        self.assertEqual(sync.normalize_official(row, PROVENANCE)[0]["authors"], [])
        row["content"]["authors"] = {"value": ["Alice Li"]}
        row["readers"] = ["Conference/Authors"]
        self.assertEqual(sync.normalize_official(row, PROVENANCE)[0]["authors"], [])
        self.assertEqual(sync.normalize_mirror(record(author="Alice Li;Anonymous; Bob Zhang"), PROVENANCE)[0]["authors"], ["Alice Li", "Bob Zhang"])

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
                   {"id": "r1", "forum": "abc123", "readers": ["everyone"],
                    "signatures": ["ICLR.cc/2027/Conference/Submission1/Reviewer_A"],
                    "invitations": ["ICLR.cc/2027/Conference/Submission1/-/Official_Review"],
                    "content": {"rating": {"value": "0: strong reject"}}},
                   {"id": "c1", "invitations": ["venue/Submission1/-/Official_Comment"],
                    "content": {"rating": {"value": "10: strong accept"}}}]}}
        _, reviews = sync.normalize_official(row, PROVENANCE)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["rating"], 0)
        self.assertEqual(reviews[0]["reviewer"], "A")

    def test_official_keywords_and_public_review_fields_are_preserved(self):
        review = {"id": "r", "forum": "p", "readers": ["everyone"],
                  "invitations": ["ICLR.cc/2027/Conference/Submission1/-/Official_Review"],
                  "content": {"rating": {"value": "4: Accept"}, "confidence": {"value": 5, "readers": ["chairs"]}}}
        row = {"id": "p", "content": {"title": {"value": "Title"}, "keywords": {"value": ["Video", "Restoration"]}},
               "details": {"directReplies": [review, {**review, "id": "private", "readers": ["chairs"]},
                                              {**review, "id": "deleted", "ddate": 1}]}}
        paper, reviews = sync.normalize_official(row, PROVENANCE)
        self.assertEqual(paper["keywords"], "Video;Restoration")
        self.assertEqual(len(reviews), 1)
        self.assertIsNone(reviews[0]["confidence"])

    def test_numeric_zero_in_single_reviewer_mirror_is_not_missing(self):
        _, reviews = sync.normalize_mirror(record(reviewers="A", rating=0, confidence=0,
                                                  soundness=0, presentation=0, contribution=0), PROVENANCE)
        self.assertEqual(reviews[0]["rating"], 0)
        self.assertEqual(reviews[0]["confidence"], 0)

    def test_official_pagination_explicitly_requests_count(self):
        class Fetcher:
            def json(self, url):
                params = parse_qs(urlsplit(url).query)
                self_test.assertEqual(params["count"], ["true"])
                return {"count": 1, "notes": [{"id": "paper"}]}
        self_test = self
        with tempfile.TemporaryDirectory() as directory, patch.object(sync.time, "sleep"):
            records, provenance = sync.official_records(Fetcher(), Path(directory), False, 100)
        self.assertEqual(len(records), provenance["api_reported_count"])

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
