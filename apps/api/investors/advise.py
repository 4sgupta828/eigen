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
# Per-AXIS weight. Each axis contributes weight x STRENGTH in [0,1], not weight x presence — a firm
# that has done eleven rounds in your sector should not tie one that merely lists the sector.
#
# `still_deploying` is deliberately NOT here. It used to carry 1.0, the largest weight of any signal,
# which meant a generalist matching nothing but "filed a fund recently" outranked a specialist who
# actually invests in the founder's sector. Recency is NECESSARY, NOT SUFFICIENT, so it multiplies the
# score instead of adding to it (see `recency_multiplier`).
WEIGHTS = {
    "sector": 1.0,
    "stage_observed": 0.8,
    "stage_stated": 0.35,     # they say so; a third of what we can see them do
    "geo": 0.5,
    "co_investor": 0.7,
    # Behaviour we can see in the edges, about rounds shaped like this one. Weighted below a direct
    # sector match and above geography: that a firm has repeatedly followed your backers, or
    # repeatedly written first cheques, is a stronger reason to email them than sharing a country.
    "follows_on": 0.65,
    "first_round": 0.55,
    "cheque": 0.4,
}

# A dormant fund is not a match however well its history reads: it is not writing cheques. Recency
# scales the whole score rather than adding to it, and never quite reaches zero so a perfect match
# with an old filing still appears — labelled — rather than vanishing without explanation.
DORMANT_YEARS = 7
_RECENCY_FLOOR = 0.25
_DORMANT_MULT = 0.06   # >= DORMANT_YEARS with no filing: shown, labelled, and effectively last
CONFLICT_PENALTY = 1.6        # a direct competitor is disqualifying, not a footnote
CHEQUE_MISMATCH_PENALTY = 0.5


def _saturating(n: int, alpha: float = 0.55) -> float:
    """n hits -> [0,1), saturating. The first round in your sector is worth far more than the tenth."""
    import math
    return 1.0 - math.exp(-alpha * max(0, n))


OBSERVED_FLOOR = 0.30   # any hit we have SEEN scores at least this
STATED_STRENGTH = 0.20  # a firm's own claim scores below the weakest thing we have observed


def _strength(hits: int, denom: int | None) -> float:
    """Strength of an observed overlap, normalised by the population it was measured over where we
    know it. Five of ten is a thesis; five of a thousand is noise. Without a denominator we can only
    say "at least this many", so we fall back to the saturating count and never invent a rate.

    Floored at OBSERVED_FLOOR so that dividing by a big portfolio can never push an observed fact
    below a stated one — one devtools company out of nine hundred is weak, but we watched it happen,
    and "they say they do devtools" must not outrank it."""
    if hits <= 0:
        return 0.0
    shaped = _saturating(hits)
    if denom and denom > 0:
        # half the signal is "how many", half is "out of how many". A clamp here instead would make
        # every single-hit firm identical and throw away the concentration entirely.
        shaped = 0.5 * shaped + 0.5 * min(1.0, hits / denom)
    return OBSERVED_FLOOR + (1.0 - OBSERVED_FLOOR) * shaped


