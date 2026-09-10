"""Brief → contract for Investor Search (the only model call at search time; the route caches by text hash).

Two rules this compiler has that the startup one does not, both from docs/specs/investors.md:

1. **A must on a STATED key filters what a firm CLAIMS, and the note says so.** "Writes $500k cheques" can only
   ever match firms whose own site states a range, so the note carries the known-rate rather than letting the
   user believe they filtered the market.
2. **A track-record filter is refused outright.** Our view of any portfolio is a biased subset, so a "good
   returns" must would rank firms by our own coverage. The brief comes back with what IS answerable instead:
   has filed a fund recently, and has a fund a public LP reports returns for.
"""
from __future__ import annotations

import json
import re

from eigen_kernel.facets import Contract, FacetType, validate_contract
from eigen_kernel.facets.lexicon import (claimed_by_filters, find_spans, may_blank_text, plan_from_spans)

from .query_lexicon import config as lexicon_config
from .schema import KIND, REGISTER, SCHEMA, UNIFIED

COVERAGE_FLOOR = 0.5
# `country` is on most briefs and narrows little; it does not count as "something that filters" when
# deciding whether the words may be dropped.
SCOPE_KEYS = ("country",)
MIN_MUST_SUPPORT = 15       # a categorical must stays a must when at least this many firms carry the values

# Phrases that ask for a track record. There is no public source for one, so they become a note, never a filter.
TRACK_RECORD = re.compile(r"(?i)\b(track record|success rate|hit rate|best[\w\s]{0,12}(return|perform)\w*"
                          r"|top.?(tier|quartile)|good returns?|winning|outperform|most successful"
                          r"|highest[\w\s]{0,10}return\w*|irr|dpi|tvpi|moic)\b")
TRACK_RECORD_NOTE = ("Track record is not searchable here — no public source supports it, and measuring it over "
                     "the slice of a portfolio we happen to see would flatter every firm. The closest honest "
                     "filters are 'still deploying' (they filed a fund recently) and 'a public LP reports "
                     "returns for one of their funds'.")


def system_prompt() -> str:
    return f"""You compile a search brief about INVESTORS (venture funds, PE firms, angels) into a filter contract, as strict JSON:
{{"text": "<the semantic gist for similarity search, 3-12 words, no filters restated>",
 "must": {{"<key>": ["<value>", ...] | {{"min": <number>, "max": <number>}}}},
 "must_not": {{"<key>": ["<value>"]}},
 "prefer": {{"<key>": ["<value>", ...]}},
 "avoid": {{"<key>": ["<value>", ...]}},
 "rank_by": "match" | "<numeric or ordinal key>",
 "notes": ["<ONLY a requirement the keys cannot express, in the user's words; never an explanation of your choices; usually empty>"]}}

Rules:
- Only the keys and values listed below. A must is what the brief states as a hard requirement ("only", "must",
  "at least", "$50M+", a named geography); what it merely describes is a prefer. "not X" / "no X" → must_not.
- Money keys take USD ("$250k" is 250000, "$50M" is 50000000). Year keys take a year. Percentages take a number.
- STAGE: the brief's stage words go in `stated_stage` (pre_seed seed series_a series_b series_c growth all).
  One control covers both what a firm SAYS and what it DOES, so never put a stage in `observed_stage` yourself.
  Likewise put sectors in `sector_focus` and geographies they invest in in `geo_focus` — not the observed twins.
- WHERE THEY ARE versus WHERE THEY INVEST are different: "London funds" is country/metro; "funds investing in
  India" is geo_focus. If the brief is ambiguous, use geo_focus.
- "still raising" / "active" / "deploying" → still_deploying: yes_recent. "dormant"/"quiet" → quiet.
- CHEQUE SIZE: "writes $1-3M cheques" → stated_check_min min 1000000, stated_check_max max 3000000.
- NEVER compile a track record, returns, success rate, IRR or "top tier" into any key. There is no such key.
- Do not invent values the brief does not imply.

The user message may carry `words_that_name_a_filter`: spans of the brief that are legal values of the
vocabulary below, found by looking the words up. They are CANDIDATES, not decisions — confirm one by
putting it under the right key, reject it by leaving it out. You see the sentence; the lookup saw words.

Examples:
brief: "seed funds that lead in AI infra, US or Europe, $50-250M latest fund, still deploying, not corporate VC"
{{"text":"AI infrastructure seed investors","must":{{"stated_stage":["seed"],"sector_focus":["ai_infra"],
 "geo_focus":["us","europe"],"latest_fund_size":{{"min":50000000,"max":250000000}},"still_deploying":["yes_recent"]}},
 "must_not":{{"investor_type":["corporate_vc"]}},"prefer":{{"leads_rounds":["leads"]}},"rank_by":"match","notes":[]}}

brief: "who funds pre-seed fintech in India and writes 250k cheques"
{{"text":"pre-seed fintech investors in India","must":{{"stated_stage":["pre_seed"],"sector_focus":["fintech"],
 "geo_focus":["in"]}},"prefer":{{"stated_check_min":[]}},"rank_by":"match","notes":[]}}

The keys:
{SCHEMA.to_prompt_block(KIND)}"""


