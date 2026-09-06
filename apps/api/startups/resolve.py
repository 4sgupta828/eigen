"""Form D issuer → company resolution (the whole game for funding; spec §4.1).

Order: (1) CIK already on the company → exact, permanent; (2) exact normalised legal / product / alias name
match AND a compatible location (same US state, or the company's HQ text names the filing's city or state) →
`exact_name`; (3) a name match without location agreement, or several candidates → the model judges
"same operating company?" from the filing's identity fields against the candidate's one-liner + HQ (a gated
call with a confidence threshold) → `llm_merge`; otherwise the filing stays unmatched. Pooled funds and vehicles
never reach here (`is_operating`). A rejected judgment is recorded so it is never re-asked."""
from __future__ import annotations

import json
import re

from .sources.formd import name_norm

STATE_IN_HQ = re.compile(r"\b([A-Z]{2})\b")


def _hq_matches(hq: str, city: str, state: str) -> bool:
    h = (hq or "").lower()
    if not h:
        return False
    if city and city.lower() in h:
        return True
    return bool(state) and bool(re.search(r"\b" + re.escape(state.upper()) + r"\b", hq or ""))


def candidates_for(filing: dict, companies: list[dict]) -> list[dict]:
    """Companies whose normalised name / legal name / alias equals the filing's normalised name (or a previous name)."""
    names = {filing.get("name_norm") or ""} | {name_norm(p) for p in (filing.get("previous_names") or [])}
    names.discard("")
    out = []
    for c in companies:
        cn = {name_norm(c.get("name") or ""), name_norm(c.get("legal_name") or "")} | {name_norm(a) for a in (c.get("aliases") or [])}
        cn.discard("")
        if cn & names:
            out.append(c)
    return out


def decide_structural(filing: dict, cands: list[dict]) -> tuple[str, dict | None]:
    """('cik'|'exact_name'|'ambiguous'|'none', company)."""
    cik = filing.get("cik") or ""
    for c in cands:
        if cik and c.get("cik") == cik:
            return "cik", c
    located = [c for c in cands if _hq_matches(c.get("hq") or "", filing.get("city") or "", filing.get("state") or "")]
    if len(located) == 1:
        return "exact_name", located[0]
    if len(cands) == 1 and not (cands[0].get("hq") or "").strip():
        return "ambiguous", cands[0]          # a name match with no location to check → ask the model
    if cands:
        return "ambiguous", None
    return "none", None


MERGE_SYSTEM = """You decide whether an SEC Form D filing's issuer is the SAME operating company as a candidate startup.
Use only the fields given. Answer strict JSON: {"same": true|false, "confidence": 0..1, "reason": "<one line>"}.
How to read the fields: the filing's address is often a registered agent or law firm (Dover / Wilmington, DE; a
"c/o" address) or the US entity of a startup headquartered abroad — an address mismatch alone is NOT evidence of a
different company. The same distinctive name + a compatible industry group (Other Technology for software, Other
Health Care for health, etc.) + a plausible incorporation year (at or before the YC batch year) → same, confidence
≥ 0.8. Different: a generic name shared by unrelated businesses in another industry, or an incorporation year long
after the startup's batch, or a fund / SPV / "a series of" vehicle (never an operating company)."""


async def judge_merge(llm_json, filing: dict, cand: dict) -> tuple[bool, float, str]:
    user = json.dumps({"filing": {k: filing.get(k) for k in ("entity_name", "previous_names", "city", "state", "entity_type", "year_inc", "industry")},
                       "candidate": {k: cand.get(k) for k in ("name", "legal_name", "hq", "one_liner", "yc_batch", "website")}}, ensure_ascii=False)
    try:
        out = await llm_json(MERGE_SYSTEM, user)
        return bool(out.get("same")), float(out.get("confidence") or 0.0), str(out.get("reason") or "")[:200]
    except Exception:   # noqa: BLE001
        return False, 0.0, "judge_failed"
