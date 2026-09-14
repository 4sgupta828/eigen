"""QUERY EXPANSION for the dense leg (HyDE) — bridge the investor's vocabulary to the company's own.

The relevance failure this fixes: a company describes itself in its founders' words ("training
company-specific models that approve AI actions"), the investor searches in category words ("agentic
ai", "AI agent authorization"), and the two embeddings sit too far apart — so the literal keyword leg
wins and the substantively-relevant company never surfaces. Measured on prod: decawork.ai ranked #1 for
its own words and was absent from the top 60 for "agentic ai".

The mechanism is generic (embed a hypothetical answer, not the question); the PROMPT is the vertical's —
it knows what an investor means by a category and which adjacent words retrieve the same companies. Only
the dense (semantic) leg reads this expansion; the keyword leg keeps the investor's literal words as its
anchor, so a precise term still matches precisely.
"""
from __future__ import annotations

import hashlib
import logging
import re

_log = logging.getLogger("eigen.startups.query_expand")

# a query that already carries enough signal (a full sentence) gains little from expansion and costs a
# model call; expansion earns its keep on the short, category-shaped queries where the vocabulary gap bites.
_MAX_WORDS_TO_EXPAND = 12

SYSTEM = """You expand a venture investor's SHORT startup-search query into a rich description of the KIND
of company they are looking for, so a semantic search can find companies that build exactly this but
describe themselves in different words.

Write 2-4 sentences of plain prose describing what such a company does: the problem it solves, the
technology or approach, who it sells to, and the ADJACENT WORDS a founder might use for the same thing.
An investor typing "agentic ai" is looking for companies building, securing, orchestrating, or governing
autonomous AI agents — a founder of one such company might never write "agentic" and instead say
"autonomous software that takes actions", "approve what an agent is allowed to do", "guardrails for
tool use", or "authorization for AI agents". Name those synonyms.

RULES:
- Describe the CATEGORY, never invent specific company names, funding, or facts.
- Stay faithful to the query's intent — do not drift to an adjacent-but-different market. "agentic ai"
  is not "AI chatbots"; "developer tools" is not "no-code app builders".
- Use the words a range of founders in this space would actually use, including the plain-English framing
  of the jargon, so a company that avoids the buzzword is still described.
- Output ONLY the description prose. No preamble, no JSON, no bullet points, no quotes.
"""


def _too_rich_to_expand(query: str) -> bool:
    return len((query or "").split()) > _MAX_WORDS_TO_EXPAND


async def expand_query(llm_json, query: str) -> str | None:
    """Return a HyDE-style description to embed for the dense leg, or None to fall back to the raw query.

    `llm_json(system, user) -> dict` is the same seam the compiler uses; we ask for prose and read it
    from a `{"description": "..."}` envelope, tolerating a model that returns a bare string field.
    """
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q or llm_json is None or _too_rich_to_expand(q):
        return None
    try:
        out = await llm_json(SYSTEM + '\nReturn JSON: {"description": "<the prose>"}.', q)
    except Exception as e:   # noqa: BLE001 — expansion is an enhancement; a failure must never fail a search
        _log.warning("query expansion failed for %r: %s", q[:80], e)
        return None
    if not isinstance(out, dict):
        return None
    desc = out.get("description") or out.get("text") or ""
    if isinstance(desc, list):
        desc = " ".join(str(x) for x in desc)
    desc = re.sub(r"\s+", " ", str(desc)).strip()
    if len(desc) < len(q):   # a model that returned less than the query has not expanded anything
        _log.info("query expansion for %r produced nothing usable", q[:80])
        return None
    # the investor's own words stay in front, so the expansion enriches rather than replaces the intent
    expanded = f"{q}. {desc}"[:1200]
    _log.info("expanded %r -> %d chars", q[:80], len(expanded))
    return expanded


def cache_key(query: str) -> str:
    return hashlib.sha1((query or "").strip().lower().encode("utf-8")).hexdigest()[:16]