def _clean_map(m, *, numeric_ok: bool) -> dict:
    """Keep only real keys and legal values; drop the rest silently (the model occasionally invents a key)."""
    out: dict = {}
    for key, vals in (m or {}).items():
        k = SCHEMA.key(key)
        if k is None:
            continue
        if isinstance(vals, dict):
            if not numeric_ok or k.type is not FacetType.numeric:
                continue
            lo, hi = vals.get("min"), vals.get("max")
            rng = {}
            for name, v in (("min", lo), ("max", hi)):
                try:
                    if v is not None:
                        rng[name] = float(v)
                except (TypeError, ValueError):
                    continue
            if rng:
                out[key] = rng
            continue
        keep = []
        for v in (vals if isinstance(vals, (list, tuple)) else [vals]):
            got = SCHEMA.validate_value(key, v)
            if got and got not in keep:
                keep.append(got)
        if keep:
            out[key] = keep
    return out


def build_contract(out: dict, *, coverage: dict | None = None, value_counts: dict | None = None,
                   limit: int = 60, brief: str = "") -> tuple[Contract, list[str]]:
    """Model JSON → validated Contract + notes. `coverage` is the known-rate per key over the index."""
    notes = [str(n)[:200] for n in (out.get("notes") or [])
             if n and not re.search(r"\b(schema|I'll|I will|I use|so I)\b", str(n))][:4]
    must = _clean_map(out.get("must"), numeric_ok=True)
    prefer = _clean_map(out.get("prefer"), numeric_ok=False)
    avoid = _clean_map(out.get("avoid"), numeric_ok=False)
    exclude = _clean_map(out.get("must_not"), numeric_ok=False)

    if brief and TRACK_RECORD.search(brief):
        notes.insert(0, TRACK_RECORD_NOTE)

    # An observed key is a measurement of our coverage, and the model is told not to use one directly. If it
    # does anyway, move it onto its stated twin, where the unified control matches BOTH registers in SQL.
    for observed, stated in {v: k for k, v in UNIFIED.items()}.items():
        for section in (must, prefer, avoid, exclude):
            if observed in section and isinstance(section[observed], list):
                section.setdefault(stated, [])
                section[stated] = sorted(set(section[stated]) | set(section.pop(observed)))

    # No coverage table means we do not KNOW what the index covers — and "unknown coverage" must not be read
    # as "covered by nobody", or a failed coverage read would silently turn every must into a preference.
    cov = coverage or {}
    vc = value_counts or {}
    for key in list(must) if cov else ():
        rate = cov.get(key, 0.0)
        label = (SCHEMA.key(key).label or key)
        vals = must[key]
        low = rate < COVERAGE_FLOOR
        # A thin key still filters honestly when the REQUESTED values are well covered.
        if low and isinstance(vals, list) and vc.get(key):
            if sum(int(vc[key].get(v, 0)) for v in vals) >= MIN_MUST_SUPPORT:
                low = False
        if not low:
            continue
        pct = int(rate * 100)
        if REGISTER.get(key) == "stated":
            # Keep the must — it is exactly what was asked — but say what it can see. Before Step 4 has run,
            # the stated register is empty, and a silent must here returns nothing at all.
            notes.append(f"{label}: only {pct}% of investors state this on their own site, so this filter can "
                         f"only see those. Tap the chip to rank by it instead.")
            if pct == 0:
                must.pop(key)
                if isinstance(vals, list):
                    prefer[key] = sorted(set(prefer.get(key, [])) | set(vals))
                notes[-1] = (f"{label}: no investor in the index states this yet — kept as a preference, and the "
                             f"words still rank. (It arrives when the firm-site pass runs.)")
            continue
        if isinstance(vals, dict):
            notes.append(f"{label}: known for {pct}% of investors — this must can only see those")
            continue
        must.pop(key)
        prefer[key] = sorted(set(prefer.get(key, [])) | set(vals))
        notes.append(f"{label}: known for {pct}% of investors — kept as a preference (tap the chip to make it a must)")

    rank_by = str(out.get("rank_by") or "match")
    k = SCHEMA.key(rank_by)
    if rank_by != "match" and (k is None or k.type.value not in ("numeric", "ordinal")):
        rank_by = "match"
    c = Contract(kind=KIND, text=str(out.get("text") or "")[:200], must=must, prefer=prefer, avoid=avoid,
                 rank_by=rank_by, scope={"exclude": exclude} if exclude else {}, limit=limit)
    errs = validate_contract(c, SCHEMA)
    if errs:
        for section in ("must", "prefer", "avoid"):
            setattr(c, section, {kk: vv for kk, vv in getattr(c, section).items()
                                 if not any(f"{section}: " in e and repr(kk) in e for e in errs)})
        if validate_contract(c, SCHEMA):
            c = Contract(kind=KIND, text=c.text, limit=limit)
            notes.append("the brief could not be compiled into filters; ranking by the words alone")
    return c, notes


