"""Parse a filing's primary-document HTML into named narrative sections (STRUCTURAL, Rule 18).

A 10-K/10-Q is organized by numbered Items ("Item 1. Business", "Item 1A. Risk Factors",
"Item 7. Management's Discussion…"). We locate those markers by regex (a computable structure, not a
semantic judgment) and take, for each item, its LARGEST text span (the table-of-contents entry is a
tiny span; the real section is large). S-1/other prospectuses use caption headers, handled as a
fallback. Everything is length-capped so we never embed a whole 100k-char filing.
"""
from __future__ import annotations

import html
import re

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_MULTINL = re.compile(r"\n\s*\n\s*\n+")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)

# "Item 1.", "Item 1A.", "Item 7.:" etc. (case-insensitive), start-of-lineish.
_ITEM = re.compile(r"\bItem\s+(\d{1,2}[A-Z]?)\s*[.\:\-–]", re.IGNORECASE)

_ITEM_TITLES = {
    "1": "Business", "1A": "Risk Factors", "1B": "Unresolved Staff Comments",
    "2": "Properties", "3": "Legal Proceedings",
    "7": "Management's Discussion and Analysis", "7A": "Market Risk Disclosures",
    "8": "Financial Statements", "9A": "Controls and Procedures",
}
# The narrative items worth ingesting for diligence (skip boilerplate/financial-statement dumps).
_WANTED_ITEMS = {"1", "1A", "3", "7", "7A"}

# S-1 / prospectus caption fallback headers.
_CAPTION_HEADERS = ["PROSPECTUS SUMMARY", "RISK FACTORS",
                    "MANAGEMENT'S DISCUSSION AND ANALYSIS", "BUSINESS", "USE OF PROCEEDS"]

_MAX_SECTION = 24000     # cap one section (splitter chunks further at 8k)
_MAX_TOTAL = 60000       # cap total narrative per filing (embedding-cost guard)


def html_to_text(raw: bytes) -> str:
    s = raw.decode("utf-8", "ignore")
    s = _SCRIPT_STYLE.sub(" ", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    s = _WS.sub(" ", s)
    s = _MULTINL.sub("\n\n", s)
    return s.strip()


def _item_sections(text: str) -> dict[str, str]:
    """For each wanted Item, its largest text span between consecutive item markers."""
    marks = [(m.group(1).upper(), m.start()) for m in _ITEM.finditer(text)]
    if len(marks) < 3:
        return {}
    spans: dict[str, str] = {}
    for i, (num, pos) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        body = text[pos:end].strip()
        if num in _WANTED_ITEMS and len(body) > len(spans.get(num, "")):
            spans[num] = body[:_MAX_SECTION]
    return {_ITEM_TITLES.get(k, f"Item {k}"): v for k, v in spans.items() if len(v) > 200}


def _caption_sections(text: str) -> dict[str, str]:
    """Fallback for S-1/prospectuses: split on all-caps caption headers."""
    positions: list[tuple[str, int]] = []
    up = text.upper()
    for cap in _CAPTION_HEADERS:
        idx = up.find(cap)
        if idx != -1:
            positions.append((cap.title(), idx))
    positions.sort(key=lambda x: x[1])
    out: dict[str, str] = {}
    for i, (title, pos) in enumerate(positions):
        end = positions[i + 1][1] if i + 1 < len(positions) else min(len(text), pos + _MAX_SECTION)
        body = text[pos:end].strip()
        if len(body) > 200:
            out[title] = body[:_MAX_SECTION]
    return out


def sections_from_html(raw: bytes) -> dict[str, str]:
    """Return {section_title: text} for a filing's primary HTML, length-capped, best-effort."""
    text = html_to_text(raw)
    secs = _item_sections(text) or _caption_sections(text)
    if not secs:
        # last resort: the leading narrative (skip a short cover page), capped.
        secs = {"Filing Text": text[:_MAX_TOTAL]}
    # enforce a total cap across sections (largest-first)
    total, kept = 0, {}
    for title, body in sorted(secs.items(), key=lambda kv: -len(kv[1])):
        if total >= _MAX_TOTAL:
            break
        room = _MAX_TOTAL - total
        kept[title] = body[:room]
        total += len(kept[title])
    return kept
