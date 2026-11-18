#!/usr/bin/env python3
"""Build the same Data dashboard for every registered venue/year, preserving ICLR."""

import argparse
import hashlib
import html
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.paper_venues import VENUES, YEARS
from scripts.paper_keywords import keyword_search_text
from scripts.build_iclr_web import compress, snapshot as iclr_snapshot, ARTIFACT_IDS
from scripts.author_tracking import build_tracking

WEB = ROOT / "web"
BUILDER = Path("/root/.codex/plugins/cache/openai-curated-remote/data-analytics/1.2.0/output_formats/html/scripts/data-app.mjs")
FIELDS = ["rating", "confidence", "soundness", "presentation", "contribution", "informativeness"]
ACCEPTED_STATUSES = {"accepted", "accept", "published", "poster", "oral", "spotlight", "highlight", "award candidate"}
NON_ACCEPTED_STATUSES = {"reject", "rejected", "desk reject", "withdraw", "withdrawn"}


def decision_counts(rows, statistics=None):
    statuses = [str(row.get("status") or "").strip().casefold() for row in rows]
    accepted = sum(status in ACCEPTED_STATUSES for status in statuses)
    counts = {"acceptedPaperCount": accepted,
              "pendingDecisionCount": sum(status not in ACCEPTED_STATUSES | NON_ACCEPTED_STATUSES for status in statuses),
              # Public rejects do not establish coverage of all submissions either.
              "totalPaperCount": None}
    if statistics is not None:
        admitted, submitted = statistics["accepted"], statistics["submitted"]
        if ((admitted is None and submitted is None)
                or (admitted is not None and (type(admitted) is not int or admitted < 0))
                or (submitted is not None and (type(submitted) is not int or submitted <= 0))
                or (admitted is not None and submitted is not None and admitted > submitted)
                or not statistics.get("sources")):
            raise ValueError("Submission statistics require valid counts and sources")
        counts.update(acceptedPaperCount=admitted, totalPaperCount=submitted,
                      localAcceptedPaperCount=accepted, statistics=statistics)
    return counts


