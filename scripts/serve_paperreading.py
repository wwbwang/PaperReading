#!/usr/bin/env python3
"""Serve PaperReading's static library and snapshot-scoped abstract search."""

import argparse
import gzip
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.review_text import retrieve
from scripts.paper_keywords import keyword_search_text
from scripts.browser_viewer import proxy_browser


class DashboardHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_request(self, code="-", size="-"):
        if urlsplit(self.path).path.startswith("/browser"):
            self.log_message('"%s %s" %s %s', self.command, urlsplit(self.path).path, code, size)
        else:
            super().log_request(code, size)

    def accepts_gzip(self):
        return any(re.fullmatch(r"gzip(?:\s*;\s*q=(?!0(?:\.0*)?$)[01](?:\.\d+)?)?", part.strip())
                   for part in self.headers.get("Accept-Encoding", "").split(","))

    def do_GET(self):
        if urlsplit(self.path).path == "/browser":
            self.send_response(302)
            self.send_header("Location", "/browser/" + ("?" + urlsplit(self.path).query if urlsplit(self.path).query else ""))
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif urlsplit(self.path).path.startswith("/browser/"):
            proxy_browser(self)
        elif urlsplit(self.path).path == "/api/search":
            self.search()
        elif urlsplit(self.path).path == "/api/reviews":
            self.reviews()
        elif urlsplit(self.path).path == "/api/keywords":
            self.keywords()
        else:
            super().do_GET()

    def keywords(self):
        params = parse_qs(urlsplit(self.path).query)
        if set(params) != {"year", "revision", "ids"} or any(len(v) != 1 for v in params.values()):
            self.send_error(400, "Invalid keyword request")
            return
        year, revision, ids = (params[k][0] for k in ["year", "revision", "ids"])
        ids = ids.split(",")
        if year not in {"2026", "2027"} or not re.fullmatch(r"[a-f0-9]{64}", revision) or len(ids) > 25 or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) for value in ids):
            self.send_error(400, "Invalid keyword request")
            return
        path = Path(self.directory) / "data/iclr" / year / revision / "_search.sqlite3"
        if not path.is_file():
            self.send_error(409, "Snapshot unavailable; reload the page")
            return
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
                rows = dict(database.execute("SELECT id, keywords FROM papers WHERE id IN (" + ",".join("?" for _ in ids) + ")", ids))
        except sqlite3.Error:
            self.send_error(503, "Keywords unavailable")
            return
        self.json_response({"revision": revision, "keywords": rows})

    def reviews(self):
        params = parse_qs(urlsplit(self.path).query)
        if set(params) != {"year", "revision", "paper_id"} or any(len(v) != 1 for v in params.values()):
            self.send_error(400, "Invalid review request")
            return
        year, revision, paper_id = (params[k][0] for k in ["year", "revision", "paper_id"])
        if year not in {"2026", "2027"} or not re.fullmatch(r"[a-f0-9]{64}", revision) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", paper_id):
            self.send_error(400, "Invalid review request")
            return
        database_path = Path(self.directory) / "data/iclr" / year / revision / "_search.sqlite3"
        if not database_path.is_file():
            self.send_error(409, "Snapshot unavailable; reload the page")
            return
        with closing(sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)) as database:
            exists = database.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if not exists:
            self.send_error(404, "Unknown paper in this year")
            return
        try:
            result, status = retrieve(int(year), paper_id)
        except (ValueError, KeyError, TypeError):
            result, status = {"status": "unavailable", "reviews": [], "message": "OpenReview 返回的数据暂时无法解析。"}, 502
        self.json_response(result, status)

    def json_response(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        use_gzip = self.accepts_gzip() and len(body) > 1024
        if use_gzip:
            body = gzip.compress(body, compresslevel=3)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Accept-Encoding")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def search(self):
        params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        required = {"conference", "year", "revision", "q"}
        valid = required <= set(params) <= required | {"keywords", "keyword_scope", "authors"} and all(len(v) == 1 for v in params.values())
        values = {k: v[0] for k, v in params.items()}
        scope = values.get("keyword_scope", "both")
        if not valid or scope not in {"both", "keywords", "title"} or values["conference"] != "iclr" or values["year"] not in {"2026", "2027"} or not re.fullmatch(r"[a-f0-9]{64}", values["revision"]) or any(len(values.get(key, "")) > 500 for key in ["q", "keywords", "authors"]):
            self.send_error(400, "Invalid search")
            return
        path = Path(self.directory) / "data/iclr" / values["year"] / values["revision"] / "_search.sqlite3"
        if not path.is_file():
            self.send_error(409, "Snapshot unavailable; reload the page")
            return
        keyword_query = values.get("keywords", "").strip()
        terms = list(dict.fromkeys(keyword_search_text(keyword_query).split()))
        author_query = values.get("authors", "").strip()
        author_terms = list(dict.fromkeys(keyword_search_text(author_query).split()))
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
                if author_query and not database.execute("SELECT 1 FROM authors LIMIT 1").fetchone():
                    self.json_response({"status": "unavailable", "message": "当前年份的快照未提供作者信息，暂不可按作者搜索。"}, 422)
                    return
                columns = {"both": ["keyword_search", "title_search"], "keywords": ["keyword_search"], "title": ["title_search"]}[scope]
                clause = " AND (" + " OR ".join(f"instr({column}, ?) > 0" for column in columns) + ")"
                sql = "SELECT id FROM papers WHERE instr(search, ?) > 0" + clause * len(terms)
                arguments = (values["q"].strip().lower(), *(term for term in terms for _ in columns))
                if author_terms:
                    sql += " AND EXISTS (SELECT 1 FROM authors WHERE authors.paper_id = papers.id" + " AND instr(authors.search, ?) > 0" * len(author_terms) + ")"
                    arguments += tuple(author_terms)
                ids = [] if (keyword_query and not terms) or (author_query and not author_terms) else [row[0] for row in database.execute(sql, arguments)]
        except sqlite3.Error:
            self.send_error(503, "Search unavailable")
            return
        self.json_response({"revision": values["revision"], "ids": ids})

    def send_head(self):
        path = Path(self.translate_path(self.path))
        if any(part.startswith("_") for part in path.relative_to(self.directory).parts) or path.suffix == ".sqlite3":
            self.send_error(404, "Not found")
            return None
        if path.is_dir():
            parts = urlsplit(self.path)
            if not parts.path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", parts._replace(path=parts.path + "/").geturl())
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            path = path / "index.html"
        if not path.is_file():
            self.send_error(404, "Not found")
            return None
        use_gzip = self.accepts_gzip() and path.with_name(path.name + ".gz").is_file()
        content = path.with_name(path.name + ".gz") if use_gzip else path
        stat = content.stat()
        etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
        immutable = re.search(r"[a-f0-9]{64}", str(path.relative_to(self.directory))) is not None
        self.send_response(304 if self.headers.get("If-None-Match") == etag else 200)
        self.send_header("ETag", etag)
        self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if immutable else "no-cache")
        if self.headers.get("If-None-Match") == etag:
            self.end_headers()
            return None
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Length", str(stat.st_size))
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        return content.open("rb")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    directory = ROOT / "web/dist"
    if not (directory / "index.html").is_file():
        parser.error("Build the website first: python scripts/build_iclr_web.py")
    server = ThreadingHTTPServer((args.host, args.port), partial(DashboardHandler, directory=str(directory)))
    print(f"PaperReading listening at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
