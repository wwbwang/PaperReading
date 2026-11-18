"""Build a local watchlist from public author names and explicit identity evidence."""
import argparse
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.paper_keywords import keyword_search_text, public_author_names
from scripts.paper_venues import VENUES
from scripts.sync_library import Cache, clean, write_json


def title_key(value):
    # Punctuation/spacing differences do not change the identity of a title.
    value = re.sub(r"\\(?:textbf|textit|textrm|text|mathrm|mathbf|mathcal|mathbb|mathit)\s*\{([^{}]*)\}", r"\1", value)
    return re.sub(r"[\W_]+", "", keyword_search_text(value))


def author_key(value):
    return " ".join(sorted(keyword_search_text(value).split()))


def parse_publications(content, url, aliases):
    """Read team evidence, excluding preprints; formal local names remain required."""
    names = {author_key(name) for name in aliases}
    publications = []
    for block in re.split(r"<h4\b[^>]*>", content, flags=re.I)[1:]:
        heading = block.split("</h4>", 1)[0]
        details = re.findall(r"<h5\b[^>]*>(.*?)</h5>", block, re.S | re.I)
        if len(details) < 2 or not names.intersection(author_key(name) for name in clean(details[0]).split(",")):
            continue
        venue = clean(details[1])
        if re.search(r"arxiv|preprint|submitted|under review", venue, re.I):
            continue
        link = re.search(r'href=["\']([^"\']+)', heading)
        publications.append({"title": clean(heading), "venue": venue,
                             "url": urljoin(url, link[1]) if link else url})
    return publications


def parse_profile_publications(content, url, aliases, page_format):
    """Read titles, author lists and venue labels from the configured public page."""
    patterns = {
        "lvmin": r'<div class="right-text">\s*<strong>(?P<title>.*?)</strong>\s*</br>(?P<venue>.*?)</br>(?P<authors>.*?)</br>',
        "jinjin": r'<pubtit>(?P<title>.*?)</pubtit>\s*<p>\s*<em>(?P<authors>.*?)</em>\s*<br\s*/?>\s*<strong>(?P<venue>.*?)</strong>',
        "zhiyuan": r'<div class="ptitle">(?P<title>.*?)</div>\s*<div class="pauthors">(?P<authors>.*?)</div>\s*<div class="pvenue">(?P<venue>.*?)(?:<p>|</div>)',
        "insait": r'pub-row-compact__meta">(?P<venue>.*?)</span>\s*</div>\s*<h3[^>]*>\s*<a\s+href="(?P<link>[^"]+)"[^>]*>(?P<title>.*?)</a>\s*</h3>\s*<p[^>]*>(?P<authors>.*?)</p>',
        "liangbin": (
            r'<td>\s*<a(?:\s[^>]*)?><b>(?P<title>[^<]+)</b></a>\s*<br>'
            r'(?P<authors>(?:(?!</td>).)*?)<br>\s*<p[^>]*>\s*'
            r'(?P<venue><em>(?:(?!</em>).)*?</em>\s*20\d{2})\.'
        ),
    }
    content = re.sub(r"<!--.*?-->", "", content, flags=re.S)
    names = {author_key(name) for name in aliases}
    publications = []
    for match in re.finditer(patterns[page_format], content, re.S):
        venue = " ".join(clean(match["venue"]).split())
        if not re.search(r"\b20\d{2}\b", venue) or re.search(r"arxiv|preprint|submitted|under review|tech(?:nical)? report", venue, re.I):
            continue
        listed_names = re.split(r",|\s+and\s+", clean(match["authors"]))
        if names.intersection(author_key(name.strip(" *†✉\n")) for name in listed_names):
            link = match.groupdict().get("link")
            publications.append({"title": " ".join(clean(match["title"]).split()), "venue": venue,
                                 "url": urljoin(url, link) if link else url})
    return publications


def refresh_profiles(directory, *, author_ids=None, refresh=True):
    registry = json.loads((directory / "watchlist.json").read_text())
    responses = {}
    for profile in registry["authors"]:
        if author_ids is not None and profile["id"] not in author_ids:
            continue
        formats = profile.get("publication_sources") or {profile["publications_url"]: "xpixel"}
        sources, publications = [], {}
        for url, page_format in formats.items():
            if url not in responses:
                cache = Cache(directory / "raw" / "bibliographies", refresh=refresh)
                responses[url] = cache.get(url).decode(), cache.sources[-1]
            content, record = responses[url]
            if page_format == "xpixel":
                entries = parse_publications(content, url, profile["aliases"])
            else:
                entries = parse_profile_publications(content, url, profile["aliases"], page_format)
            sources.append(record)
            for entry in entries:
                publications.setdefault(title_key(entry["title"]), entry)
        if not publications:
            raise ValueError(f'No publication evidence for {profile["id"]}; retaining the previous snapshot')
        write_json(directory / f'{profile["id"]}.json', {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "sources": sources, "publications": list(publications.values())})


