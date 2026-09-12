"""The case for, and the case against — one reasoned argument per side, per claim.

Evidence rows are not an argument. A reader handed six quotes has to do the reasoning themselves, and
the reasoning is the work: what these sources, taken together, actually imply about this claim, and
where that implication is weak.

So for every claim we write both sides — and the constraint that makes this honest rather than
rhetorical is that **each case may only argue from the evidence it was given**. A side with nothing
behind it says so and stops. That is not a limitation to apologise for: "there is no case to make for
this yet" is the most useful sentence this mode can produce.

One model call for the whole thesis, not one per claim: ten small calls cost ten times as much and
argue each claim without knowing the others, which is how you get a case for rung 3 that contradicts
the case for rung 5.
"""
from __future__ import annotations

import json

MAX_EV_PER_SIDE = 4
MAX_QUOTE = 260

_SYSTEM = """\
You argue both sides of each claim a startup thesis rests on, from evidence only.

For every CLAIM you are given the evidence found FOR it and AGAINST it, each row tagged with its
register: `filed` (regulatory or audited), `stated` (somebody asserting it), `observed` (an artifact
that exists). Some rows are tagged `signal` — forum or news sentiment, which is how people feel and
never what is true.

Write two short cases per claim, two or three sentences each:

- `case_for`: the strongest honest argument that the claim holds, from the FOR rows.
- `case_against`: the strongest honest argument that it does not, from the AGAINST rows.

Rules, in order of importance:
1. ARGUE ONLY FROM THE ROWS GIVEN. Never introduce a fact, a number, a company or a trend that is not
   in them. You have no outside knowledge here.
2. If a side has no rows, write exactly what is missing — "nothing in the record speaks to this" —
   and say what kind of source would. Do not manufacture a case out of plausibility.
3. Weigh the register. A filed number outranks an assertion; an artifact outranks a claim about one;
   `signal` rows may colour a case but can never carry it, and you must say so when they are all you
   have.
4. Name the weakness in your own case. The reader is deciding whether to spend money, not whether you
   sound confident.
5. No hedging language, no "it could be argued", no restating the claim. Plain sentences.

Then say which side the evidence currently favours: "for", "against", or "neither".

Return ONE JSON object exactly matching this schema:

{"cases": [{"rung": "<rung key>", "case_for": "...", "case_against": "...",
            "leans": "for|against|neither"}]}

Output ONLY the JSON object."""


def _rows(evidence: list[dict], side: str) -> str:
    out = []
    for e in (evidence or []):
        if e.get("side") != side:
            continue
        tag = "signal" if e.get("signal_only") else (e.get("register") or "stated")
        who = e.get("said_by") or e.get("source_key") or "source"
        out.append(f"  - [{tag} · {who}] {(e.get('quote') or '')[:MAX_QUOTE]}")
        if len(out) >= MAX_EV_PER_SIDE:
            break
    return "\n".join(out) or "  (no rows)"


def _prompt(thesis: str, claims: list[dict]) -> str:
    blocks = []
    for c in claims:
        ev = c.get("evidence") or []
        blocks.append(f"CLAIM ({c['rung']}): {c['claim']}\n"
                      f" FOR:\n{_rows(ev, 'for')}\n AGAINST:\n{_rows(ev, 'against')}")
    return f"THESIS:\n{thesis}\n\n" + "\n\n".join(blocks) + "\n\nReturn the JSON now."


def project_cost(n_claims: int) -> dict:
    return {"calls": 1, "claims": n_claims, "projected_usd": 0.004}


async def cases_for(llm_json, *, thesis: str, claims: list[dict]) -> dict[str, dict]:
    """-> {rung: {case_for, case_against, leans}}. Never raises; an empty map means the table shows
    its evidence without a written case, which is thinner but never wrong."""
    if llm_json is None or not claims:
        return {}
    try:
        raw = await llm_json(_SYSTEM, _prompt(thesis, claims))
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001
        return {}
    out: dict[str, dict] = {}
    known = {c["rung"] for c in claims}
    for row in (d.get("cases") or []):
        k = str((row or {}).get("rung") or "").strip()
        if k not in known:
            continue
        leans = str(row.get("leans") or "neither").strip().lower()
        out[k] = {"case_for": str(row.get("case_for") or "").strip()[:900],
                  "case_against": str(row.get("case_against") or "").strip()[:900],
                  "leans": leans if leans in ("for", "against", "neither") else "neither"}
    return out