def write_json(path, value):
    # Staging files may share an inode with the editable project. Replace the
    # staging directory entry rather than overwriting a hard-linked source.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def snapshot(venue, year, assets):
    folder = ROOT / "library" / venue / str(year)
    manifest = json.loads((folder / "manifest.json").read_text())
    path = folder / "papers.jsonl"
    if manifest["status"] == "available":
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
            raise ValueError("Normalized paper snapshot checksum mismatch")
        papers = [json.loads(line) for line in path.open()]
    else:
        papers = []
    revision = hashlib.sha256(json.dumps({"manifest": manifest, "schema": "library-v2"}, sort_keys=True).encode()).hexdigest()
    assets.mkdir(parents=True)
    db = sqlite3.connect(assets / "_search.sqlite3")
    db.execute("CREATE TABLE papers (id TEXT PRIMARY KEY, search TEXT NOT NULL, keywords TEXT NOT NULL, keyword_search TEXT NOT NULL, title_search TEXT NOT NULL, abstract_search TEXT NOT NULL)")
    db.execute("CREATE TABLE authors (paper_id TEXT NOT NULL, name TEXT NOT NULL, search TEXT NOT NULL)")
    db.execute("CREATE INDEX authors_paper_id ON authors (paper_id)")
    db.execute("CREATE TABLE metadata (revision TEXT NOT NULL)")
    db.execute("INSERT INTO metadata VALUES (?)", (revision,))
    rows, chunks, values = [], {}, []
    for paper in papers:
        ratings = [n for n in paper["ratings"] if n is not None]
        if any(not isinstance(n, (int, float)) for n in ratings):
            raise ValueError("Non-numeric review rating")
        values.extend(ratings)
        mean = sum((Fraction(str(n)) for n in ratings), Fraction()) / len(ratings) if ratings else None
        chunk = hashlib.sha256(paper["id"].encode()).hexdigest()[:1]
        rows.append({"id": paper["id"], "title": paper["title"], "status": paper["status"],
                     "rating_mean": float(mean) if mean is not None else None, "rating_count": len(ratings),
                     "bin": f"{mean.numerator}/{mean.denominator}" if mean is not None else None,
                     "ratings_json": json.dumps(paper["ratings"]), "detail_chunk": chunk})
        detail = {key: paper[key] for key in ["id", "abstract", "paper_url", "pdf_url", "authors"]}
        detail["reviews_json"] = json.dumps(paper["reviews"], ensure_ascii=False)
        chunks.setdefault(chunk, {})[paper["id"]] = detail
        db.execute("INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?)", (paper["id"], (paper["title"] + "\n" + paper["abstract"]).lower(),
                   paper["keywords"], keyword_search_text(paper["keywords"]), keyword_search_text(paper["title"]), keyword_search_text(paper["abstract"])))
        db.executemany("INSERT INTO authors VALUES (?, ?, ?)", [(paper["id"], name, keyword_search_text(name)) for name in paper["authors"]])
    db.commit();db.close()
    for chunk, data in chunks.items():
        write_json(assets / f"{chunk}.json", data)
    # Observed values are not asserted to be the complete official scale.
    scale = {"min": min(values) if values else 0, "max": max(values) if values else 10}
    label, kind, name, homepage = VENUES[venue]
    source_label = manifest.get("source_label", "Crossref 出版机构登记元数据" if kind == "journal" or papers else "公开来源检查")
    coverage = (f"已收录 {len(papers):,} 篇；摘要 {manifest['abstract_count']:,} 篇、公开作者 {manifest['author_count']:,} 篇、Keywords {manifest['keyword_count']:,} 篇。"
                if papers else manifest["message"])
    coverage += " 审稿评分及正文只在来源提供时展示；不以录用结果推测评分。"
    if manifest.get("coverage_note"):
        coverage += " " + manifest["coverage_note"]
    if kind == "journal":
        coverage += " 年份使用 Crossref 的 published/issued 年；Early Access 与卷期年份可能不同。"
    if values:
        coverage += " 评分范围为当前快照中的观测值，不代表完整官方量表。"
    write_json(assets / "manifest.json", manifest)
    return {"id": f"dashboard:paperreading-{venue}-{year}", "title": "PaperReading", "surface": "dashboard",
            "status": "reviewed", "buildStatus": "complete", "generatedAt": manifest["retrieved_at"], "filters": [],
            "iclr": {"venue": venue, "year": year, "label": label, "kind": kind, "conference": f"{label} {year}",
                     "homepage": homepage, "datasetStatus": manifest["status"], "coverageMessage": coverage,
                     "ratingScale": scale, "exactScores": True, "authorPaperCount": manifest["author_count"],
                     "reviewFields": [key for key in FIELDS if any(r.get(key) is not None for p in papers for r in p["reviews"])],
                     "retrievedAt": manifest["retrieved_at"], "source": source_label,
                     "officialCoverageVerified": manifest.get("official_coverage_verified", False),
                     "revision": revision, "detailBase": f"/data/{venue}/{year}/{revision}/"},
            "queries": {"papers": {"rows": rows, "payloadColumns": ["ratings_json"],
                "source": {"label": f"{label} {year} · {source_label}",
                           "files": [str(path.relative_to(ROOT)), str((folder / 'manifest.json').relative_to(ROOT))],
                           "executedAt": manifest["retrieved_at"], "links": [{"label": "原始来源", "url": homepage}],
                           "caveats": [coverage, "镜像和索引覆盖未与官方全量逐条核对；无记录不等于没有论文。"],
                           "metricDefinitions": [{"label": "论文数", "definition": "按来源记录 ID 或 DOI 去重的本地公开记录数量。"},
                                                 {"label": "平均分", "definition": "来源逐审稿人有效评分的算术平均；不补零，不从状态推断。"}]},
                "methods": [{"language": "python", "code": f"python scripts/sync_library.py --venues {venue} --years {year}\npython scripts/build_library.py --venues {venue} --years {year}"}]}}}


