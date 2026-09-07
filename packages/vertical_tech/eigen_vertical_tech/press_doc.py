"""Turn a startup-press RSS item into a citable news document + facets.

The sibling of `news_doc.py`. That one wraps GDELT, which gives metadata only, so its documents are
headline-level. These feeds publish the ARTICLE, so a document here carries the reporting itself —
which is what makes a funding round, a launch or an acquisition searchable rather than merely
countable.

Tier is unchanged and deliberate: `source_kind="news"` grades to `analysis`, above an unreviewed
preprint and below a filing. Press reports a round; the Form D attests it. When both exist the
filing wins, and the answer format must never present a reported number as an audited one.
"""
from __future__ import annotations

import html
import re

_MAX_BODY = 9000


def item_id(rec: dict) -> str:
    return str(rec.get("guid") or rec.get("id") or rec.get("link") or "").strip()


def title(rec: dict) -> str:
    return " ".join(str(rec.get("title") or "").split()).strip()


def _year(rec: dict) -> str:
    m = re.search(r"(19|20)\d{2}", str(rec.get("published") or ""))
    return m.group(0) if m else ""


def _strip_html(raw: str) -> str:
    txt = html.unescape(html.unescape(raw or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", txt)).strip()


def facets(rec: dict) -> dict:
    f = {
        "source_kind": "news",            # → "analysis" tier; never controlling for a factual claim
        "entity_type": "article",
        "publication": " ".join(str(rec.get("publication") or "").split()).strip(),
        "author": " ".join(str(rec.get("author") or "").split()).strip(),
        "url": str(rec.get("link") or "").strip(),
        "published": str(rec.get("published") or "").strip()[:64],
        "year": _year(rec),
    }
    return {k: v for k, v in f.items() if v}


def to_markdown(rec: dict) -> str:
    pub = " ".join(str(rec.get("publication") or "").split()).strip()
    author = " ".join(str(rec.get("author") or "").split()).strip()
    published = str(rec.get("published") or "").strip()

    parts = [f"# {title(rec)}", ""]
    byline = " — ".join(x for x in [pub, author] if x) or "Press report"
    parts += [byline + (f", {published}" if published else "")
              + "  (press report — reported, not audited; a filing or the company's own"
                " disclosure outranks it on any figure)", ""]
    if rec.get("link"):
        parts += [f"URL: {rec['link']}", ""]
    body = _strip_html(rec.get("content") or rec.get("summary") or "")
    if body:
        parts += ["## Report", body[:_MAX_BODY] + (" …" if len(body) > _MAX_BODY else ""), ""]
    return "\n".join(parts).strip() + "\n"
