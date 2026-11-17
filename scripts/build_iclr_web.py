#!/usr/bin/env python3
"""Create or rebuild the local ICLR dashboard from the reviewed paper snapshot."""

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.paper_keywords import keyword_search_text, public_author_names
WEB = ROOT / "web"
PLUGIN = Path("/root/.codex/plugins/cache/openai-curated-remote/data-analytics/1.2.0")
ARTIFACT_IDS = {2026: "dashboard:paperreading-iclr-2026",
                2027: 'dashboard:f4d4d306-d1e0-4b7f-a31d-63c7e8c00469'}
REVIEW_FIELDS = ["rating", "confidence", "soundness", "presentation", "contribution", "informativeness"]
# Change this when immutable detail payloads change, even if the source snapshot does not.
WEB_SCHEMA = "abstract-search-v3"


def snapshot(year=2027, assets=None):
    directory = ROOT / f"iclr{year}"
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["conference"] != f"ICLR {year}":
        raise ValueError("Requested year does not match the dataset manifest")
    if hashlib.sha256((directory / "papers.jsonl").read_bytes()).hexdigest() != manifest["output_sha256"]["papers.jsonl"]:
        raise ValueError("Normalized paper snapshot checksum mismatch")
    scale = manifest.get("rating_scale", {"min": 0, "max": 10, "values": [0, 2, 4, 6, 8, 10]})
    bin_count = 2 * (scale["max"] - scale["min"])
    revision = hashlib.sha256(json.dumps({"papers": manifest["output_sha256"]["papers.jsonl"],
                                         "source": manifest["provenance"].get("sha256"),
                                         "schema": WEB_SCHEMA}, sort_keys=True).encode()).hexdigest()
    keywords, authors = {}, {}
    if manifest["provenance"]["source"] == "papercopilot":
        raw = (directory / "raw/papercopilot.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["provenance"]["sha256"]:
            raise ValueError("Keyword source does not match the pinned mirror")
        for row in json.loads(raw):
            paper_id = row.get("openreview_forum") or row["id"]
            keywords[paper_id] = row.get("keywords") or ""
            authors[paper_id] = public_author_names(row.get("author"))
        del raw
    rows, available_fields, chunks = [], set(), {}
    author_paper_count = 0
    database = None
    if assets is not None:
        assets.mkdir(parents=True, exist_ok=True)
        database_path = assets / "_search.sqlite3"
        database_path.unlink(missing_ok=True)
        database = sqlite3.connect(database_path)
        database.execute("CREATE TABLE papers (id TEXT PRIMARY KEY, search TEXT NOT NULL, keywords TEXT NOT NULL, keyword_search TEXT NOT NULL, title_search TEXT NOT NULL, abstract_search TEXT NOT NULL)")
        database.execute("CREATE TABLE authors (paper_id TEXT NOT NULL, name TEXT NOT NULL, search TEXT NOT NULL)")
        database.execute("CREATE INDEX authors_paper_id ON authors (paper_id)")
        database.execute("CREATE TABLE metadata (revision TEXT NOT NULL)")
        database.execute("INSERT INTO metadata VALUES (?)", (revision,))
    for line in (directory / "papers.jsonl").open():
        paper = json.loads(line)
        if paper.get("conference", manifest["conference"]) != manifest["conference"]:
            raise ValueError("Paper belongs to a different conference")
        scores = [v for v in paper["ratings"] if v is not None]
        if any(score not in scale["values"] for score in scores):
            raise ValueError(f"Invalid rating for {manifest['conference']}: {paper['id']}")
        row = {key: paper[key] for key in [
            "id", "title", "status", "rating_mean",
        ]}
        paper_keywords = paper.get("keywords", keywords.get(paper["id"], ""))
        paper_authors = public_author_names(paper.get("authors", authors.get(paper["id"], [])))
        author_paper_count += bool(paper_authors)
        row["rating_count"] = len(scores)
        if scores and year == 2027:
            mean = Fraction(sum(scores), len(scores))
            row["bin"] = f"{mean.numerator}/{mean.denominator}"
        else:
            row["bin"] = min(bin_count - 1, (2 * sum(scores) - 2 * scale["min"] * len(scores)) // len(scores)) if scores else None
        row["ratings_json"] = json.dumps(paper["ratings"], separators=(",", ":"))
        available_fields.update(key for r in paper["reviews"] for key in REVIEW_FIELDS if r.get(key) is not None)
        chunk = hashlib.sha256(paper["id"].encode()).hexdigest()[:2]
        row["detail_chunk"] = chunk
        detail = {key: paper[key] for key in ["id", "abstract", "paper_url", "pdf_url"]}
        detail["authors"] = paper_authors
        detail["reviews_json"] = json.dumps([
            {k: r.get(k) for k in ["reviewer", *REVIEW_FIELDS]}
            for r in paper["reviews"]
        ], separators=(",", ":"))
        if assets is not None:
            chunks.setdefault(chunk, {})[paper["id"]] = detail
            database.execute("INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?)",
                             (paper["id"], (paper["title"] + "\n" + (paper["abstract"] or "")).lower(), paper_keywords, keyword_search_text(paper_keywords), keyword_search_text(paper["title"]), keyword_search_text(paper["abstract"])))
            database.executemany("INSERT INTO authors VALUES (?, ?, ?)",
                                 [(paper["id"], name, keyword_search_text(name)) for name in paper_authors])
        rows.append(row)
    if database is not None:
        database.commit()
        database.close()
        for chunk, papers in chunks.items():
            write_json(assets / f"{chunk}.json", papers)
    mirror = manifest["provenance"]["source"] == "papercopilot"
    source_label = "Paper Copilot 公开镜像" if mirror else "OpenReview 官方公开数据"
    source_url = ("https://github.com/papercopilot/paperlists/commit/" + manifest["provenance"]["commit"]
                  if mirror else f"https://openreview.net/group?id=ICLR.cc/{year}/Conference")
    source = {
        "label": f"ICLR {year} 主会公开投稿 · {source_label}",
        "files": [f"iclr{year}/papers.jsonl", f"iclr{year}/manifest.json", *([f"iclr{year}/raw/papercopilot.json"] if mirror else [])],
        "executedAt": manifest["provenance"]["retrieved_at"],
        "links": [{"label": "原始来源", "url": source_url}],
        "caveats": manifest["limitations"],
        "metricDefinitions": [
            {"label": "平均分", "definition": "每篇论文所有非空审稿总评分的算术平均，使用该届原始尺度，不进行十分制换算。"},
            {"label": "精确均分", "definition": "以总评分之和/有效评分人数约分作为类别键，每个实际出现的均分对应一根柱；按数值排序、等距展示。不同人数的相同均分合并；不舍入、不按区间合并。"} if year == 2027 else
            {"label": "0.5 分区间", "definition": f"原始尺度 {scale['min']}–{scale['max']} 分；左闭右开，末档包含上限。按未四舍五入的均分分档；无评分单独统计。"},
            {"label": "论文数", "definition": "按 OpenReview forum ID 去重的主会投稿数量，包含撤稿和直接拒稿。"},
        ],
        "evidenceFlow": [
            {"title": "原始来源", "detail": source_label + "；" + source_url},
            {"title": "本地核对", "detail": "scripts/validate_iclr.py 核对原始镜像与论文导出；官方接口受限，镜像覆盖尚未经官方全量核对。"},
            {"title": "网站变换", "detail": "scripts/build_iclr_web.py 按指定年份加载主会记录，使用原始总评分求均值；2027 按精确均分分类，2026 按半分区间分类。模糊查询默认覆盖标题、关键词和摘要，多词须全部命中；使用 Unicode 归一化并忽略大小写和分隔符。作者仅使用会议公开名单，忽略 Anonymous 等占位值；不从预印本或标题推断作者。作者查询的所有词需命中同一作者；浏览器交集筛选后重新计数。"},
        ],
    }
    return {
        "title": "PaperReading", "surface": "dashboard", "status": "reviewed",
        "buildStatus": "complete", "generatedAt": manifest["generated_at"], "filters": [],
        "iclr": {"year": year, "conference": manifest["conference"], "ratingScale": scale,
                 "authorPaperCount": author_paper_count,
                 "reviewFields": [field for field in REVIEW_FIELDS if field in available_fields],
                 "retrievedAt": manifest["provenance"]["retrieved_at"], "source": source_label,
                 "officialCoverageVerified": manifest["provenance"]["official_coverage_verified"],
                 "revision": revision, "detailBase": f"/data/iclr/{year}/{revision}/"},
        "queries": {"papers": {"rows": rows, "source": source,
                                "payloadColumns": ["ratings_json"],
                                "methods": [{"language": "python", "code": f"python scripts/build_iclr_web.py --year {year}"}]}},
    }


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def compress(directory):
    for path in directory.rglob("*"):
        if path.suffix in (".json", ".html", ".js", ".css"):
            compressed = path.with_name(path.name + ".gz")
            if not compressed.exists() or compressed.stat().st_mtime_ns < path.stat().st_mtime_ns:
                temporary = compressed.with_suffix(".gz.tmp")
                temporary.write_bytes(gzip.compress(path.read_bytes(), compresslevel=6, mtime=0))
                temporary.replace(compressed)


def build_portal():
    from scripts.build_library import portal
    portal()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, choices=[2026, 2027], help="Rebuild one year; default: both years")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--plugin-root", type=Path, default=PLUGIN)
    args = parser.parse_args()
    node = shutil.which("node")
    if not node:
        parser.error("Node.js is required to build the dashboard")
    if not WEB.exists():
        parser.error("The existing Data app workspace is required")
    (ROOT / ".runtime").mkdir(exist_ok=True)
    from scripts.build_library import build_one
    for year in [args.year] if args.year else [2026, 2027]:
        if args.prepare_only:
            data = snapshot(year)
            data["id"] = ARTIFACT_IDS[year]
            data["exportPreferences"] = json.loads((WEB / "src/data.json").read_text()).get("exportPreferences", {"selected": None, "destinations": []})
            write_json(WEB / "src/data.json", data)
        else:
            build_one("iclr", year, builder=args.plugin_root / "output_formats/html/scripts/data-app.mjs")
    if not args.prepare_only:
        build_portal()
        print("PaperReading ready: http://localhost:8000/", flush=True)


if __name__ == "__main__":
    main()