def build_one(venue, year, project=None, builder=BUILDER):
    dist = WEB / "dist"
    target = dist / venue / str(year)
    digest = hashlib.sha256()
    inputs = [*sorted((WEB / "src/content").rglob("*")), Path(__file__),
              ROOT / "scripts/build_iclr_web.py", ROOT / "scripts/paper_keywords.py", ROOT / "scripts/paper_venues.py"]
    inputs.append(ROOT / f"iclr{year}/manifest.json" if venue == "iclr" and year in (2026, 2027) else ROOT / "library" / venue / str(year) / "manifest.json")
    for path in inputs:
        if path.is_file():
            digest.update(str(path.relative_to(ROOT)).encode());digest.update(path.read_bytes())
    # A manifest match cannot conceal a missing or modified normalized export.
    source = ROOT / (f"iclr{year}" if venue == "iclr" and year in (2026, 2027) else f"library/{venue}/{year}")
    manifest = json.loads((source / "manifest.json").read_text())
    expected = manifest.get("sha256") or manifest.get("output_sha256", {}).get("papers.jsonl")
    if expected and hashlib.sha256((source / "papers.jsonl").read_bytes()).hexdigest() != expected:
        raise ValueError("Normalized paper snapshot checksum mismatch")
    fingerprint = digest.hexdigest()
    stamp = target / "authored-build.json"
    if stamp.exists() and json.loads(stamp.read_text()).get("inputSha256") == fingerprint and (target / "index.html").exists():
        print(f"Unchanged {venue} {year}", flush=True)
        return
    with tempfile.TemporaryDirectory(prefix="library-build-", dir=ROOT / ".runtime") as temp:
        temporary = Path(temp)
        assets = temporary / "assets"
        if venue == "iclr" and year in (2026, 2027):
            data = iclr_snapshot(year, assets)
            data["id"] = ARTIFACT_IDS[year]
            data["iclr"].update(venue="iclr", label="ICLR", kind="conference")
        else:
            data = snapshot(venue, year, assets)
        previous = json.loads((WEB / "src/data.json").read_text())
        if "exportPreferences" in previous:
            data["exportPreferences"] = previous["exportPreferences"]
        if project is None:
            project = temporary / "project"
            shutil.copytree(WEB, project, copy_function=os.link, ignore=shutil.ignore_patterns("dist", "node_modules", ".data-app-offline", ".git"))
        write_json(project / "src/data.json", data)
        subprocess.run(["node", str(builder), "build", "--project-dir", str(project), "--separate-data"], check=True, stdout=subprocess.DEVNULL)
        if assets:
            destination = dist / "data" / venue / str(year) / data["iclr"]["revision"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                assets.rename(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        old = temporary / "old"
        try:
            if target.exists():
                target.rename(old)
            (project / "dist").rename(target)
        except BaseException:
            if old.exists():
                if target.exists():
                    shutil.rmtree(target)
                old.rename(target)
            raise
        write_json(target / "authored-build.json", {"inputSha256": fingerprint})
        compress(dist / venue / str(year))
        if assets:
            compress(dist / "data" / venue / str(year) / data["iclr"]["revision"])
    print(f"Built {venue} {year}", flush=True)


def portal():
    entries, sections, datasets = [], [], []
    statistics = json.loads((ROOT / "library/conference-statistics.json").read_text())
    for venue, (label, kind, name, homepage) in VENUES.items():
        cards = []
        for year in reversed(YEARS):
            folder = WEB / "dist" / venue / str(year)
            if not folder.exists():
                continue
            build = json.loads((folder / "data-app-build.json").read_text())
            data = json.loads((folder / build["snapshot"]["path"]).read_text())
            meta, rows = data["iclr"], data["queries"]["papers"]["rows"]
            datasets.append(({**meta, "venue": venue, "year": year}, rows))
            status = meta.get("datasetStatus", "available")
            entry = {"conference": label, "venue": venue, "kind": kind, "year": year, "paperCount": len(rows),
                     "status": status, "reviewCount": sum(r["rating_count"] for r in rows), "url": f"/{venue}/{year}/"}
            entry.update(decision_counts(rows, statistics.get(f"{venue}/{year}")))
            entries.append(entry)
            text = f'{len(rows):,}<span> 篇</span>' if rows else {"not_held": "本年不举办", "unavailable": "暂未获取"}.get(status, "暂未获取")
            info = f'{entry["reviewCount"]:,} 条公开评分' if entry["reviewCount"] else "来源未提供公开评分"
            verified = entry.get("statistics")
            if kind != "journal" and (rows or verified):
                admitted = entry["acceptedPaperCount"]
                accepted = f"{admitted:,}" if admitted is not None else "—"
                if not verified and not admitted and entry["pendingDecisionCount"]:
                    accepted = "待定"
                total = f'{entry["totalPaperCount"]:,}' if entry["totalPaperCount"] is not None else "—"
                text = f'<span>{"核实" if verified else "本地"}</span> {accepted} / {total}'
                scope = (verified["scope"]
                         if verified else "录取数为本地记录统计；总投稿量尚未核实")
                if verified and admitted is not None and entry["totalPaperCount"] is not None:
                    scope += f'；录取率 {100 * admitted / entry["totalPaperCount"]:.2f}%'
                info = f'录取 {accepted} / 总投稿 {total}；{scope}；{info}'
            cards.append(f'<a class="year-card" data-year="{year}" data-status="{status}" href="/{venue}/{year}/" title="{html.escape(info)}" aria-label="{html.escape(label)} {year}，{len(rows):,} 条已获取记录；{html.escape(info)}"><span class="year-heading">{year}</span><span class="year-count">{text}</span><span class="year-arrow" aria-hidden="true">↗</span></a>')
        type_label = {"conference": "会议", "journal": "期刊", "workshop": "Workshop"}[kind]
        column_label = "收录论文" if kind == "journal" else "录取 / 总投稿"
        sections.append(f'<article class="conference" data-kind="{kind}"><div class="conference-header"><div><span class="conference-tag">{type_label}</span><h3>{html.escape(label)}</h3></div><a class="availability" href="{html.escape(homepage)}" target="_blank" rel="noopener noreferrer" aria-label="{html.escape(label)} 官方网站">官网 ↗</a></div><p class="venue-name">{html.escape(name)}</p><div class="year-columns" aria-hidden="true"><span>年份</span><span>{column_label}</span></div><div class="year-grid">{"".join(cards)}</div></article>')
    template = (WEB / "portal/index.html").read_text()
    template = template.replace("__VENUE_COUNT__", str(len(VENUES)))
    for kind in ("conference", "journal", "workshop"):
        template = template.replace(f"__{kind.upper()}_COUNT__", str(sum(v[1] == kind for v in VENUES.values())))
    source_notes = []
    for statistic in statistics.values():
        links = "；".join(f'<a href="{html.escape(source["url"])}" target="_blank" rel="noopener noreferrer">{html.escape(source["label"])} ↗</a>'
                         for source in statistic["sources"])
        source_notes.append(f'<p>{html.escape(statistic["scope"])}。核实日期：{html.escape(statistic["verified_at"])}。来源：{links}</p>')
    (WEB / "dist/index.html").write_text(template.replace("__VENUE_CARDS__", "\n".join(sections))
                                      .replace("__STATISTICS_SOURCES__", "\n".join(source_notes)))
    shutil.copy2(WEB / "portal/library.css", WEB / "dist/library.css")
    for asset in ["portal.js", "authors.js", "reading-state.mjs"]:
        shutil.copy2(WEB / "portal" / asset, WEB / "dist" / asset)
    author_assets = WEB / "dist/author-assets"
    author_assets.mkdir(exist_ok=True)
    for asset in ["katex.mjs", "katex.css", "LICENSE"]:
        shutil.copy2(WEB / "src/content/assets/katex" / asset, author_assets / asset)
    shutil.copy2(WEB / "src/content/dashboard/abstract-math.mjs", author_assets / "abstract-math.mjs")
    (WEB / "dist/authors").mkdir(exist_ok=True)
    shutil.copy2(WEB / "portal/authors.html", WEB / "dist/authors/index.html")
    write_json(WEB / "dist/catalog.json", {"title": "PaperReading", "datasets": entries})
    build_tracking(WEB / "dist", datasets)
    compress(WEB / "dist")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venues", nargs="+", choices=list(VENUES), default=list(VENUES))
    parser.add_argument("--years", nargs="+", type=int, choices=YEARS, default=YEARS)
    parser.add_argument("--portal-only", action="store_true")
    args = parser.parse_args()
    (ROOT / ".runtime").mkdir(exist_ok=True)
    if not args.portal_only:
        with tempfile.TemporaryDirectory(prefix="library-compiler-", dir=ROOT / ".runtime") as directory:
            project = Path(directory) / "project"
            shutil.copytree(WEB, project, copy_function=os.link, ignore=shutil.ignore_patterns("dist", "node_modules", ".data-app-offline", ".git"))
            for venue in args.venues:
                for year in args.years:
                    build_one(venue, year, project)
    portal()


if __name__ == "__main__":
    main()
