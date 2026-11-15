"""Preserve author keyword text and normalize it for case-insensitive partial search."""
import re
import unicodedata


def keyword_search_text(value):
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[\W_]+", " ", text).strip()
