"""Review backfill restart, coverage accounting and failure boundaries."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import sync_review_text as sync
from scripts.review_text import cached_review


def page(ids, count=3):
    return {"status": "ok", "received": len(ids), "count": count, "papers": [
        {"id": paper, "notes": [{"id": "review-" + paper, "forum": paper, "readers": ["everyone"],
            "invitations": ["ICLR.cc/2027/Conference/Submission1/-/Official_Review"],
            "signatures": ["ICLR.cc/2027/Conference/Submission1/Reviewer_test"],
            "content": {"summary": {"value": "TEST ONLY: public review"}}}]} for paper in ids]}


class SyncReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "iclr2027").mkdir()
        (self.root / "iclr2027/papers.jsonl").write_text(
            "\n".join(json.dumps({"id": paper}) for paper in ("a", "b", "c")))
        self.fetch = patch.object(sync, "retrieve_submission_page")
        self.mock_fetch = self.fetch.start()
        self.addCleanup(self.fetch.stop)
        self.sleep = patch.object(sync.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def run_sync(self, **options):
        return sync.sync_year(2027, self.root, page_size=2, delay=1, **options)

    def test_resume_skips_committed_pages_and_caches_for_website(self):
        self.mock_fetch.return_value = page(["a", "b"])
        first = self.run_sync(max_pages=1)
        self.assertEqual((first["status"], first["offset"], first["reviews"]), ("paused", 2, 2))
        self.mock_fetch.reset_mock()
        self.mock_fetch.return_value = page(["c"])
        second = self.run_sync()
        self.mock_fetch.assert_called_once_with(2027, 2, 2)
        self.assertEqual((second["status"], second["covered_papers"], second["reviews"]), ("complete", 3, 3))
        cache, _ = cached_review(2027, "a", self.root)
        self.assertEqual(cache["reviews"][0]["reviewer"], "test")
        self.assertEqual(cache["status"], "available")
        self.mock_fetch.reset_mock()
        self.run_sync()
        self.mock_fetch.assert_not_called()

    def test_failed_fetch_retains_progress_and_never_caches_empty_reviews(self):
        self.mock_fetch.side_effect = [page(["a", "b"]), sync.BrowserReviewError("login_required", "TEST ONLY")]
        result = self.run_sync()
        self.assertEqual((result["status"], result["error"], result["offset"]), ("blocked", "login_required", 2))
        self.assertIsNone(cached_review(2027, "c", self.root)[0])
        self.mock_fetch.side_effect = None
        self.mock_fetch.return_value = page(["c"])
        self.assertEqual(self.run_sync()["status"], "complete")

    def test_missing_submission_and_empty_review_are_distinct(self):
        first = page(["a", "b"], count=2)
        first["papers"][1]["notes"] = []
        self.mock_fetch.return_value = first
        result = self.run_sync()
        self.assertEqual((result["status"], result["covered_papers"], result["papers_without_text"]), ("partial", 2, 1))
        coverage = json.loads((self.root / "iclr2027/raw/review_sync/coverage.json").read_text())
        self.assertEqual(coverage["missing_ids"], ["c"])
        self.assertEqual(cached_review(2027, "b", self.root)[0]["status"], "empty")

    def test_duplicate_and_changed_count_do_not_advance_progress(self):
        for last in [page(["b"]), page(["c"], count=4)]:
            with self.subTest(last=last):
                self.mock_fetch.side_effect = [page(["a", "b"]), last]
                result = self.run_sync(refresh=True)
                self.assertEqual((result["status"], result["offset"]), ("error", 2))

    def test_refresh_never_reuses_pages_from_an_earlier_pass(self):
        self.mock_fetch.side_effect = [page(["a", "b"]), page(["c"])]
        self.assertEqual(self.run_sync()["status"], "complete")
        self.mock_fetch.side_effect = None
        self.mock_fetch.return_value = page(["a", "b"])
        self.run_sync(refresh=True, max_pages=1)
        self.mock_fetch.reset_mock()
        self.mock_fetch.return_value = page(["c"])
        self.assertEqual(self.run_sync()["status"], "complete")
        self.mock_fetch.assert_called_once_with(2027, 2, 2)

    def test_resume_can_change_batch_size_without_restarting(self):
        self.mock_fetch.return_value = page(["a", "b"])
        self.run_sync(max_pages=1)
        self.mock_fetch.reset_mock()
        self.mock_fetch.return_value = page(["c"])
        result = sync.sync_year(2027, self.root, page_size=1, delay=1)
        self.assertEqual(result["status"], "complete")
        self.mock_fetch.assert_called_once_with(2027, 2, 1)

    def test_database_failure_retains_uncommitted_page_for_resume(self):
        import sqlite3
        self.mock_fetch.return_value = page(["a", "b"])
        with patch.object(sync, "store_review_batch", side_effect=sqlite3.OperationalError("TEST ONLY")):
            result = self.run_sync()
        self.assertEqual((result["status"], result["offset"]), ("error", 0))
        self.mock_fetch.reset_mock()
        self.assertEqual(self.run_sync(max_pages=1)["offset"], 2)
        self.mock_fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
