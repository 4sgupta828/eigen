"""One publication date, in one sortable shape.

Feeds disagree: RSS ships RFC 2822 ("Mon, 07 Sep 2026 07:19:44 +0000"), Atom ships ISO 8601
("2026-09-07T14:00:03+00:00"), and a few ship neither cleanly. A card can display any of them, but a
FEED cannot be ordered by them — which is why "what's new" was previously ordered by when we happened
to ingest a row, an ordering that means nothing to a reader.

`iso_date` normalises to YYYY-MM-DD, which sorts correctly as plain text, so recency works in a jsonb
facet with no new column and no migration.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def iso_date(raw: str) -> str:
    """YYYY-MM-DD, or "" when the feed gave nothing we can trust. A wrong date is worse than none:
    it would put an old piece at the top of "this week"."""
    s = " ".join(str(raw or "").split())
    if not s:
        return ""
    m = _ISO.match(s)
    if m:
        return m.group(0)
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        return ""
    if dt is None:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    # a date in the future is a feed bug, not news; treat it as unknown rather than pinning it top
    if dt > datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1):
        return ""
    return dt.date().isoformat()
