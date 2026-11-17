"""Document-frequency topics from the pinned snapshot's author keywords."""

import sqlite3
import re
import unicodedata
from collections import Counter, defaultdict
from contextlib import closing
from functools import lru_cache

def topic_key(value):
    # Keep meaningful symbols: C++, C# and C are distinct topics.
    return re.sub(r"[\s_\-‐‑‒–—]+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


class TopicIndex:
    def __init__(self, rows):
        self.papers = {}
        labels = defaultdict(Counter)
        for paper_id, keywords in rows:
            topics = {}
            for label in keywords.split(";"):
                label = label.strip()
                key = topic_key(label)
                if key and len(key) <= 200 and key not in {"none", "null", "nan", "n a", "na"}:
                    topics.setdefault(key, label)
            self.papers[paper_id] = frozenset(topics)
            for key, label in topics.items():
                labels[key][label] += 1
        self.labels = {key: min(variants, key=lambda label: (-variants[label], label.casefold(), label))
                       for key, variants in labels.items()}

    def matches(self, paper_id, topics):
        return self.papers[paper_id].issuperset(topics)

    def summarize(self, ids, limit=60):
        ids = set(ids)
        if not ids.issubset(self.papers):
            raise ValueError("Unknown paper in this snapshot")
        counts = Counter()
        covered = 0
        for paper_id in ids:
            topics = self.papers[paper_id]
            covered += bool(topics)
            counts.update(topics)
        words = [{"key": key, "label": self.labels[key], "count": count,
                  "percentage": 100 * count / len(ids)}
                 for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]
        return {"paper_count": len(ids), "keyword_papers": covered, "missing_keywords": len(ids) - covered,
                "topic_count": len(counts), "words": words}


@lru_cache(maxsize=4)
def topic_index(database_path):
    with closing(sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)) as database:
        return TopicIndex(database.execute("SELECT id, keywords FROM papers"))
