"""Startup Advisor — given a startup, which investors have actually done this before?

The question a founder asks is "who will fund me". That is a prediction, and this codebase does not make
predictions it cannot ground (docs/specs/investors.md §0). So the question is answered as the nearest thing
that IS knowable, and the difference is stated on every row: **who has already funded companies like yours,
at your stage, in your geography, and is still deploying capital.** That is a record, not a forecast.

Six signals, each traceable to a register:

  ▣ still deploying     they filed a fund within 36 months   — filed, and the one nobody else shows a founder
  ◈ funds your sector   companies in their portfolio like you — observed over what we hold
  ◈ funds your stage    the stages of the rounds we can date  — observed
  ◈ funds your geo      where their portfolio companies are   — observed
  ▢ says your stage     their own site says they do it        — stated, in their voice
  ◈ co-invests with     they appear beside investors you have — observed

And one that matters more than any of them and is never a reason TO reach out:

  ⚠ conflict            they already fund something in your sector

A firm that clears no signal is not returned. A firm that clears one is returned with one reason, and the
card says so — three matched signals is a different claim from one, and collapsing them into a single score
would hide exactly the distinction a founder is trying to make.

**"Still deploying" alone is not advice.** It is true of every firm that has raised recently, so a list
ranked on it is a list of everyone, in alphabetical order, wearing the costume of a recommendation. At least
one signal that is about THIS startup — its sector, its stage, its geography, its existing investors — has to
match, and when none does the answer says the portfolio record is too thin to say rather than filling the
page.
"""
from __future__ import annotations

import re

from eigen_kernel.facets import Contract

from .schema import KIND

# What each signal is worth when ordering the list. `still_deploying` leads deliberately: a fund that closed
# last year is raising, and a firm whose last filing was in 2019 is not going to write your cheque however
# good the sector fit looks. Sector is next, because it is the reason a partner takes the meeting.
WEIGHTS = {
    "still_deploying": 1.0,
    "sector": 0.9,
    "stage_observed": 0.6,
    "stage_stated": 0.5,
    "geo": 0.4,
    "co_investor": 0.7,
}

STAGES = ("pre_seed", "seed", "series_a", "series_b", "series_c", "growth")

_DECK_HINTS = {
    "pre_seed": ("pre-seed", "pre seed", "preseed", "friends and family"),
    "seed": ("seed round", "raising seed", "seed financing", "our seed"),
    "series_a": ("series a",),
    "series_b": ("series b",),
    "series_c": ("series c",),
    "growth": ("series d", "series e", "growth round", "growth equity"),
}


def stage_from_text(text: str) -> str:
    """The stage a deck SAYS it is raising, or '' — read only from an explicit round name.

    An amount is never a stage (§4 of the startup spec, and the same rule here): "$3M" is a seed in one
    sector and a pre-seed in another, and guessing a founder's round from their ask is exactly the kind of
    inference this product refuses to make silently.
    """
    low = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    # Latest named round first, because a Series A deck recaps the seed on its traction slide — but pre-seed
    # is checked ahead of seed, since "pre-seed round" contains "seed round" and would otherwise read as one.
    for stage in ("growth", "series_c", "series_b", "series_a", "pre_seed", "seed"):
        for hint in _DECK_HINTS[stage]:
            if hint in low:
                return stage
    return ""


def build_contract(*, stage: str = "", sectors: list[str] | None = None, geo: list[str] | None = None,
                   limit: int = 40) -> Contract:
    """The search behind the advice: a PREFER on every signal, a MUST on almost nothing.

    A must here would be a quiet lie. "Series A investors in fintech in Texas" as three hard filters returns
    an empty page long before it returns a wrong one, because our stage coverage is thin and a firm that has
    never been observed doing your stage may simply not have been observed. So the signals rank, the reasons
    are shown per row, and the only hard filter is the one that is filed and cheap: they are an investor.
    """
    prefer: dict = {}
    if stage:
        prefer["stated_stage"] = [stage]
        prefer["observed_stage"] = [stage]
    if sectors:
        prefer["sector_focus"] = list(sectors)
        prefer["observed_sector"] = list(sectors)
    if geo:
        prefer["observed_geo"] = list(geo)
        prefer["geo_focus"] = list(geo)
    prefer["still_deploying"] = ["yes_recent"]
    return Contract(kind=KIND, text="", must={}, prefer=prefer, avoid={}, rank_by="match", limit=limit)


# Signals that say something about a PARTICULAR startup. Everything else is context, not a match.
SPECIFIC = ("sector", "stage_observed", "stage_stated", "geo", "co_investor")


def is_advice(why: list[dict]) -> bool:
    """Does this row say anything about this startup, or only that the firm exists and has money?"""
    return any(w["signal"] in SPECIFIC for w in why)


def reasons_for(row: dict, *, stage: str, sectors: list[str], geo: list[str],
                co_investors: list[str]) -> tuple[list[dict], float]:
    """([{signal, register, detail}], score) — why this firm is on the list, in the registers it came from.

    Every reason names its register, because "they say they do seed" and "we can see eleven seed rounds" are
    different kinds of claim and a founder deciding who to email should be able to tell them apart.
    """
    facets = row.get("facets") or {}
    out: list[dict] = []
    score = 0.0

    def add(signal: str, register: str, detail: str) -> None:
        nonlocal score
        out.append({"signal": signal, "register": register, "detail": detail})
        score += WEIGHTS.get(signal, 0.2)

    if "yes_recent" in (facets.get("still_deploying") or []):
        yr = (row.get("numeric") or {}).get("latest_fund_year")
        add("still_deploying", "filed", f"filed a fund in {int(yr)}" if yr else "filed a fund recently")

    hit = [s for s in sectors if s in (facets.get("observed_sector") or [])]
    if hit:
        add("sector", "observed", "funds " + ", ".join(s.replace("_", " ") for s in hit[:2]))
    said = [s for s in sectors if s in (facets.get("sector_focus") or [])]
    if said and not hit:
        add("sector", "stated", "says they fund " + ", ".join(s.replace("_", " ") for s in said[:2]))

    if stage and stage in (facets.get("observed_stage") or []):
        add("stage_observed", "observed", f"has done {stage.replace('_', ' ')} rounds")
    elif stage and stage in (facets.get("stated_stage") or []):
        add("stage_stated", "stated", f"says they invest at {stage.replace('_', ' ')}")

    g = [x for x in geo if x in (facets.get("observed_geo") or []) or x in (facets.get("geo_focus") or [])]
    if g:
        add("geo", "observed", "funds in " + ", ".join(x.upper() for x in g[:2]))

    co = [c for c in co_investors if c in (facets.get("co_investor") or [])]
    if co:
        add("co_investor", "observed", "co-invests with " + ", ".join(c.replace("_", " ") for c in co[:2]))

    return out, score


def conflicts_for(portfolio: list[dict], sectors: list[str], sector_of) -> list[dict]:
    """Portfolio companies of this firm that sit in the founder's own sector.

    Shown as a warning and never as a reason. A firm that already backs a direct competitor is usually the
    wrong door, and it is the single most useful thing a founder can learn from an investor list — but it is
    OUR sector labelling on both sides, so it is offered as "worth checking", not as a verdict.
    """
    out = []
    for c in portfolio or []:
        overlap = [s for s in (sector_of.get(c["id"]) or []) if s in sectors]
        if overlap:
            out.append({"id": c["id"], "name": c.get("name") or c["id"],
                        "sector": overlap[0].replace("_", " ")})
    return out[:4]
