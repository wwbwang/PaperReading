"""Preserve author keyword text and normalize it for case-insensitive partial search."""
import re
import unicodedata


def keyword_search_text(value):
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[\W_]+", " ", text).strip()


def public_author_names(value):
    values = value.split(";") if isinstance(value, str) else value if isinstance(value, list) else []
    placeholders = {"anonymous", "anonymous author", "anonymous authors", "unknown"}
    return [name.strip() for name in values if isinstance(name, str) and name.strip()
            and keyword_search_text(name) not in placeholders]
