"""Keyword-based category assignment. Tune the keywords in config.CATEGORIES."""
import re
from urllib.parse import urlsplit

import config


def _norm(text):
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "


_KEYWORDS = {slug: [" " + _norm(k).strip() for k in kws] for slug, kws in config.CATEGORIES.items()}


def categorize(url, title, body):
    """Returns (primary_category, extra_tags)."""
    path, title_n, head = _norm(urlsplit(url).path), _norm(title), _norm(body[:600])
    scores = {}
    for slug, keywords in _KEYWORDS.items():
        score = sum((3 if kw in path else 0) + (2 if kw in title_n else 0) + (1 if kw in head else 0)
                    for kw in keywords)
        if score:
            scores[slug] = score
    if not scores:
        return config.DEFAULT_CATEGORY, []
    ranked = sorted(scores, key=lambda s: -scores[s])    # stable: ties keep config order
    return ranked[0], [s for s in ranked[1:4] if scores[s] >= 2]