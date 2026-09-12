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
import re

MAX_EV_PER_SIDE = 4
MAX_QUOTE = 260

_SYSTEM = """\
You argue both sides of each claim a startup thesis rests on, from evidence only.

For every CLAIM you are given the evidence found FOR it and AGAINST it, each row tagged with its
register: `filed` (regulatory or audited), `stated` (somebody asserting it), `observed` (an artifact
that exists). Some rows are tagged `signal` — forum or news sentiment, which is how people feel and
never what is true.

Write two cases per claim, three or four sentences each — an ARGUMENT, not a summary of the rows:

- `case_for`: the strongest honest argument that the claim holds, from the FOR rows.
- `case_against`: the strongest honest argument that it does not, from the AGAINST rows.

CITE. Every sentence that rests on a row ends with its immutable evidence marker exactly as given —
`[[e:abc123]]`, or two markers when two rows carry it. A sentence with no marker is unsupported.
Never invent or alter an evidence ID.

REASON, do not paraphrase. Say what the rows IMPLY for this claim and why: what follows from them,
what the reader should conclude, and how far it generalises beyond the specific case the row
describes. "A source says X" is not an argument. "X means the buyer already has a workaround they are
used to, so the gain has to clear their switching cost, not zero [2]" is.

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

FINALLY, one `overall` reading of the WHOLE thesis that integrates every claim — four to six
sentences. This is the part the reader acts on, so:
- Say where the thesis is strongest and where it is weakest, naming the claims.
- Weigh them: a thesis can survive a weak claim low on the ladder and cannot survive a broken one at
  its centre. Say which kind this is.
- Name what would change your reading — the single piece of evidence that would move it most.
- Be explicit that willingness to pay and switching cost are NOT settled here by anything, because no
  document can settle them. A thesis whose remaining risk is entirely in those two is in a different
  position from one contradicted on the record, and the reader must not confuse them.
- Do not issue a verdict on whether to build it. Say what is known, what is not, and what it costs to
  find out.

Return ONE JSON object exactly matching this schema:

{"cases": [{"rung": "<rung key>", "case_for": "...", "case_against": "...",
            "leans": "for|against|neither"}],
 "overall": "..."}

Output ONLY the JSON object."""


def numbered(evidence: list[dict]) -> list[dict]:
    """Keep the bounded, side-balanced evidence selection used by the prompt."""
    out = []
    for side in ("for", "against"):
        n = 0
        for e in (evidence or []):
            if e.get("side") != side:
                continue
            out.append(e)
            n += 1
            if n >= MAX_EV_PER_SIDE:
                break
    return out


def _rows(evidence: list[dict], side: str) -> str:
    out = []
    for e in numbered(evidence):
        if e.get("side") != side:
            continue
        tag = "signal" if e.get("signal_only") else (e.get("register") or "stated")
        who = e.get("said_by") or e.get("source_key") or "source"
        evidence_id = str(e.get("id") or "")
        gates = e.get("gate_results") or {}
        gate_text = ",".join(f"{key}={'true' if gates.get(key) is True else 'false'}" for key in
                             ("span_ok", "entailed", "on_subject", "kind_ok", "period_ok"))
        identity = " · ".join(filter(None, [str(e.get("source_subject") or ""),
                                             str(e.get("evidence_kind") or ""),
                                             str(e.get("period") or e.get("as_of") or "")]))
        out.append(f"  [[e:{evidence_id}]] ({tag} · {who}"
                   f"{(' · ' + identity) if identity else ''} · {gate_text}) "
                   f"{(e.get('quote') or '')[:MAX_QUOTE]}")
    return "\n".join(out) or "  (no rows)"


_CITE_RE = re.compile(r"\[\[e:([A-Za-z0-9_-]{1,80})\]\]")


def sanitize_case(text: str, allowed_ids: set[str]) -> str:
    """Drop any sentence whose cited source is absent; uncited prose is limited to empty-side copy."""
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        if not sentence:
            continue
        cited = set(_CITE_RE.findall(sentence))
        if cited:
            if cited <= allowed_ids:
                kept.append(sentence)
            continue
        if sentence.lower().startswith("nothing in the record speaks to this"):
            kept.append(sentence)
    return " ".join(kept)[:900]


def _prompt(thesis: str, claims: list[dict]) -> str:
    blocks = []
    for c in claims:
        ev = c.get("evidence") or []
        blocks.append(f"CLAIM ({c['rung']}): {c['claim']}\n"
                      f" FOR:\n{_rows(ev, 'for')}\n AGAINST:\n{_rows(ev, 'against')}")
    return f"THESIS:\n{thesis}\n\n" + "\n\n".join(blocks) + "\n\nReturn the JSON now."


def project_cost(n_claims: int) -> dict:
    return {"calls": 1, "claims": n_claims, "projected_usd": 0.004}


async def cases_for(llm_json, *, thesis: str, claims: list[dict]) -> tuple[dict[str, dict], str]:
    """-> ({rung: {case_for, case_against, leans}}, overall). Never raises; empties mean the table
    shows its evidence without a written case, which is thinner but never wrong."""
    if llm_json is None or not claims:
        return {}, ""
    try:
        raw = await llm_json(_SYSTEM, _prompt(thesis, claims))
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001
        return {}, ""
    out: dict[str, dict] = {}
    by_rung = {c["rung"]: c for c in claims}
    known = set(by_rung)
    for row in (d.get("cases") or []):
        k = str((row or {}).get("rung") or "").strip()
        if k not in known:
            continue
        leans = str(row.get("leans") or "neither").strip().lower()
        allowed = {str(e.get("id") or "") for e in numbered(by_rung[k].get("evidence") or [])
                   if e.get("id")}
        out[k] = {"case_for": sanitize_case(str(row.get("case_for") or ""), allowed),
                  "case_against": sanitize_case(str(row.get("case_against") or ""), allowed),
                  "leans": leans if leans in ("for", "against", "neither") else "neither"}
    return out, str(d.get("overall") or "").strip()[:2000]
