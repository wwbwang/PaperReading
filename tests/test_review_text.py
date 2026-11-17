"""Public review normalization, correct reviewer matching, cache and access limits."""
import io
import json
import os
import tempfile
import sqlite3
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import review_text


def note(**changes):
    value = {"id": "review-note", "forum": "paper-a", "readers": ["everyone"],
             "invitations": ["ICLR.cc/2027/Conference/Submission1/-/Official_Review"],
             "signatures": ["ICLR.cc/2027/Conference/Submission1/Reviewer_4QfN"],
             "content": {"summary": {"value": "TEST ONLY: paper overview"},
                         "strengths": {"value": "TEST ONLY: strengths"},
                         "weaknesses": {"value": "TEST ONLY: limitations"},
                         "questions": {"value": "TEST ONLY: a question"},
                         "additional_comments": {"value": "TEST ONLY: extra comments"},
                         "rating": {"value": "4: Accept"}}}
    value.update(changes)
    return value


class ReviewTextTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.old_blocked = review_text._blocked_until
        self.old_limited = review_text._rate_limited_until
        review_text._blocked_until = 0
        review_text._rate_limited_until = 0
        self.browser = patch.object(review_text, "retrieve_pages", side_effect=review_text.BrowserReviewError(
            "verification_required", "请在当前机器的浏览器中完成验证或登录，再重新获取。"))
        self.browser_mock = self.browser.start()
        self.addCleanup(self.browser.stop)

    def tearDown(self):
        review_text._blocked_until = self.old_blocked
        review_text._rate_limited_until = self.old_limited
        self.directory.cleanup()

    def test_keeps_public_original_sections_and_alias(self):
        result = review_text.normalize([note()], 2027, "paper-a")
        self.assertEqual(result[0]["reviewer"], "4QfN")
        self.assertEqual(len(result[0]["sections"]), 5)
        self.assertEqual(result[0]["sections"][0]["text"], "TEST ONLY: paper overview")
        self.assertEqual(result[0]["rating"], "4: Accept")
        self.assertIn("noteId=review-note", result[0]["url"])

    def test_excludes_other_forums_years_private_notes_comments_and_deleted_reviews(self):
        invalid = [note(forum="other"), note(readers=["ICLR.cc/2027/Conference"]),
                   note(ddate=1), note(invitations=["ICLR.cc/2026/Conference/Submission1/-/Official_Review"]),
                   note(invitations=["ICLR.cc/2027/Conference/Submission1/-/Official_Comment"]),
                   note(invitations=["ICLR.cc/2027/Conference/Submission1/-/Meta_Review"])]
        self.assertEqual(review_text.normalize(invalid, 2027, "paper-a"), [])

    def test_missing_alias_is_not_inferred_from_position_or_rating(self):
        self.assertIsNone(review_text.normalize([note(signatures=[])], 2027, "paper-a")[0]["reviewer"])
        duplicates = review_text.normalize([note(), note()], 2027, "paper-a")
        self.assertEqual(len(duplicates), 1)

    def test_import_and_cached_retrieval_preserve_raw_notes(self):
        path = self.root / "export.json"
        path.write_text(json.dumps({"notes": [note()]}))
        result, status = review_text.retrieve(2027, "paper-a", self.root, input_path=path)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "available")
        raw = json.loads((self.root / "iclr2027/raw/review_text/paper-a.json").read_text())
        self.assertEqual(raw["pages"][0]["notes"], [note()])
        with patch.object(review_text, "build_opener", side_effect=AssertionError("must use cache")):
            self.assertEqual(review_text.retrieve(2027, "paper-a", self.root)[0], result)

    def test_batch_cache_serves_without_network_and_excludes_private_fields(self):
        (self.root / "iclr2027").mkdir()
        public = note()
        public["content"]["secret"] = {"value": "PRIVATE", "readers": ["chairs"]}
        results = review_text.store_review_batch(2027, [{"id": "paper-a", "notes": [public]}],
                                                self.root, retrieved_at=review_text.timestamp())
        with patch.object(review_text, "build_opener", side_effect=AssertionError("must use batch cache")):
            self.assertEqual(review_text.retrieve(2027, "paper-a", self.root), (results[0], 200))
        with sqlite3.connect(self.root / "iclr2027/review_text.sqlite3") as database:
            row = database.execute("SELECT result, raw FROM reviews").fetchone()
        self.assertNotIn("PRIVATE", "".join(row))
        self.assertIn("TEST ONLY: paper overview", row[1])

    def test_cached_reviews_do_not_wait_for_other_paper_network_lock(self):
        path = self.root / "export.json"
        path.write_text(json.dumps({"notes": [note()]}))
        original, _ = review_text.retrieve(2027, "paper-a", self.root, input_path=path)
        class BusyLock:
            def __enter__(self):
                raise AssertionError("Cached reads must bypass network lock")
            def __exit__(self, *args):
                pass
        with patch.object(review_text, "_guard", BusyLock()):
            self.assertEqual(review_text.retrieve(2027, "paper-a", self.root), (original, 200))

    def test_future_filesystem_mtime_cannot_hide_newer_batch_reviews(self):
        path = self.root / "export.json"
        path.write_text(json.dumps({"notes": [note()]}))
        review_text.retrieve(2027, "paper-a", self.root, input_path=path)
        cache = self.root / "iclr2027/review_text/paper-a.json"
        future = time.time() + 86400
        os.utime(cache, (future, future))
        updated = note()
        updated["content"]["summary"]["value"] = "TEST ONLY: newer official text"
        results = review_text.store_review_batch(2027, [{"id": "paper-a", "notes": [updated]}], self.root,
                                                retrieved_at=review_text.timestamp())
        self.assertEqual(review_text.retrieve(2027, "paper-a", self.root), (results[0], 200))

    def test_challenge_is_explicit_and_stops_repeated_requests(self):
        error = HTTPError("https://api2.openreview.net/notes", 403, "Forbidden", {}, io.BytesIO(b"challenge"))
        with patch.object(review_text, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            first, status = review_text.retrieve(2027, "paper-a", self.root)
            second, second_status = review_text.retrieve(2027, "paper-b", self.root)
            self.assertEqual(status, 503)
            self.assertEqual(second_status, 503)
            self.assertEqual(first["status"], "blocked")
            self.assertEqual(second["reviews"], [])
            self.assertEqual(opener.return_value.open.call_count, 1)
        self.assertFalse((self.root / "iclr2027/review_text/paper-a.json").exists())

    def test_invalid_identifiers_are_rejected(self):
        for year, paper_id in [(2028, "paper-a"), (2027, "../../etc/passwd")]:
            with self.assertRaises(ValueError):
                review_text.retrieve(year, paper_id, self.root)

    def test_browser_success_after_http_challenge_and_during_cooldown(self):
        self.browser_mock.side_effect = None
        self.browser_mock.return_value = [{"notes": [note()]}]
        error = HTTPError("https://api2.openreview.net/notes", 403, "Forbidden", {}, io.BytesIO())
        with patch.object(review_text, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            first, status = review_text.retrieve(2027, "paper-a", self.root)
            self.assertEqual((status, first["status"], first["transport"]), (200, "available", "browser"))
            blocked_until = review_text._blocked_until
            # Completing browser verification must work without waiting for HTTP cooldown.
            second, _ = review_text.retrieve(2027, "paper-a", self.root, refresh=True)
            self.assertEqual(second["reviews"], first["reviews"])
            self.assertEqual(opener.return_value.open.call_count, 1)
            self.assertEqual(self.browser_mock.call_count, 2)
            self.assertEqual(review_text._blocked_until, blocked_until)

    def test_http_pagination_requests_total_and_collects_all_pages(self):
        pages = []
        for review_id in ("review-1", "review-2"):
            response = io.BytesIO(json.dumps({"notes": [note(id=review_id)], "count": 2}).encode())
            response.headers = {"Content-Type": "application/json"}
            pages.append(response)
        with patch.object(review_text, "build_opener") as opener:
            opener.return_value.open.side_effect = pages
            result, status = review_text.retrieve(2027, "paper-a", self.root)
            urls = [call.args[0].full_url for call in opener.return_value.open.call_args_list]
        self.assertEqual(status, 200)
        self.assertEqual([r["id"] for r in result["reviews"]], ["review-1", "review-2"])
        self.assertTrue(all("count=true" in url for url in urls))
        self.assertIn("offset=1", urls[1])
        self.browser_mock.assert_not_called()

    def test_private_fields_and_notes_never_enter_raw_or_display_cache(self):
        public = note()
        public["content"]["private_comment"] = {"value": "PRIVATE FIELD", "readers": ["chairs"]}
        path = self.root / "export.json"
        path.write_text(json.dumps({"notes": [public, note(id="private", readers=["chairs"])]}))
        result, _ = review_text.retrieve(2027, "paper-a", self.root, input_path=path)
        self.assertNotIn("PRIVATE FIELD", json.dumps(result))
        raw = (self.root / "iclr2027/raw/review_text/paper-a.json").read_text()
        self.assertNotIn("PRIVATE FIELD", raw)
        self.assertNotIn('"private"', raw)

    def test_rate_limit_does_not_switch_transport_or_retry_until_cooldown(self):
        error = HTTPError("https://api2.openreview.net/notes", 429, "Limited", {}, io.BytesIO())
        with patch.object(review_text, "build_opener") as opener:
            opener.return_value.open.side_effect = error
            for paper in ("paper-a", "paper-b"):
                result, status = review_text.retrieve(2027, paper, self.root)
                self.assertEqual((status, result["browser_status"]), (503, "rate_limited"))
            self.assertEqual(opener.return_value.open.call_count, 1)
            self.browser_mock.assert_not_called()

    def test_failed_refresh_keeps_previous_public_text_and_timestamp(self):
        path = self.root / "export.json"
        path.write_text(json.dumps({"notes": [note()]}))
        original, _ = review_text.retrieve(2027, "paper-a", self.root, input_path=path)
        cache = self.root / "iclr2027/review_text/paper-a.json"
        with patch.object(review_text.time, "time", return_value=time.time() + 21601), \
                patch.object(review_text, "build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError()
            result, status = review_text.retrieve(2027, "paper-a", self.root)
        self.assertEqual(status, 200)
        self.assertTrue(result["stale"])
        self.assertEqual(result["reviews"], original["reviews"])
        self.assertEqual(result["retrieved_at"], original["retrieved_at"])
        self.assertEqual(json.loads(cache.read_text()), original)

    def test_http_200_verification_html_is_blocked_and_not_cached_as_review_data(self):
        response = io.BytesIO(b'<html><title>Verifying your browser</title><div class="cf-turnstile"></div></html>')
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        with patch.object(review_text, "build_opener") as opener:
            opener.return_value.open.return_value = response
            result, status = review_text.retrieve(2027, "paper-a", self.root)
            self.assertEqual((result["status"], status), ("blocked", 503))
            self.assertIn("登录", result["message"])
            self.assertEqual(review_text.retrieve(2027, "paper-b", self.root)[1], 503)
            self.assertEqual(opener.return_value.open.call_count, 1)
        self.assertFalse((self.root / "iclr2027/review_text/paper-a.json").exists())
        error = json.loads((self.root / "iclr2027/raw/review_text/last_error.json").read_text())
        self.assertEqual(error["http_status"], 200)
        self.assertEqual(error["error"], "BrowserVerificationRequired")


if __name__ == "__main__":
    unittest.main()
