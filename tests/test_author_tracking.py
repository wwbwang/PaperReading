import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.author_tracking import build_tracking, classify, parse_publications, title_key


class AuthorTrackingTests(unittest.TestCase):
    profile = {"id": "dong", "aliases": ["Chao Dong", "董超"]}
    publication = {"title": "A Verified Paper", "url": "https://example.org/paper"}

    def test_public_identity_requires_both_name_and_explicit_publication_evidence(self):
        evidence = {title_key(self.publication["title"]): self.publication}
        for names in [[], ["Anonymous"], ["Alice Dong"], ["Chaochao Dong"]]:
            self.assertEqual(classify({"title": "A Verified Paper", "authors": names}, self.profile, evidence), (None, None))
        self.assertEqual(classify({"title": "A Verified Paper", "authors": ["Dong Chao"]}, self.profile, evidence),
                         ("verified", "https://example.org/paper"))
        self.assertEqual(classify({"title": "Different Work", "authors": ["Chao Dong"]}, self.profile, evidence), ("candidate", None))

    def test_publication_parser_excludes_preprints_and_other_group_members(self):
        page = '<h4><a href="/paper">A Verified Paper</a></h4><h5>Alice Li, Chao Dong</h5><h5>CVPR, 2025</h5>'
        page += '<h4>Anonymous Submission</h4><h5>Chao Dong</h5><h5>ArXiv, 2027</h5>'
        page += '<h4>Other Team Work</h4><h5>Alice Li, Bob Zhang</h5><h5>ICLR, 2027</h5>'
        papers = parse_publications(page, "https://example.org/publications", self.profile["aliases"])
        self.assertEqual(papers, [{"title": "A Verified Paper", "url": "https://example.org/paper", "venue": "CVPR, 2025"}])

    def test_title_matching_tolerates_punctuation_but_never_partial_titles(self):
        self.assertEqual(title_key("HAT: Hybrid Attention Transformer"), title_key("HAT — Hybrid attention transformer."))
        self.assertNotEqual(title_key("A Paper"), title_key("A Paper With More Words"))
        self.assertEqual(title_key(r"Attention with $\mathcal{O}(T)$ Complexity"), title_key("Attention with O(T) Complexity"))

    def test_local_index_preserves_first_seen_and_never_backfills_anonymous_authors(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root);dist = root / "dist";directory = root / "authors"
            folder = dist / "data/cvpr/2025/revision";folder.mkdir(parents=True);directory.mkdir()
            (directory / "watchlist.json").write_text(json.dumps({"authors": [self.profile]}))
            (directory / "dong.json").write_text(json.dumps({"retrieved_at": "2026-11-17", "publications": [self.publication]}))
            with sqlite3.connect(folder / "_search.sqlite3") as db:
                db.execute("CREATE TABLE authors (paper_id TEXT, name TEXT, search TEXT)")
                db.executemany("INSERT INTO authors VALUES (?, ?, ?)", [("public", "Chao Dong", "chao dong"), ("namesake", "Chao Dong", "chao dong"), ("partial", "Chaochao Dong", "chaochao dong")])
            details = {"public": {"authors": ["Chao Dong"], "paper_url": "https://publisher.org/p", "pdf_url": "javascript:alert(1)"},
                       "namesake": {"authors": ["Chao Dong"]}, "anonymous": {"authors": []}, "partial": {"authors": ["Chaochao Dong"]}}
            (folder / "a.json").write_text(json.dumps(details))
            rows = [{"id": key, "title": "Other Title" if key == "namesake" else "A Verified Paper", "detail_chunk": "a", "status": "Published", "rating_mean": None, "rating_count": 0} for key in details]
            meta = {"venue": "cvpr", "year": 2025, "detailBase": "/data/cvpr/2025/revision/", "authorPaperCount": 3}
            payload = build_tracking(dist, [(meta, rows)], directory)
            author = payload["authors"][0]
            self.assertEqual((author["verifiedCount"], author["candidateCount"]), (1, 1))
            self.assertEqual({p["id"] for p in author["papers"]}, {"public", "namesake"})
            self.assertEqual(next(p for p in author["papers"] if p["id"] == "public")["pdf_url"], "")
            first_seen = {p["key"]: p["first_seen"] for p in author["papers"]}
            again = build_tracking(dist, [(meta, rows)], directory)
            self.assertEqual({p["key"]: p["first_seen"] for p in again["authors"][0]["papers"]}, first_seen)
            self.assertEqual(json.loads((dist / "authors.json").read_text()), again)


if __name__ == "__main__":
    unittest.main()
