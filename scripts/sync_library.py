#!/usr/bin/env python3
"""Cache public metadata and export inspectable, source-attributed venue/year datasets."""

import argparse
import concurrent.futures
import hashlib
import html
import json
import re
import sys
import time
import threading
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.paper_venues import ISSNS, VENUES, YEARS, not_held
from scripts.paper_keywords import public_author_names
from scripts.sync_iclr import numeric

DATA = ROOT / "library"
_crossref_lock = threading.Lock()
_crossref_next = 0


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def clean(text):
    return html.unescape(re.sub(r"<[^>]*>", "", str(text or ""))).strip()


class Cache:
    def __init__(self, directory, refresh=False):
        self.directory = directory
        self.refresh = refresh
        directory.mkdir(parents=True, exist_ok=True)
        self.sources = []
        self.attempted_sources = []

    def get(self, url):
        self.attempted_sources.append(url)
        key = hashlib.sha256(url.encode()).hexdigest()
        path = self.directory / key
        meta = path.with_suffix(".json")
        if not self.refresh and path.exists() and meta.exists():
            content = path.read_bytes()
            record = json.loads(meta.read_text())
            if hashlib.sha256(content).hexdigest() != record["sha256"]:
                raise ValueError("Raw cache checksum mismatch")
        else:
            for attempt in range(3):
                try:
                    if url.startswith("https://api.crossref.org/"):
                        global _crossref_next
                        with _crossref_lock:
                            time.sleep(max(0, _crossref_next - time.monotonic()))
                            _crossref_next = time.monotonic() + 1.5
                    opener = build_opener(ProxyHandler({}))
                    with opener.open(Request(url, headers={"User-Agent": "PaperReading/1.0 (public research metadata)"}), timeout=40) as response:
                        content = response.read()
                    break
                except Exception as error:
                    if isinstance(error, HTTPError) and error.code in (400, 401, 403, 404):
                        raise
                    if attempt == 2:
                        raise
                    delay = error.headers.get("Retry-After", "") if isinstance(error, HTTPError) else ""
                    time.sleep(min(45, int(delay) if delay.isdigit() else 10 * (attempt + 1) if isinstance(error, HTTPError) and error.code == 429 else 2 ** attempt))
            record = {"url": url, "retrieved_at": now(), "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(content)
                    stream.close()
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            write_json(meta, record)
        self.sources.append(record)
        return content

    def json(self, url):
        return json.loads(self.get(url))


def base(venue, year, identity, title, url):
    return {"id": identity, "title": clean(title), "abstract": "", "authors": [], "keywords": "",
            "paper_url": url, "pdf_url": "", "status": "Published", "ratings": [], "rating_mean": None,
            "reviews": [], "venue": venue, "year": year}


def mirror(cache, venue, year, tree):
    slug = "nips" if venue == "neurips" else venue
    path = f"{slug}/{slug}{year}.json"
    if path not in tree["paths"]:
        return []
    url = f'https://raw.githubusercontent.com/papercopilot/paperlists/{tree["sha"]}/{path}'
    content = cache.get(url)
    if content.startswith(b"version https://git-lfs"):
        sha = re.search(rb"oid sha256:([a-f0-9]{64})", content)[1].decode()
        content = cache.get(f'https://media.githubusercontent.com/media/papercopilot/paperlists/{tree["sha"]}/{path}')
        if hashlib.sha256(content).hexdigest() != sha:
            raise ValueError("Mirror Git LFS checksum mismatch")
    rows = []
    for raw in json.loads(content):
        if raw.get("track", "main") not in {"main", "Main"}:
            continue
        if venue == "siggraph" and raw.get("status") != "Technical Paper":
            continue
        forum = raw.get("openreview_forum") or raw.get("id", "")
        review_url = raw.get("openreview") or (f"https://openreview.net/forum?id={forum}" if venue in {"iclr", "icml", "neurips"} else "")
        paper_url = raw.get("oa") or raw.get("site") or review_url
        if venue == "siggraph":
            paper_url = raw.get("url_paper") or paper_url
        if not paper_url:
            continue
        # An OpenReview submission link alone does not establish acceptance.
        # CVF's edition-specific proceedings URLs do establish publication.
        published = paper_url.startswith(f"https://openaccess.thecvf.com/content/{venue.upper()}{year}/html/")
        paper = base(venue, year, re.sub(r"[^A-Za-z0-9_-]", "", str(forum)) or hashlib.sha256(paper_url.encode()).hexdigest()[:24], raw["title"], paper_url)
        paper.update(abstract=raw.get("abstract") or "", authors=public_author_names(raw.get("author")),
                     keywords=raw.get("keywords") or "", pdf_url=raw.get("pdf") or (f"https://openreview.net/pdf?id={forum}" if review_url else ""),
                     status=raw.get("status") or ("Published" if published else "Unknown"), source="Paper Copilot 公开镜像（未核实官方全量覆盖）")
        if venue == "siggraph":
            paper.update(status="Accepted", program_type=raw["status"])
        aliases = str(raw.get("reviewers") or "").split(";") if raw.get("reviewers") else []
        ratings = str(raw["rating"] if raw.get("rating") is not None else "").split(";")
        # A mirror's aggregate rating is never a substitute for individual reviews.
        if aliases and len(aliases) == len(ratings):
            for i, alias in enumerate(aliases):
                review = {"reviewer": alias}
                for field in ["rating", "confidence", "soundness", "presentation", "contribution", "informativeness"]:
                    values = str(raw[field] if raw.get(field) is not None else "").split(";")
                    if len(values) == len(aliases):
                        review[field] = numeric(values[i])
                paper["reviews"].append(review)
            paper["ratings"] = [r.get("rating") for r in paper["reviews"]]
        valid = [n for n in paper["ratings"] if n is not None]
        paper["rating_mean"] = sum(valid) / len(valid) if valid else None
        rows.append(paper)
    return rows


def siggraph_program(cache, year):
    """Read Technical Papers only; invited TOG presentations/posters are separate."""
    url = f"https://s{year}.conference-schedule.org/"
    page = cache.get(url).decode()
    sources = re.findall(rf'source="(/wp-content/linklings_snippets/wp_program_view_all_{year}-[^"]+)"', page)
    if not sources:
        raise ValueError("No public SIGGRAPH daily program found")
    papers = {}
    for source in dict.fromkeys(sources):
        schedule = cache.get(urljoin(url, html.unescape(source))).decode()
        for identity, block in re.findall(r'<tr\b[^>]*ssid="(papers_\d+)"[^>]*>(.*?)</tr>', schedule, re.S):
            title = re.search(r'<a[^>]*data-link-type="[^"]+\.presentation"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
            if not title or identity in papers:
                continue
            paper = base("siggraph", year, identity, title[2], urljoin(url, html.unescape(title[1])))
            paper.update(status="Accepted", source="SIGGRAPH 官方 Technical Papers 日程",
                         authors=public_author_names([clean(name) for name in re.findall(
                             r'<div class="presenter-name"><a[^>]*>(.*?)</a>', block, re.S)]))
            papers[identity] = paper
    if not papers:
        raise ValueError("No SIGGRAPH Technical Papers parsed")

    def detail(paper):
        try:
            page = cache.get(paper["paper_url"]).decode()
            description = re.search(r'<span class="abstract">(.*?)</span></div>', page, re.S)
            paper["abstract"] = clean(description[1]) if description else ""
            paper["abstract_source"] = "官方日程 Description（可能是短简介，并非出版全文摘要）"
            keywords = re.search(r'<div class="keyword tag-group-list[^"\n]*">(.*?)(?=<div class="[^"\n]*tag-group-list|</div></div></span>)', page, re.S)
            paper["keywords"] = ";".join(clean(v) for v in re.findall(
                r'<div class="program-track [^"]+">(.*?)</div>', keywords[1], re.S)) if keywords else ""
            doi = re.search(r'href="https://doi.org/(10\.[^"]+)"', page)
            if doi:
                paper.update(program_url=paper["paper_url"], doi=html.unescape(doi[1]).lower(),
                             paper_url="https://doi.org/" + html.unescape(doi[1]))
        except Exception as error:
            paper["abstract_error"] = type(error).__name__
        return paper

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows = []
        for i, paper in enumerate(pool.map(detail, papers.values()), 1):
            rows.append(paper)
            if i % 100 == 0:
                print(f"siggraph {year}: official descriptions {i}/{len(papers)}", flush=True)
    return rows


def cvf(cache, venue, year):
    if venue in {"ntire", "aim"}:
        host = "ICCV" if venue == "aim" and year % 2 else "CVPR"
        url = f'https://openaccess.thecvf.com/{host}{year}_workshops/{venue.upper()}'
    else:
        url = f"https://openaccess.thecvf.com/{venue.upper()}{year}?day=all"
    text = cache.get(url).decode()
    if not re.search(r'class=["\']ptitle', text):
        raise ValueError("Official proceedings not available at this endpoint")
    rows = []
    for block in re.split(r'<dt class=["\']ptitle["\']>', text)[1:]:
        link = re.search(r'<a href="([^"]+)">(.*?)</a>', block, re.S)
        if not link:
            continue
        page = urljoin(url, link[1])
        paper = base(venue, year, hashlib.sha256(page.encode()).hexdigest()[:24], link[2], page)
        paper["authors"] = [html.unescape(v) for v in re.findall(r'name="query_author" value="([^"]+)"', block)]
        pdf = re.search(r'<a href="([^"]+\.pdf)">pdf</a>', block)
        paper["pdf_url"] = urljoin(url, pdf[1]) if pdf else ""
        paper["source"] = "CVF 官方公开论文集"
        rows.append(paper)

    def abstract(paper):
        try:
            page = cache.get(paper["paper_url"]).decode()
            found = re.search(r'<div id="abstract"[^>]*>(.*?)</div>', page, re.S)
            paper["abstract"] = clean(found[1]) if found else ""
        except Exception as error:
            paper["abstract_error"] = type(error).__name__
        return paper

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        result = []
        for i, paper in enumerate(pool.map(abstract, rows), 1):
            result.append(paper)
            if i % 250 == 0:
                print(f"{venue} {year}: abstracts {i}/{len(rows)}", flush=True)
    return result


def crossref_paper(raw, venue, year):
    doi = raw.get("DOI", "").lower()
    paper = base(venue, year, hashlib.sha256(doi.encode()).hexdigest()[:24], (raw.get("title") or [""])[0], "https://doi.org/" + doi)
    paper.update(doi=doi, abstract=clean(raw.get("abstract")),
                 authors=[" ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name", "") for a in raw.get("author", [])],
                 source="Crossref 出版机构登记元数据")
    paper["authors"] = public_author_names(paper["authors"])
    pdf = next((v["URL"] for v in raw.get("link", []) if v.get("content-type") == "application/pdf" and v.get("URL", "").startswith("https://")), "")
    paper["pdf_url"] = pdf
    paper["publication_date"] = raw.get("published", raw.get("issued", {})).get("date-parts", [[]])[0]
    return paper


def journal(cache, venue, year):
    cursor = "*"
    result = {}
    expected = None
    while True:
        url = f"https://api.crossref.org/journals/{ISSNS[venue]}/works?" + urlencode({
            "filter": f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31,type:journal-article",
            "rows": 1000, "cursor": cursor})
        page = cache.json(url)["message"]
        expected = page["total-results"] if expected is None else expected
        for row in page["items"]:
            # Crossref's 'pub-date' range matches any publication date; use the
            # canonical published/issued year to avoid duplicate year assignments.
            date = row.get("published", row.get("issued", {})).get("date-parts", [[]])[0]
            if date and date[0] == year and row.get("DOI") and row.get("title"):
                result[row["DOI"].lower()] = crossref_paper(row, venue, year)
        if len(page["items"]) < 1000:
            break
        next_cursor = page.get("next-cursor")
        if not next_cursor or next_cursor == cursor:
            raise ValueError("Crossref pagination did not advance")
        cursor = next_cursor
        time.sleep(.3)
    # OpenAlex contributes abstracts only on exact DOI joins. Formal author names
    # remain the publisher-deposited Crossref names, never preprint guesses.
    page_number = 1
    enrichment_error = None
    try:
        while result and any(not paper["abstract"] for paper in result.values()):
            params = {"filter": f"primary_location.source.issn:{ISSNS[venue]},publication_year:{year}",
                      "per-page": 200, "page": page_number, "select": "doi,abstract_inverted_index,primary_location"}
            page = cache.json("https://api.openalex.org/works?" + urlencode(params))
            for raw in page["results"]:
                doi = (raw.get("doi") or "").removeprefix("https://doi.org/").lower()
                if doi not in result:
                    continue
                paper = result[doi]
                index = raw.get("abstract_inverted_index") or {}
                if not paper["abstract"] and index:
                    words = sorted((pos, word) for word, positions in index.items() for pos in positions)
                    paper["abstract"] = " ".join(word for _, word in words)
                    paper["abstract_source"] = "OpenAlex，按已发表 DOI 精确关联"
                location = raw.get("primary_location") or {}
                if not paper["pdf_url"] and location.get("pdf_url"):
                    paper["pdf_url"] = location["pdf_url"]
            if len(page["results"]) < 200:
                break
            page_number += 1
            time.sleep(.15)
    except Exception as error:
        enrichment_error = str(error)
    return list(result.values()), {"api_reported_count": expected, "abstract_enrichment_error": enrichment_error,
                                  "source_label": "Crossref 出版机构元数据；OpenAlex 摘要（按已发表 DOI 精确关联）",
                                  "abstract_enriched_count": sum(bool(p.get("abstract_source")) for p in result.values())}


def matches_container(container, venue):
    if re.search(r"workshop|companion|abstracts|tutorial", container, re.I):
        return False
    if venue == "acmmm":
        return bool(re.search(r"\bACM (?:International Conference on Multimedia|Multimedia)(?:\s+\d{4})?\s*$", container, re.I))
    if venue in {"eccv", "accv"}:
        return bool(re.search(r"\b" + venue + r"\s+20\d\d\b", container, re.I))
    normalized = re.sub(r"[^a-z0-9]", "", container.lower())
    full = re.sub(r"[^a-z0-9]", "", VENUES[venue][2].lower())
    return full in normalized or bool(re.search(r"\b" + re.escape(VENUES[venue][0]) + r"\b", container, re.I))


def conference_crossref(cache, venue, year):
    """Search candidate proceedings, then reject every unrelated container/year."""
    label, _, title, _ = VENUES[venue]
    result = {}
    containers = set()
    for offset in range(0, 10000, 1000):
        url = "https://api.crossref.org/works?" + urlencode({"query.container-title": f"{year} {title}",
            "filter": "from-pub-date:2025-01-01,until-pub-date:2027-12-31,type:proceedings-article",
            "rows": 1000, "offset": offset})
        page = cache.json(url)["message"]
        matched = 0
        for raw in page["items"]:
            container = " ".join(raw.get("container-title", []))
            if not matches_container(container, venue):
                continue
            date = raw.get("published", raw.get("issued", {})).get("date-parts", [[]])[0]
            edition = re.search(r"\b(20\d\d)\b", container)
            event_date = raw.get("event", {}).get("start", {}).get("date-parts", [[]])[0]
            edition_year = int(edition[1]) if edition else (event_date or date or [None])[0]
            if edition_year != year or not raw.get("DOI") or not raw.get("title"):
                continue
            containers.add(container);matched += 1
            result[raw["DOI"].lower()] = crossref_paper(raw, venue, year)
        if not matched or len(page["items"]) < 1000:
            break
    return list(result.values()), {"matched_containers": sorted(containers), "official_coverage_verified": False}


def ijcai(cache, year):
    url = f"https://www.ijcai.org/proceedings/{year}/"
    text = cache.get(url).decode()
    rows = []
    for match in re.finditer(r'<div class="paper_wrapper[^\"]*"[^>]*>(.*?)(?=<div class="paper_wrapper|$)', text, re.S):
        block = match[1]
        title = re.search(r'class="title"[^>]*>(.*?)</(?:a|div)>', block, re.S)
        link = re.search(r'href="([^\"]+)"[^>]*>\s*(?:Details|Abstract)', block, re.I)
        if not title or not link:
            continue
        page = urljoin(url, link[1])
        paper = base("ijcai", year, hashlib.sha256(page.encode()).hexdigest()[:24], title[1], page)
        authors = re.search(r'class="authors"[^>]*>(.*?)</div>', block, re.S)
        paper["authors"] = [a.strip() for a in clean(authors[1]).split(",")] if authors else []
        pdf = re.search(r'href="([^\"]+\.pdf)"', block, re.I)
        paper["pdf_url"] = urljoin(url, pdf[1]) if pdf else ""
        paper["source"] = "IJCAI 官方论文集"
        rows.append(paper)
    if not rows:
        raise ValueError("No public IJCAI proceedings parsed")
    def detail(paper):
        try:
            raw = cache.json(paper["paper_url"] + ".json")
            paper["abstract"] = clean(raw.get("abstract"))
            paper["keywords"] = ";".join(raw.get("keywords") or []) if isinstance(raw.get("keywords"), list) else raw.get("keywords") or ""
        except Exception as error:
            paper["abstract_error"] = type(error).__name__
        return paper
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(detail, rows))