def lexicon_read(brief: str):
    """The deterministic first read — the facet values in the words themselves, before any model call."""
    if not (brief or "").strip():
        return None
    try:
        cfg = lexicon_config()
        spans = find_spans(brief, SCHEMA, KIND, aliases=cfg["aliases"])
        if not spans:
            return None
        return plan_from_spans(brief, spans, filler=cfg["filler"], must_keys=cfg["must_keys"],
                               risky_values=cfg["risky_values"])
    except Exception:      # noqa: BLE001 — a lexicon that cannot read must never fail a search
        return None


def apply_lexicon(c: Contract, plan) -> list[str]:
    """Fold the lexicon's read in. The model still wins any key it spoke about."""
    if plan is None:
        return []
    notes = list(plan.notes)
    for key, vals in (plan.must or {}).items():
        if key in c.must or key in c.avoid or key in (c.scope or {}).get("exclude", {}):
            continue
        if key in c.prefer:
            model_vals = c.prefer.get(key)
            if not (isinstance(model_vals, list) and set(vals) & set(model_vals)):
                continue
            c.prefer.pop(key, None)
            c.must[key] = sorted(set(vals) & set(model_vals))
            notes.append(f"you named the {(SCHEMA.key(key).label or key).lower()}, so it filters rather than ranks")
            continue
        c.must[key] = list(vals)
        notes.append(f"read \u201c{(SCHEMA.key(key).label or key).lower()}\u201d straight from your words")
    for key, vals in (plan.prefer or {}).items():
        if key in c.must or key in c.prefer or key in c.avoid:
            continue
        c.prefer[key] = list(vals)
    return notes


def settle_text(c: Contract, brief: str, plan=None) -> list[str]:
    """Drop the semantic text when every word of the brief already became a filter."""
    if not (brief or "").strip() or not c.text:
        return []
    try:
        residual = claimed_by_filters(brief, c, filler=lexicon_config()["filler"],
                                      spans=(plan.spans if plan is not None else None))
        if not may_blank_text(c, residual, scope_keys=SCOPE_KEYS):
            return []
        c.text = ""
        return ["every word of your brief became a filter, so the filters are the search"]
    except Exception:      # noqa: BLE001
        return []


def candidates_for_model(plan) -> list[dict]:
    if plan is None:
        return []
    out = []
    for sp in plan.spans:
        item = {"words": sp.text, "could_be": {sp.key: sp.value}}
        if sp.ambiguous:
            item["or"] = list(sp.ambiguous)
        out.append(item)
    return out[:12]


async def compile_brief(llm_json, text: str, *, coverage: dict | None = None, value_counts: dict | None = None,
                        limit: int = 60) -> tuple[Contract, list[str]]:
    plan = lexicon_read(text)
    payload = {"brief": text[:1500]}
    cands = candidates_for_model(plan)
    if cands:
        payload["words_that_name_a_filter"] = cands
    try:
        out = await llm_json(system_prompt(), json.dumps(payload))
    except Exception:      # noqa: BLE001 — a provider outage falls back to the words, never a 500
        out = {}
    if not isinstance(out, dict):
        out = {}
    if not out.get("text"):
        out["text"] = re.sub(r"\s+", " ", text)[:200]
    c, notes = build_contract(out, coverage=coverage, value_counts=value_counts, limit=limit, brief=text)
    lex = apply_lexicon(c, plan)
    if lex:
        notes = (notes + lex)[:8]
    notes += settle_text(c, text, plan)
    return c, notes
