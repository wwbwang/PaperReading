"""Check HTTP caching, year isolation and exact literal abstract search."""
import gzip
import importlib.util
import json
import sqlite3
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("paper_server", ROOT / "scripts/serve_paperreading.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temporary.name)
        cls.revision = "a" * 64
        (cls.directory / "index.html").write_text("PaperReading")
        (cls.directory / "index.html.gz").write_bytes(gzip.compress(b"PaperReading"))
        for year in [2026, 2027]:
            folder = cls.directory / "data/iclr" / str(year) / cls.revision
            folder.mkdir(parents=True)
            (folder / "00.json").write_text('{}')
            with sqlite3.connect(folder / "_search.sqlite3") as database:
                database.execute("CREATE TABLE papers (id TEXT, search TEXT, keywords TEXT, keyword_search TEXT, title_search TEXT)")
                database.executemany("INSERT INTO papers VALUES (?, ?, ?, ?, ?)", [(f"{year}-a", "title-only multi-agent\nabstract only needle%_ 图像", "Image Restoration; Multi-Agent; 图像", "image restoration multi agent 图像", "title only multi agent"), (f"{year}-b", "another\nsecond abstract", "Diffusion; Generative Modeling", "diffusion generative modeling", "another")])
                database.execute("CREATE TABLE authors (paper_id TEXT, name TEXT, search TEXT)")
                if year == 2026:
                    database.executemany("INSERT INTO authors VALUES (?, ?, ?)", [
                        ("2026-a", "Alice Li", "alice li"), ("2026-a", "Bob Zhang", "bob zhang"),
                        ("2026-a", "李明", "李明"), ("2026-b", "Alice Zhang", "alice zhang"),
                        ("2026-b", "François Martin", "françois martin")])
            database.close()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(module.DashboardHandler, directory=str(cls.directory)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.client = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temporary.cleanup()

    def search_url(self, year=2027, revision=None, query="NEEDLE%_"):
        return self.base + "/api/search?" + urlencode({"conference": "iclr", "year": year, "revision": revision or self.revision, "q": query})

    def test_literal_abstract_search_and_year_isolation(self):
        for year in [2026, 2027]:
            for query in ["NEEDLE%_", "图像"]:
                with self.client.open(self.search_url(year, query=query)) as response:
                    result = json.load(response)
                self.assertEqual(result, {"revision": self.revision, "ids": [f"{year}-a"]})
        with self.client.open(self.search_url(query="' OR 1=1 --")) as response:
            self.assertEqual(json.load(response)["ids"], [])

    def test_unknown_snapshot_and_invalid_parameters(self):
        for url, status in [(self.search_url(revision="b" * 64), 409), (self.search_url(year=2028), 400), (self.search_url(revision="../../etc"), 400), (self.search_url() + "&year=2026", 400)]:
            with self.assertRaises(HTTPError) as error:
                self.client.open(url)
            self.assertEqual(error.exception.code, status)

    def test_keyword_partial_search_and_combined_filters(self):
        for year in [2026, 2027]:
            for keywords, query, expected in [
                ("DIFF", "", [f"{year}-b"]),
                ("ＤＩＦＦ", "", [f"{year}-b"]),
                ("multi-ag", "", [f"{year}-a"]),
                ("AGENT multi", "", [f"{year}-a"]),
                ("图像", "", [f"{year}-a"]),
                ("diff", "another", [f"{year}-b"]),
                ("diff", "needle", []),
                ("diff restoration", "", []),
                ("%_'", "", []),
            ]:
                url = self.search_url(year, query=query) + "&" + urlencode({"keywords": keywords, "keyword_scope": "keywords"})
                with self.subTest(year=year, keywords=keywords, query=query), self.client.open(url) as response:
                    self.assertEqual(json.load(response)["ids"], expected)

    def test_keywords_are_batched_and_year_scoped(self):
        params = {"year": 2027, "revision": self.revision, "ids": "2027-a,2027-b"}
        url = self.base + "/api/keywords?"
        with self.client.open(url + urlencode(params)) as response:
            result = json.load(response)
        self.assertEqual(result["keywords"], {"2027-a": "Image Restoration; Multi-Agent; 图像", "2027-b": "Diffusion; Generative Modeling"})
        params["year"] = 2026
        with self.client.open(url + urlencode(params)) as response:
            self.assertEqual(json.load(response)["keywords"], {})
        for ids in ["../../etc", ",".join(["2026-a"] * 26)]:
            params["ids"] = ids
            with self.assertRaises(HTTPError) as error:
                self.client.open(url + urlencode(params))
            self.assertEqual(error.exception.code, 400)

    def test_fuzzy_search_scope_defaults_to_both_and_excludes_abstract(self):
        for year in [2026, 2027]:
            for query, scope, expected in [
                ("TITLE-on", None, [f"{year}-a"]),
                ("TITLE-on", "title", [f"{year}-a"]),
                ("TITLE-on", "keywords", []),
                ("restor", "both", [f"{year}-a"]),
                ("restor", "title", []),
                ("restor", "keywords", [f"{year}-a"]),
                ("ＴＩＴＬＥ multi-AG", "title", [f"{year}-a"]),
                ("title restoration", "both", [f"{year}-a"]),
                ("title restoration", "title", []),
                ("title restoration", "keywords", []),
                ("needle", "both", []),
                ("needle", "title", []),
                ("%_'", "both", []),
            ]:
                params = {"keywords": query}
                if scope is not None:
                    params["keyword_scope"] = scope
                with self.subTest(year=year, query=query, scope=scope), self.client.open(self.search_url(year, query="") + "&" + urlencode(params)) as response:
                    self.assertEqual(json.load(response)["ids"], expected)
        for suffix in ["&keyword_scope=invalid", "&keyword_scope=title&keyword_scope=both"]:
            with self.assertRaises(HTTPError) as error:
                self.client.open(self.search_url(query="") + suffix)
            self.assertEqual(error.exception.code, 400)

    def test_gzip_revalidation_and_immutable_assets(self):
        with self.client.open(Request(self.base + "/", headers={"Accept-Encoding": "gzip;q=0.8"})) as response:
            self.assertEqual(gzip.decompress(response.read()), b"PaperReading")
            etag = response.headers["ETag"]
            self.assertEqual(response.headers["Cache-Control"], "no-cache")
        with self.assertRaises(HTTPError) as error:
            self.client.open(Request(self.base + "/", headers={"Accept-Encoding": "gzip", "If-None-Match": etag}))
        self.assertEqual(error.exception.code, 304)
        with self.client.open(Request(self.base + "/", headers={"Accept-Encoding": "gzip;q=0"})) as response:
            self.assertIsNone(response.headers["Content-Encoding"])
            self.assertEqual(response.read(), b"PaperReading")
        with self.client.open(self.base + f"/data/iclr/2027/{self.revision}/00.json") as response:
            self.assertIn("immutable", response.headers["Cache-Control"])

    def test_author_search_matches_one_author_and_intersects_other_queries(self):
        for authors, query, keywords, expected in [
            ("ALIC", "", "", ["2026-a", "2026-b"]),
            ("ＡＬＩＣＥ", "", "", ["2026-a", "2026-b"]),
            ("zhang alice", "", "", ["2026-b"]),
            ("li alice", "", "", ["2026-a", "2026-b"]),
            ("bob zhang", "", "", ["2026-a"]),
            ("François", "", "", ["2026-b"]),
            ("李", "", "", ["2026-a"]),
            ("alice", "needle", "", ["2026-a"]),
            ("alice", "", "diff", ["2026-b"]),
            ("alice", "needle", "diff", []),
            ("needle", "", "", []),
            ("%_'", "", "", []),
            ("' OR 1=1 --", "", "", []),
        ]:
            url = self.search_url(2026, query=query) + "&" + urlencode({"authors": authors, "keywords": keywords})
            with self.subTest(authors=authors, query=query, keywords=keywords), self.client.open(url) as response:
                self.assertEqual(json.load(response)["ids"], expected)

    def test_missing_author_data_is_reported_separately_from_empty_results(self):
        url = self.search_url(2027, query="") + "&authors=alice"
        with self.assertRaises(HTTPError) as caught:
            self.client.open(url)
        self.assertEqual(caught.exception.code, 422)
        self.assertEqual(json.load(caught.exception)["status"], "unavailable")
        for suffix in ["&authors=a&authors=b", "&authors=" + "a" * 501]:
            with self.assertRaises(HTTPError) as caught:
                self.client.open(self.search_url(2026, query="") + suffix)
            self.assertEqual(caught.exception.code, 400)

    def test_review_endpoint_checks_year_membership_before_fetching(self):
        params = {"year": 2027, "revision": self.revision, "paper_id": "2027-a"}
        result = {"paper_id": "2027-a", "status": "available", "reviews": []}
        with patch.object(module, "retrieve", return_value=(result, 200)) as fetch:
            with self.client.open(self.base + "/api/reviews?" + urlencode(params)) as response:
                self.assertEqual(json.load(response), result)
            fetch.assert_called_once_with(2027, "2027-a")
            params["year"] = 2026
            with self.assertRaises(HTTPError) as error:
                self.client.open(self.base + "/api/reviews?" + urlencode(params))
            self.assertEqual(error.exception.code, 404)
            self.assertEqual(fetch.call_count, 1)
        params["paper_id"] = "../../etc"
        with self.assertRaises(HTTPError) as error:
            self.client.open(self.base + "/api/reviews?" + urlencode(params))
        self.assertEqual(error.exception.code, 400)

    def test_private_search_database_cannot_be_downloaded(self):
        with self.assertRaises(HTTPError) as error:
            self.client.open(self.base + f"/data/iclr/2027/{self.revision}/_search.sqlite3")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