def classify(paper, profile, evidence):
    names = {author_key(name) for name in public_author_names(paper.get("authors"))}
    if not names.intersection(author_key(name) for name in profile["aliases"]):
        return None, None
    match = evidence.get(title_key(paper["title"]))
    return ("verified", match["url"]) if match else ("candidate", None)


def safe_url(value):
    return value if isinstance(value, str) and urlsplit(value).scheme in {"http", "https"} else ""


def build_tracking(dist, datasets, directory=None):
    directory = directory or ROOT / "library/authors"
    profiles = json.loads((directory / "watchlist.json").read_text())["authors"]
    output = directory / "index.json"
    previous = json.loads(output.read_text()) if output.exists() else {"authors": []}
    old = {a["id"]: a for a in previous["authors"]}
    updated = datetime.now(timezone.utc).isoformat()
    result = []
    for profile in profiles:
        bibliography = json.loads((directory / f'{profile["id"]}.json').read_text())
        evidence = {title_key(p["title"]): p for p in bibliography["publications"]}
        seen = {p["key"]: p["first_seen"] for p in old.get(profile["id"], {}).get("papers", [])}
        papers, coverage = [], []
        aliases = {keyword_search_text(name) for name in profile["aliases"]}
        aliases |= {" ".join(name.split()[::-1]) for name in aliases}
        for meta, rows in datasets:
            venue, year = meta["venue"], meta["year"]
            coverage.append({"venue": venue, "year": year, "status": meta.get("datasetStatus", "available"),
                             "papers": len(rows), "publicAuthorPapers": meta.get("authorPaperCount", 0)})
            folder = dist / meta["detailBase"].lstrip("/")
            path = folder / "_search.sqlite3"
            if not rows or not path.exists():
                continue
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as database:
                # The index's normalized names are a candidate shortlist only.
                placeholders = ",".join("?" for _ in aliases)
                candidates = {record[0] for record in database.execute(
                    f"SELECT paper_id FROM authors WHERE search IN ({placeholders})", tuple(aliases))}
            selected = [p for p in rows if p["id"] in candidates]
            chunks = {}
            for row in selected:
                chunk = row["detail_chunk"]
                if chunk not in chunks:
                    chunks[chunk] = json.loads((folder / f"{chunk}.json").read_text())
                detail = chunks[chunk][row["id"]]
                state, evidence_url = classify({**row, **detail}, profile, evidence)
                if state is None:
                    continue
                key = f'{venue}/{year}/{row["id"]}'
                papers.append({"key": key, "id": row["id"], "title": row["title"], "venue": venue,
                    "venueLabel": VENUES[venue][0], "year": year, "status": row["status"],
                    "authors": public_author_names(detail.get("authors")), "identity": state,
                    "evidence_url": safe_url(evidence_url), "paper_url": safe_url(detail.get("paper_url")),
                    "pdf_url": safe_url(detail.get("pdf_url")), "rating_mean": row["rating_mean"],
                    "rating_count": row["rating_count"], "first_seen": seen.get(key, updated)})
        papers.sort(key=lambda p: (-p["year"], p["venue"], p["title"].casefold()))
        result.append({**profile, "evidence_retrieved_at": bibliography["retrieved_at"],
                       "verifiedCount": sum(p["identity"] == "verified" for p in papers),
                       "candidateCount": sum(p["identity"] == "candidate" for p in papers),
                       "papers": papers, "coverage": coverage})
    payload = {"updated_at": updated, "years": [2025, 2026, 2027], "authors": result}
    write_json(output, payload)
    write_json(dist / "authors.json", payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-profiles", action="store_true", help="Refresh public team bibliography evidence")
    args = parser.parse_args()
    if args.refresh_profiles:
        refresh_profiles(ROOT / "library/authors")
    from scripts.build_library import portal
    portal()


if __name__ == "__main__":
    main()