def official_list(cache, venue, year):
    """Parse edition-specific official lists; no author/abstract inference."""
    if venue == "eccv":
        url = f"https://eccv.ecva.net/Conferences/{year}/AcceptedPapers"
    elif venue == "accv":
        url = f"https://accv{year}.org/conference-program/"
    else:
        url = f"https://bmvc{year}.bmva.org/" + ("proceedings/conference-proceedings/" if year == 2025 else "programme/accepted_papers/")
    text = cache.get(url).decode()
    rows = []
    if venue == "eccv":
        for block in re.findall(r'<tr(?:\s[^>]*)?>(.*?)</tr>', text, re.S):
            link = re.search(r'<a href="(/virtual/20\d\d/poster/\d+)"[^>]*>(.*?)</a>', block, re.S)
            if not link:
                continue
            page = urljoin(url, link[1])
            paper = base(venue, year, hashlib.sha256(page.encode()).hexdigest()[:24], link[2], page)
            authors = re.search(r'<i>(.*?)</i>', block, re.S)
            paper["authors"] = [a.strip() for a in clean(authors[1]).split("⋅")] if authors else []
            rows.append(paper)
    elif venue == "accv":
        for block in re.findall(r'<li class="paper"[^>]*>(.*?)</li>', text, re.S):
            link = re.search(r'<a href="(https://openreview.net/forum\?id=([A-Za-z0-9_-]+))"[^>]*>(.*?)</a>', block, re.S)
            if not link:
                continue
            paper = base(venue, year, link[2], link[3], html.unescape(link[1]))
            authors = re.search(r'class="paper-authors"[^>]*>(.*?)</div>', block, re.S)
            paper["authors"] = public_author_names(clean(authors[1])) if authors else []
            paper["pdf_url"] = f"https://openreview.net/pdf?id={link[2]}"
            rows.append(paper)
    else:
        for block in re.findall(r'<tr[^>]*>(.*?)</tr>', text, re.S):
            if year == 2025:
                link = re.search(r'<a href="(/proceedings/(\d+)/)"[^>]*>(.*?)</a>', block, re.S)
                if not link:
                    continue
                paper = base(venue, year, f"bmvc-{year}-{link[2]}", link[3], urljoin(url, link[1]))
                pdf = re.search(r'href="([^\"]+/paper.pdf)"', block)
                paper["pdf_url"] = pdf[1] if pdf else ""
                authors = re.search(r'</strong><br\s*/?>(.*?)<br', block, re.S)
                if authors:
                    paper["authors"] = [re.sub(r"\s*\(.*", "", a).strip() for a in clean(authors[1]).split(";")]
            else:
                cells = re.findall(r'<td[^>]*>(.*?)</td>', block, re.S)
                if len(cells) != 2 or not clean(cells[0]).isdigit():
                    continue
                paper = base(venue, year, f"bmvc-{year}-{clean(cells[0])}", cells[1], url)
            rows.append(paper)
    if not rows:
        raise ValueError("No papers parsed from official edition list")

    def detail(paper):
        paper.update(status="Accepted", source="会议官方录用名单／论文集")
        if venue == "accv" or (venue == "bmvc" and year != 2025):
            return paper
        try:
            page = cache.get(paper["paper_url"]).decode()
            abstract = re.search(r'class="abstract-text-inner"[^>]*>(.*?)</div>', page, re.S) if venue == "eccv" else re.search(r'<h[1-6][^>]*>\s*Abstract\s*</h[1-6]>\s*(.*?)(?:</p>|<h[1-6])', page, re.S | re.I)
            paper["abstract"] = clean(abstract[1]) if abstract else ""
            if venue == "eccv":
                pdf = re.search(r'href="(https://media.eventhosts.cc/Conferences/ECCV\d+/pdfs/[^\"]+\.pdf)"', page)
                paper["pdf_url"] = pdf[1] if pdf else ""
        except Exception as error:
            paper["abstract_error"] = type(error).__name__
        return paper
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        result = []
        for i, paper in enumerate(pool.map(detail, rows), 1):
            result.append(paper)
            if i % 250 == 0:
                print(f"{venue} {year}: official details {i}/{len(rows)}", flush=True)
        return result


