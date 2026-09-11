"""A DeepDive dossier, read for what a FUNDRAISE needs.

DeepDive already does the hard part: resolve a name or domain to a company, discover it on the web if
we do not hold it, crawl its own site, extract claims with one model call per page, and put every
claim through the congruence gates (`subject_bound` drops the customer testimonial on the company's
own case-study page; `metric_defined` drops a number whose metric word is not near it). It costs what
it costs, and it is projected and capped before it spends.

None of that needed rebuilding. What was missing is the LENS: a dossier is written for diligence on a
company, and a founder asking "who should I raise from" needs a different reading of the same facts.

The fundamentals that change an investor match, and where each comes from:

  existing investors   Investors section      -> the co_investor leg, the strongest single signal we
                                                have: firms that have already co-invested with your
                                                backers have done a deal shaped like yours.
  round history        Funding rounds         -> stage EVIDENCE, as opposed to the stage a deck claims.
  what / who for       Who buys, Model        -> the sector legs.
  team                 Key people             -> shown, never scored (see the spec: matching on founder
                                                pedigree means inventing an investor preference we have
                                                never observed).
  hiring               Open roles             -> a growth signal a founder can point to, stated as what
                                                it is: open roles, not traction.
  milestones           Stated milestones      -> claims WITH their attribution, never converted into a
                                                revenue integer. DeepDive refuses that and so does this.

Everything here is a re-reading of claims that already carry a register, a quote and a source. This
module adds no facts, calls no model, and fabricates nothing: where a section is absent it says so.
"""
from __future__ import annotations


def _claims(dossier: dict, *kinds: str) -> list[dict]:
    out = []
    for s in (dossier or {}).get("sections") or []:
        if s.get("kind") in kinds:
            out.extend(s.get("claims") or [])
    return out


def _section(dossier: dict, title_startswith: str) -> dict | None:
    for s in (dossier or {}).get("sections") or []:
        if str(s.get("title") or "").lower().startswith(title_startswith.lower()):
            return s
    return None


def existing_investors(dossier: dict) -> list[dict]:
    """Who already backs them, with the source that says so. These become the co_investor leg."""
    sec = _section(dossier, "Investors")
    out = []
    for c in (sec or {}).get("claims") or []:
        name = c.get("name") or c.get("claim") or ""
        if not name:
            continue
        out.append({"name": name, "slug": c.get("slug") or "", "lead": bool(c.get("lead")),
                    "source_url": c.get("source_url") or "", "quote": c.get("quote") or ""})
    return out


def rounds(dossier: dict) -> list[dict]:
    """Round history — the stage a company has EVIDENCE for, beside whatever a deck claims."""
    out = []
    for c in _claims(dossier, "financing"):
        out.append({"round": c.get("round_name") or c.get("claim") or "",
                    "date": str(c.get("event_date") or c.get("as_of") or "")[:10],
                    "investors": c.get("investors") or [], "lead": c.get("lead") or "",
                    "source_url": c.get("source_url") or ""})
    return [r for r in out if r["round"]]


def evidenced_stage(dossier: dict) -> str:
    """The latest round we can SEE, mapped to the index's stage vocabulary. Empty when nothing is
    visible — we never fall back to guessing from an amount, which is the same rule stage_from_text
    enforces on the deck side."""
    words = {"pre-seed": "pre_seed", "pre seed": "pre_seed", "preseed": "pre_seed", "seed": "seed",
             "series a": "series_a", "series b": "series_b", "series c": "series_c",
             "series d": "growth", "growth": "growth"}
    best, rank = "", -1
    order = ["pre_seed", "seed", "series_a", "series_b", "series_c", "growth"]
    for r in rounds(dossier):
        t = str(r.get("round") or "").lower()
        for w, v in words.items():
            if w in t and order.index(v) > rank:
                best, rank = v, order.index(v)
    return best


def team(dossier: dict) -> list[dict]:
    sec = _section(dossier, "Key people")
    return [{"name": c.get("name") or c.get("claim") or "", "title": c.get("title") or "",
             "source_url": c.get("source_url") or ""}
            for c in (sec or {}).get("claims") or []][:12]


def milestones(dossier: dict) -> list[dict]:
    """Claims with their attribution intact. A milestone is who said what, when — never a number we
    have converted into a fact about the business."""
    return [{"claim": c.get("claim") or "", "attribution": c.get("attribution") or "",
             "register": c.get("register") or "stated", "source_url": c.get("source_url") or "",
             "as_of": str(c.get("as_of") or "")[:10]}
            for c in _claims(dossier, "stated")][:12]


def hiring(dossier: dict) -> dict:
    sec = _section(dossier, "Open roles")
    claims = (sec or {}).get("claims") or []
    return {"open_roles": len(claims), "titles": [c.get("title") or c.get("claim") or "" for c in claims][:8]}


def fundraising_profile(dossier: dict) -> dict:
    """The dossier, read for a raise. Every list is allowed to be empty; an empty list is a stated gap
    rather than an invitation to fill it in."""
    c = (dossier or {}).get("company") or {}
    inv = existing_investors(dossier)
    rds = rounds(dossier)
    gaps = []
    if not inv:
        gaps.append("No existing investors found — the co-investor signal, which is the strongest one "
                    "we have, cannot be used for this search.")
    if not rds:
        gaps.append("No funding rounds visible, so the stage used is the one you state rather than one "
                    "we can evidence.")
    return {
        "company": {"id": c.get("id") or "", "name": c.get("name") or "",
                    "website": c.get("website") or "", "one_liner": c.get("one_liner") or ""},
        "existing_investors": inv,
        "rounds": rds,
        "evidenced_stage": evidenced_stage(dossier),
        "team": team(dossier),
        "milestones": milestones(dossier),
        "hiring": hiring(dossier),
        "gaps": gaps,
    }


def contract_from(profile: dict, *, claimed_stage: str = "", sectors: list[str] | None = None,
                  geo: list[str] | None = None) -> dict:
    """What to search investors with. The claimed stage is kept ALONGSIDE the evidenced one rather than
    overwritten — the reviewers split on this, and the resolution in the spec is that we never correct
    a founder's claim, we show both and name the difference."""
    ev = profile.get("evidenced_stage") or ""
    return {
        "stage": claimed_stage or ev,
        "stage_evidenced": ev,
        "stage_claimed": claimed_stage,
        "stage_disagrees": bool(ev and claimed_stage and ev != claimed_stage),
        "sectors": list(sectors or []),
        "geo": list(geo or []),
        "co_investors": [i["slug"] for i in profile.get("existing_investors") or [] if i.get("slug")],
    }
