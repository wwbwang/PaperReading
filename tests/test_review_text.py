"""Public review normalization, correct reviewer matching, cache and access limits."""
import io
import json
import tempfile
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
        review_text._blocked_until = 0

    def tearDown(self):
        review_text._blocked_until = self.old_blocked
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