def sync_one(venue, year, tree, refresh=False, refresh_sources=False):
    directory = DATA / venue / str(year)
    cache = Cache(directory / "raw", refresh=refresh_sources)
    existing = directory / "manifest.json"
    previous = json.loads(existing.read_text()) if existing.exists() else None
    if not refresh and previous and previous.get("status") == "available":
        print(f"{venue} {year}: reuse normalized snapshot", flush=True)
        return
    meta = {"venue": venue, "year": year, "label": VENUES[venue][0], "kind": VENUES[venue][1],
            "homepage": VENUES[venue][3], "retrieved_at": now(), "sources": [], "errors": [],
            "official_coverage_verified": False, "review_policy": "仅展示来源提供的公开评分和正文；缺失不计为零分。"}
    rows = []
    if not_held(venue, year):
        meta.update(status="not_held", message="该会议按单双年轮换，本年份不举办。")
    elif venue == "iclr" and year in (2026, 2027):
        meta.update(status="existing", message="沿用现有完整 ICLR 本地快照和审稿正文缓存。", local_path=f"iclr{year}")
    else:
        try:
            if venue in ISSNS:
                rows, extra = journal(cache, venue, year);meta.update(extra)
            else:
                rows = mirror(cache, venue, year, tree)
                if rows:
                    meta["source_label"] = "Paper Copilot 公开镜像"
                elif venue == "siggraph":
                    rows = siggraph_program(cache, year)
                    meta["source_label"] = "SIGGRAPH 官方 Technical Papers 日程"
                elif venue in {"cvpr", "iccv", "wacv", "ntire", "aim"}:
                    rows = cvf(cache, venue, year);meta["source_label"] = "CVF 官方公开论文集"
                    meta["official_coverage_verified"] = True
                elif venue == "ijcai":
                    rows = ijcai(cache, year);meta["source_label"] = "IJCAI 官方论文集"
                elif venue in {"eccv", "bmvc", "accv"}:
                    rows = official_list(cache, venue, year);meta["source_label"] = "会议官方录用名单／论文集"
                else:
                    rows, extra = conference_crossref(cache, venue, year);meta.update(extra)
        except Exception as error:
            meta["errors"].append(f"{type(error).__name__}: {error}")
        meta.update(status="available" if rows else "unavailable",
                    message="已缓存公开记录；字段覆盖见下方统计。" if rows else "本次尚未取得可核实的公开论文记录；不代表该年份没有论文。")
    if venue == "siggraph":
        meta["coverage_note"] = "仅收录 Technical Papers；不含独立 Posters、受邀 TOG 论文展示或 SIGGRAPH Asia。日程 Description 可能为短简介；未核实 Journal / Conference 两轨的完整覆盖，未取得公开审稿评分。"
    unique = {}
    if not rows and previous and previous.get("status") == "available":
        # A failed/empty refresh is not evidence that the previous papers vanished.
        write_json(directory / "refresh-error.json", {"checked_at": now(),
                   "errors": meta["errors"] or ["Refresh returned no records"],
                   "attempted_sources": cache.attempted_sources})
        print(f"{venue} {year}: refresh failed; retained previous snapshot", flush=True)
        return
    for paper in rows:
        if paper["id"] in unique:
            if paper["title"] != unique[paper["id"]]["title"]:
                raise ValueError("Conflicting paper IDs")
            continue
        unique[paper["id"]] = paper
    directory.mkdir(parents=True, exist_ok=True)
    if unique:
        path = directory / "papers.jsonl"
        temporary = path.with_suffix(".jsonl.tmp")
        with temporary.open("w") as out:
            for paper in sorted(unique.values(), key=lambda p: p["id"]):
                out.write(json.dumps(paper, ensure_ascii=False) + "\n")
        temporary.replace(path)
        meta["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    meta.update(paper_count=len(unique), abstract_count=sum(bool(p["abstract"]) for p in unique.values()),
                author_count=sum(bool(p["authors"]) for p in unique.values()),
                keyword_count=sum(bool(p["keywords"]) for p in unique.values()),
                scored_count=sum(p["rating_mean"] is not None for p in unique.values()),
                sources=sorted(cache.sources, key=lambda s: s["url"]), attempted_sources=sorted(set(cache.attempted_sources)))
    write_json(existing, meta)
    (directory / "refresh-error.json").unlink(missing_ok=True)
    print(f'{venue} {year}: {meta["status"]}, {len(unique)} papers, {meta["abstract_count"]} abstracts', flush=True)


