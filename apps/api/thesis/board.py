"""Public ThesisBoard — the sanitizers that turn an owner's private thesis into a safe, self-contained,
anonymized snapshot for the global board.

Two disciplines, enforced here so no route can forget them:
  • ANONYMITY — the SUBMITTER's identity is removed (owner id, the genesis conversation, the private
    version/shaping history). The thesis's own SUBJECT (the company/segment it analyses) stays — that is
    the analysis, not the author. Private expert-call evidence (owner-only) is dropped.
  • ANSWERED-ONLY — unanswered lines of inquiry are stripped, so the board shows settled findings, not an
    empty research plan.

The output is self-contained: it renders with no further DB lookups and carries nothing that identifies
who published it or which internal thesis it came from.
"""
from __future__ import annotations

# Thesis-doc fields that either identify the submitter or are private working state — never published.
_STRIP_KEYS = (
    "owner_id", "versions", "shaping_prefs", "proposed_thesis", "decision", "focus_rung",
    "active_version", "share_token", "owner_token_hash", "revision", "created_at", "updated_at",
    "research_status",
)


def anonymize_doc(doc: dict) -> dict:
    """A copy of the thesis document safe to serve publicly with no auth: submitter identity and private
    working state removed, the genesis conversation dropped, private expert-call evidence removed. Keeps
    the thesis sentence, its subject, and the grounded evidence behind each claim (so citations resolve)."""
    d = dict(doc or {})
    for k in _STRIP_KEYS:
        d.pop(k, None)
    d["id"] = ""                 # never expose the source thesis id on a public snapshot
    d["is_owner"] = False        # a public viewer is never the owner — suppresses every edit control
    d["turns"] = []              # the genesis conversation is private to the author
    claims = []
    for c in (d.get("claims") or []):
        c = {k: v for k, v in dict(c).items() if k != "thesis_id"}     # never expose the source thesis id
        c["evidence"] = [{k: v for k, v in (e or {}).items() if k != "thesis_id"}
                         for e in (c.get("evidence") or [])
                         if (e or {}).get("source_key") != "call"]      # drop owner-only expert-call rows
        claims.append(c)
    d["claims"] = claims
    return d


def answered_inquiries(inquiries: list[dict]) -> list[dict]:
    """Only the lines of inquiry with at least one ANSWERED question, each carrying only its answered
    questions. An answered question = a set target_status AND a non-empty grounded answer."""
    out: list[dict] = []
    for inq in (inquiries or []):
        qs = [q for q in (inq.get("questions") or [])
              if q.get("target_status") and str(q.get("answer") or "").strip()]
        if not qs:
            continue
        inq = dict(inq)
        inq["questions"] = qs
        out.append(inq)
    return out


def answered_count(inquiries: list[dict]) -> int:
    return sum(len(i.get("questions") or []) for i in (inquiries or []))


def public_voices(voices: dict) -> dict:
    """The organized-Voices snapshot, safe to serve publicly: the relevance buckets plus the moment
    cards they reference (title, speaker, link…). Voices are public first-person founder/investor
    content — nothing to strip; we keep exactly what the board needs to render with no live search.
    Returns {} when nothing has been organized, so the board simply omits the section."""
    v = dict(voices or {})
    buckets = v.get("buckets") or []
    if not buckets:
        return {}
    return {"buckets": buckets, "moments": v.get("moments") or []}


def anonymize_brainstorm(threads: list[dict]) -> list[dict]:
    """Brainstorm threads as a public snapshot — the author's exploration of the thesis with identity
    and internal ids removed. Keeps each thread's title and its transcript (the questions asked and the
    agent's structured answers). Threads with no messages are dropped; internal working memory is not
    published."""
    out: list[dict] = []
    for t in (threads or []):
        msgs = [{"role": m.get("role"), "content": m.get("content") or {}}
                for m in (t.get("messages") or []) if isinstance(m, dict)]
        if not msgs:
            continue
        out.append({"title": t.get("title") or "", "messages": msgs})
    return out
