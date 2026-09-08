"""Read the open roles off a company's own careers page.

Most companies do not use a job board we can read: measured over 90 careers pages with no board on
record, only 11 linked one. The rest list their roles in prose on their own page — text we already
crawled and stored. This turns that text into roles with a model, under the same discipline the fact
extractor uses: the model may only REPORT what the page says, and a title that does not appear on
the page is dropped rather than trusted.

What the gate stops: a model asked for open roles will happily produce "Software Engineer" for a
page that says "we're not hiring right now", because that is what such pages usually contain. The
verbatim check makes that failure impossible rather than unlikely.
"""
from __future__ import annotations

import re

MAX_PAGE_CHARS = 6000        # a careers page's role list is near the top; the tail is boilerplate
MAX_ROLES = 40

SYSTEM = (
    "You read ONE company careers page and list the OPEN ROLES it advertises. Return STRICT JSON: "
    '{"hiring": bool, "roles": [{"title": str, "location": str, "department": str}]}\n'
    "RULES\n"
    "- Copy each title VERBATIM from the page. Never normalise, translate, expand or invent one.\n"
    "- A role counts only if the page presents it as a position open NOW. Ignore team names, "
    "benefits, values, perks, office locations, alumni, past roles and 'no open roles' notices.\n"
    "- If the page advertises no specific role — a general 'get in touch', an empty board, a page "
    'that only describes the culture — return {"hiring": false, "roles": []}. That is the common '
    "case and it is the right answer; do not pad it.\n"
    "- location and department only when the page states them for that role, else empty strings.\n"
    "- At most 40 roles."
)


def user_payload(company: str, url: str, text: str) -> str:
    return f"Company: {company}\nPage: {url}\n\n{(text or '')[:MAX_PAGE_CHARS]}"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# Words that mean the page is describing a team or a policy, not advertising a job.
_NOT_A_ROLE = re.compile(r"^(we|our|the team|benefits?|perks?|culture|values?|life at|why |about |"
                         r"open roles?|careers?|jobs?|join us|no (open )?(roles?|positions?))\b", re.I)


def validate(out: dict, page_text: str) -> list[dict]:
    """The roles the PAGE supports. A title absent from the page is dropped, whatever the model said."""
    hay = _norm(page_text)
    roles: list[dict] = []
    seen: set[str] = set()
    for r in (out.get("roles") or []):
        if not isinstance(r, dict):
            continue
        title = " ".join(str(r.get("title") or "").split())[:140]
        key = _norm(title)
        if not title or len(key) < 3 or key in seen:
            continue
        if _NOT_A_ROLE.match(title):
            continue
        if key not in hay:               # the verbatim gate: the page must actually carry the title
            continue
        seen.add(key)
        roles.append({"title": title,
                      "location": " ".join(str(r.get("location") or "").split())[:120],
                      "department": " ".join(str(r.get("department") or "").split())[:120],
                      "url": ""})
        if len(roles) >= MAX_ROLES:
            break
    return roles
