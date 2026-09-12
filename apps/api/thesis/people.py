"""Who could settle a claim the record cannot.

Three roles, from the request, and they are NOT interchangeable — they answer different rungs and
they are found from different evidence:

  operator — lives the status quo, so knows what it costs and whether switching is feasible. Easiest
             to find: they authored the workaround, wrote the glue, published the migration post.
             Identity is carried by the artifact.
  advisor  — watches the category, so knows structure and timing. Found by repeated public analysis.
  buyer    — the only one who can speak to price, and the hardest to find from public record. Users
             complain; buyers allocate. A loud practitioner with no purchasing authority is NOT a
             customer contact and is never presented as one.

Identity discipline, inherited: STRONG KEYS ONLY, never a name merge. This repo has paid for that
lesson three times — naive name matching once bound 100% of podcast episodes to companies, all
wrongly, where gated matching bound 1-4% and got them right.
"""
from __future__ import annotations

import re

from .schema import ADVISOR, BUYER, OPERATOR

# source_key -> the role its author plausibly occupies, and the key their identity hangs on.
_ROLE_OF = {
    "eng_blog": (OPERATOR, "site"), "github": (OPERATOR, "github"),
    "huggingface": (OPERATOR, "github"), "stackexchange": (OPERATOR, "site"),
    "expert_feed": (ADVISOR, "site"), "founder_essay": (ADVISOR, "site"),
    "podcast": (ADVISOR, "site"), "show_notes": (ADVISOR, "site"),
    "arxiv": (OPERATOR, "orcid"), "openalex": (OPERATOR, "orcid"),
    "edgar": (BUYER, "cik"), "companies_house": (BUYER, "company_number"),
}
MAX_PER_ROLE = 4


def _named(facets: dict, source_key: str) -> tuple[str, str]:
    """(name, strong_key). Empty name means we cannot say who wrote it, and we do not guess."""
    f = facets or {}
    for k in ("author", "guest", "person", "writer"):
        v = str(f.get(k) or "").strip()
        if 3 <= len(v) <= 80 and not v.lower().startswith(("http", "www.")):
            return v, f"{source_key}:{re.sub(r'[^a-z0-9]+', '-', v.lower()).strip('-')}"
    return "", ""


def from_evidence(evidence: list[dict], facets_by_quote: dict | None = None) -> list[dict]:
    """Candidates drawn from evidence we ALREADY retrieved for this claim — so every suggestion
    carries the artifact that justifies it, and nobody appears for their own sake."""
    out: dict[str, dict] = {}
    per_role: dict[str, int] = {}
    for e in evidence or []:
        sk = (e.get("source_key") or "").lower()
        role_key = _ROLE_OF.get(sk)
        if not role_key:
            continue
        role, keykind = role_key
        facets = (facets_by_quote or {}).get(e.get("quote", "")[:120]) or {}
        name, ident = _named(facets, sk)
        if not name:
            continue
        if ident in out:
            out[ident]["artifacts"].append({"title": e.get("title", ""), "url": e.get("source_url", "")})
            continue
        if per_role.get(role, 0) >= MAX_PER_ROLE:
            continue
        per_role[role] = per_role.get(role, 0) + 1
        out[ident] = {"name": name, "identity": ident, "key_kind": keykind, "role": role,
                      "why": _why(role, e), "register": e.get("register", "stated"),
                      "artifacts": [{"title": e.get("title", ""), "url": e.get("source_url", "")}]}
    return list(out.values())


def _why(role: str, e: dict) -> str:
    t = (e.get("title") or "this").strip()[:90]
    if role == OPERATOR:
        return f"wrote “{t}” — they live the status quo this thesis proposes to replace"
    if role == ADVISOR:
        return f"published “{t}” — they follow how this category is moving"
    return f"named in “{t}” — a filed role in the function that would own the budget"


def buyer_guidance(claim: str, segment: str = "") -> str:
    """What to do when we cannot name a buyer, which is most of the time. Saying so plainly beats
    promoting a forum complainer into a customer contact."""
    seg = (segment or "this segment").strip()
    return (f"We can rarely name an economic buyer from public record, and we have not here. The "
            f"people most likely to hold this budget in {seg} are named in incumbents' own case "
            f"studies, in filed officer lists for the owning function, and in public procurement "
            f"records. A practitioner complaining about the problem is not the same person as the "
            f"one who signs for it.")