def recency_multiplier(latest_fund_year, now_year: int) -> float:
    """1.0 for a fund filed this year, decaying with a ~3-year half-life to a floor. No filing at all
    is treated as dormant rather than as unknown-but-fine: we would be ranking on a guess."""
    import math
    if not latest_fund_year:
        return _DORMANT_MULT
    gap = max(0, now_year - int(latest_fund_year))
    if gap >= DORMANT_YEARS:
        return _DORMANT_MULT      # not "old", but out of the market — a history, not a match
    return max(_RECENCY_FLOOR, math.exp(-math.log(2) * gap / 3.0))

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
                co_investors: list[str], now_year: int | None = None) -> tuple[list[dict], float]:
    """([{signal, register, detail}], score) — why this firm is on the list, in the registers it came from.

    Every reason names its register, because "they say they do seed" and "we can see eleven seed rounds" are
    different kinds of claim and a founder deciding who to email should be able to tell them apart.

    The score is weight x STRENGTH per axis, then multiplied by recency. It used to be a sum of weights
    over signal PRESENCE, which had two consequences worth stating plainly:
      - `still_deploying` carried the largest weight of any signal (1.0), so a generalist that had
        merely filed a fund recently outranked a specialist who actually invests in the sector; and
      - matching `stated_stage` (0.5) plus `geo` (0.4) tied real observed sector overlap (0.9),
        so what a firm SAYS about itself could outweigh what we can see it do.
    """
    import datetime as _dt
    now_year = now_year or _dt.date.today().year
    facets = row.get("facets") or {}
    nums = row.get("numeric") or {}
    denom = row.get("denom") or {}
    out: list[dict] = []
    score = 0.0

    def add(signal: str, register: str, detail: str, strength: float = 1.0) -> None:
        nonlocal score
        out.append({"signal": signal, "register": register, "detail": detail,
                    "strength": round(max(0.0, min(1.0, strength)), 3)})
        score += WEIGHTS.get(signal, 0.2) * max(0.0, min(1.0, strength))

    # Recency is reported as a reason (a founder wants to know they are live) but scores nothing on
    # its own — it multiplies the whole at the end.
    yr = nums.get("latest_fund_year")
    if "yes_recent" in (facets.get("still_deploying") or []):
        add("still_deploying", "filed", f"filed a fund in {int(yr)}" if yr else "filed a fund recently", 0.0)

    hit = [x for x in sectors if x in (facets.get("observed_sector") or [])]
    if hit:
        st = _strength(len(hit), denom.get("observed_sector") or nums.get("portfolio_count"))
        add("sector", "observed", "funds " + ", ".join(x.replace("_", " ") for x in hit[:2]), st)
    said = [x for x in sectors if x in (facets.get("sector_focus") or [])]
    if said and not hit:
        add("sector", "stated", "says they fund " + ", ".join(x.replace("_", " ") for x in said[:2]), STATED_STRENGTH)

    if stage and stage in (facets.get("observed_stage") or []):
        st = _strength(1, denom.get("observed_stage"))
        add("stage_observed", "observed", f"has done {stage.replace('_', ' ')} rounds", max(0.6, st))
    elif stage and stage in (facets.get("stated_stage") or []):
        add("stage_stated", "stated", f"says they invest at {stage.replace('_', ' ')}", 1.0)

    g = [x for x in geo if x in (facets.get("observed_geo") or [])]
    if g:
        add("geo", "observed", "funds in " + ", ".join(x.upper() for x in g[:2]),
            _strength(len(g), denom.get("observed_geo")))
    else:
        gs = [x for x in geo if x in (facets.get("geo_focus") or [])]
        if gs:
            add("geo", "stated", "says they fund in " + ", ".join(x.upper() for x in gs[:2]), STATED_STRENGTH)

    # Round behaviour. `follows` and `firsts` are counts from iv_edge, handed in by the route —
    # reasons_for stays pure and testable, and the SQL stays in the store.
    n_follow = int((row.get("behaviour") or {}).get("follows_on") or 0)
    if n_follow:
        add("follows_on", "observed",
            f"has come in after your backers {n_follow} time{'' if n_follow == 1 else 's'}",
            _saturating(n_follow, 0.8))
    n_first = int((row.get("behaviour") or {}).get("first_round") or 0)
    if n_first and not co_investors:
        # Only offered when there are no backers to follow: for a founder with a cap table, "they
        # write first cheques" is noise beside "they have followed yours".
        add("first_round", "observed",
            f"has written the first institutional cheque {n_first} time{'' if n_first == 1 else 's'}",
            _saturating(n_first, 0.25))

    co = [c for c in co_investors if c in (facets.get("co_investor") or [])]
    if co:
        add("co_investor", "observed", "co-invests with " + ", ".join(c.replace("_", " ") for c in co[:2]),
            _strength(len(co), denom.get("co_investor")))

    return out, score * recency_multiplier(yr, now_year)


def axes_with_evidence(why: list[dict]) -> list[str]:
    """Which axes we actually had evidence on. Shown to the reader, because a firm ranked on one axis
    out of five is a different object from one matched on four, and a list that hides the difference
    invites a founder to read confidence we do not have — which matters most in exactly the regime we
    are in, where observed sector is known for under 1% of firms."""
    seen, order = set(), []
    for w in why or []:
        a = {"stage_observed": "stage", "stage_stated": "stage"}.get(w["signal"], w["signal"])
        if a != "still_deploying" and a not in seen:
            seen.add(a); order.append(a)
    return order


def penalties_for(row: dict, *, conflicts: list[dict], raise_target: float | None = None) -> tuple[float, list[str]]:
    """(penalty, notes) — the reasons to push a firm DOWN. These used to be decoration: conflicts_for
    attached a warning to the card and changed nothing about where the card sat, so the single most
    disqualifying fact we hold — that they already fund a direct competitor — left the firm at the top
    of the list a founder was about to email."""
    import datetime as _dt
    nums = row.get("numeric") or {}
    penalty, notes = 0.0, []

    if conflicts:
        penalty += CONFLICT_PENALTY
        notes.append("already funds a company in your sector")

    yr = nums.get("latest_fund_year")
    if yr and (_dt.date.today().year - int(yr)) >= DORMANT_YEARS:
        notes.append(f"no fund filed since {int(yr)}")

    # Filed data, so this is cheap and certain: a fund whose MINIMUM cheque dwarfs the whole round is
    # not a candidate for it, however well the sector reads.
    mn = nums.get("min_investment")
    if raise_target and mn and mn > 5 * raise_target:
        penalty += CHEQUE_MISMATCH_PENALTY
        notes.append("their minimum cheque is far larger than your raise")

    return penalty, notes


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


# ── Coverage bias: Form ADV is a US register ───────────────────────────────────────────────────
# Not a gap that time closes. The SEC adviser registers are the spine of this index, and a firm with
# no US adviser registration is not merely unknown to us — it is systematically absent. A founder in
# London searching "seed funds in the UK" gets a US-skewed list that LOOKS complete, and silence about
# that is the difference between a coverage limit and a misleading answer.
US_TOKENS = {"us", "usa", "united states"}


def coverage_bias_note(geo: list[str]) -> str:
    """The warning a non-US search must carry, or '' when the search is US-based."""
    outside = [g for g in (geo or []) if str(g).strip().lower() not in US_TOKENS]
    if not outside:
        return ""
    where = ", ".join(sorted({str(g).upper() for g in outside}))
    return (f"This index is built on the SEC adviser registers, which are a US filing system. Firms "
            f"in {where} appear only where they also register in the US, so this list is skewed "
            f"toward US investors — that is a limit of what we have read, not a finding about who "
            f"funds companies in {where}.")
