import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.paper_venues import VENUES, YEARS, not_held, valid_dataset
from scripts.sync_library import crossref_paper, cvf, journal, matches_container
from scripts.build_library import decision_counts, snapshot, write_json


class LibraryTests(unittest.TestCase):
    def test_decision_counts_use_explicit_statuses_not_scores(self):
        rows = [{"status": status, "rating_mean": 10} for status in
                ["Poster", "Oral", "Spotlight", "Highlight", "Award Candidate", "Accepted", "Published", "Reject", "Desk Reject", "Withdraw", "Active", "Unknown"]]
        self.assertEqual(decision_counts(rows), {"acceptedPaperCount": 7, "pendingDecisionCount": 2, "totalPaperCount": 12})

    def test_proceedings_only_never_imply_a_submission_total_or_acceptance_rate(self):
        self.assertEqual(decision_counts([{"status": "Published"}, {"status": "Accepted"}]),
                         {"acceptedPaperCount": 2, "pendingDecisionCount": 0, "totalPaperCount": None})
        self.assertIsNone(decision_counts([])["totalPaperCount"])

    def test_pending_and_missing_statuses_are_distinct_from_rejected_decisions(self):
        self.assertEqual(decision_counts([{"status": "Active"}, {}, {"status": "Withdraw"}]),
                         {"acceptedPaperCount": 0, "pendingDecisionCount": 2, "totalPaperCount": 3})
        self.assertEqual(decision_counts([{"status": "rejected"}, {"status": "withdrawn"}]),
                         {"acceptedPaperCount": 0, "pendingDecisionCount": 0, "totalPaperCount": 2})

    def test_staging_snapshot_does_not_overwrite_hardlinked_editable_source(self):
        import os
        with tempfile.TemporaryDirectory() as root:
            source, staged = Path(root) / "source.json", Path(root) / "staged.json"
            source.write_text('{"original":true}\n')
            os.link(source, staged)
            write_json(staged, {"different": True})
            self.assertEqual(source.read_text(), '{"original":true}\n')
            self.assertEqual(json.loads(staged.read_text()), {"different": True})

    def test_registry_and_dataset_path_boundary(self):
        self.assertEqual(len(VENUES), 23)
        self.assertTrue(all(valid_dataset(v, y) for v in VENUES for y in YEARS))
        for venue, year in [("../iclr", 2026), ("unknown", 2026), ("iclr", "2026/../"), ("tip", 2024)]:
            self.assertFalse(valid_dataset(venue, year))
        self.assertTrue(not_held("eccv", 2025))
        self.assertFalse(not_held("iccv", 2025))

    def test_conference_identity_does_not_match_unrelated_multimedia_events(self):
        self.assertTrue(matches_container("Proceedings of the 33rd ACM International Conference on Multimedia", "acmmm"))
        self.assertTrue(matches_container("Computer Vision – ECCV 2026", "eccv"))
        for title in ["Proceedings of the 2026 International Conference on Multimedia Retrieval",
                      "Proceedings of the ACM Multimedia Systems Conference 2026", "2025 IEEE International Conference on Multimedia and Expo (ICME)",
                      "Proceedings of the 33rd ACM International Conference on Multimedia Workshops"]:
            self.assertFalse(matches_container(title, "acmmm"))

    def test_publisher_authors_and_missing_reviews(self):
        paper = crossref_paper({"DOI": "10.1/TEST", "title": ["<b>A</b>"], "author": [{"given": "Alice", "family": "Li"}],
                               "published": {"date-parts": [[2025, 2]]}}, "tip", 2025)
        self.assertEqual(paper["authors"], ["Alice Li"])
        self.assertEqual(paper["title"], "A")
        self.assertEqual(paper["ratings"], [])
        self.assertIsNone(paper["rating_mean"])
        self.assertEqual(paper["doi"], "10.1/test")

    def test_aim_odd_year_uses_iccv_workshops(self):
        class Cache:
            urls = []

            def get(self, url):
                self.urls.append(url)
                return b"No public proceedings yet"

        cache = Cache()
        with self.assertRaises(ValueError):
            cvf(cache, "aim", 2025)
        self.assertEqual(cache.urls, ["https://openaccess.thecvf.com/ICCV2025_workshops/AIM"])

    def test_unavailable_year_has_no_fake_rows(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            folder = root / "library/tip/2027"
            folder.mkdir(parents=True)
            manifest = {"status": "unavailable", "retrieved_at": "2026-11-16T00:00:00Z", "message": "Not retrieved",
                        "author_count": 0, "errors": [], "abstract_count": 0, "keyword_count": 0}
            (folder / "manifest.json").write_text(json.dumps(manifest))
            with patch("scripts.build_library.ROOT", root):
                data = snapshot("tip", 2027, root / "assets")
            self.assertEqual(data["queries"]["papers"]["rows"], [])
            self.assertEqual(data["iclr"]["datasetStatus"], "unavailable")

    def test_abstract_enrichment_paginates_and_joins_only_exact_published_dois(self):
        from urllib.parse import parse_qs, urlsplit

        class Cache:
            pages = []

            def json(self, url):
                if "crossref.org" in url:
                    return {"message": {"total-results": 1, "items": [{"DOI": "10.1/real", "title": ["Paper"],
                        "author": [{"given": "Official", "family": "Author"}], "published": {"date-parts": [[2025]]}}]}}
                params = parse_qs(urlsplit(url).query)
                assert "cursor" not in params
                page = int(params["page"][0]);self.pages.append(page)
                return {"results": [{"doi": "https://doi.org/10.1/unrelated", "abstract_inverted_index": {"wrong": [0]}}] * 200 if page == 1 else [
                    {"doi": "https://doi.org/10.1/real", "abstract_inverted_index": {"abstract": [1], "Correct": [0]}, "primary_location": {"pdf_url": "https://publisher.example/paper.pdf"}}]}

        cache = Cache()
        with patch("scripts.sync_library.time.sleep"):
            papers, metadata = journal(cache, "tip", 2025)
        self.assertEqual(cache.pages, [1, 2])
        self.assertEqual(papers[0]["abstract"], "Correct abstract")
        self.assertEqual(papers[0]["authors"], ["Official Author"])
        self.assertIsNone(metadata["abstract_enrichment_error"])


if __name__ == "__main__":
    unittest.main()
