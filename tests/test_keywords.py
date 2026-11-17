"""Verify source keywords and authors survive the build without inflating bootstrap rows."""
import json
import sqlite3
import unittest
from pathlib import Path

from scripts.paper_keywords import keyword_search_text, public_author_names

ROOT = Path(__file__).resolve().parents[1]


class KeywordTests(unittest.TestCase):
    def test_normalization_preserves_partial_search_terms(self):
        self.assertEqual(keyword_search_text(" ＤＩＦＦＵＳＩＯＮ; Multi-Agent_learning "), "diffusion multi agent learning")
        self.assertEqual(keyword_search_text("Straße; 图像恢复"), "strasse 图像恢复")
        self.assertEqual(keyword_search_text("%_'"), "")
        self.assertEqual(keyword_search_text(None), "")
        self.assertEqual(public_author_names("Anonymous;Alice Li;unknown; Alice Li ;Bob Zhang"), ["Alice Li", "Alice Li", "Bob Zhang"])
        self.assertEqual(public_author_names(["ANONYMOUS AUTHORS", "李明", None]), ["李明"])

    def test_every_paper_retains_source_keywords_and_normalized_search(self):
        for year in [2026, 2027]:
            with self.subTest(year=year):
                folder = ROOT / f"web/dist/iclr/{year}"
                build = json.loads((folder / "data-app-build.json").read_text())
                snapshot = json.loads((folder / build["snapshot"]["path"]).read_text())
                manifest = json.loads((ROOT / f"iclr{year}/manifest.json").read_text())
                self.assertNotEqual(snapshot["iclr"]["revision"], manifest["output_sha256"]["papers.jsonl"], "Web detail schemas require a separate cache revision")
                rows = snapshot["queries"]["papers"]["rows"]
                raw = json.loads((ROOT / f"iclr{year}/raw/papercopilot.json").read_bytes())
                keywords = {row.get("openreview_forum") or row["id"]: row.get("keywords") or "" for row in raw}
                authors = {row.get("openreview_forum") or row["id"]: [name.strip() for name in (row.get("author") or "").split(";") if name.strip()] for row in raw}
                del raw
                database = sqlite3.connect(ROOT / "web/dist" / snapshot["iclr"]["detailBase"].lstrip("/") / "_search.sqlite3")
                try:
                    self.assertEqual(database.execute("SELECT revision FROM metadata").fetchone()[0], snapshot["iclr"]["revision"])
                    indexed = {row[0]: row[1:] for row in database.execute("SELECT id, keywords, keyword_search, title_search, abstract_search FROM papers")}
                    indexed_authors = {}
                    for paper_id, name, search in database.execute("SELECT paper_id, name, search FROM authors ORDER BY rowid"):
                        indexed_authors.setdefault(paper_id, []).append((name, search))
                finally:
                    database.close()
                self.assertEqual(len(indexed), len(rows))
                self.assertEqual(snapshot["iclr"]["authorPaperCount"], len(indexed_authors))
                self.assertLessEqual(indexed_authors.keys(), indexed.keys())
                abstracts = {paper["id"]: paper["abstract"] for paper in map(json.loads, (ROOT / f"iclr{year}/papers.jsonl").open())}
                for row in rows:
                    self.assertNotIn("keywords", row, "Keywords must stay out of the initial payload")
                    self.assertNotIn("authors", row, "Authors must stay out of the initial payload")
                    original = keywords[row["id"]]
                    self.assertTrue(original, row["id"])
                    self.assertEqual(indexed[row["id"]], (original, keyword_search_text(original), keyword_search_text(row["title"]), keyword_search_text(abstracts[row["id"]])), row["id"])
                    self.assertEqual(indexed_authors.get(row["id"], []), [(name, keyword_search_text(name)) for name in authors[row["id"]]], row["id"])


if __name__ == "__main__":
    unittest.main()