def write_catalog():
    catalog = []
    for path in sorted(DATA.glob("*/*/manifest.json")):
        raw = path.read_bytes()
        manifest = json.loads(raw)
        catalog.append({**{key: value for key, value in manifest.items() if key != "sources"},
                        "manifest_path": str(path.relative_to(ROOT)), "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                        "raw_response_count": len(manifest.get("sources", []))})
    write_json(DATA / "catalog.json", {"generated_at": now(), "venues": len(VENUES), "datasets": catalog})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venues", nargs="+", choices=list(VENUES), default=list(VENUES))
    parser.add_argument("--years", nargs="+", type=int, choices=YEARS, default=YEARS)
    parser.add_argument("--catalog-only", action="store_true", help="Reconcile the local coverage catalog without network access")
    parser.add_argument("--refresh", action="store_true", help="Rebuild normalized records from cached and newly available public responses")
    parser.add_argument("--refresh-sources", action="store_true", help="Request fresh public source responses, including the mirror index")
    args = parser.parse_args()
    if args.catalog_only:
        write_catalog()
        return
    cache = Cache(DATA / "raw", refresh=args.refresh_sources)
    raw_tree = cache.json("https://api.github.com/repos/papercopilot/paperlists/git/trees/main?recursive=1")
    tree = {"sha": raw_tree["sha"], "paths": {r["path"] for r in raw_tree["tree"]}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda item: sync_one(*item, tree, refresh=args.refresh or args.refresh_sources, refresh_sources=args.refresh_sources), [(v, y) for v in args.venues for y in args.years]))
    write_catalog()


if __name__ == "__main__":
    main()
