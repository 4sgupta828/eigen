"""Task 4 capstone — the population-query ANSWER ROUTE.

`answer_from_population(...)` answers a landscape/population question END TO END,
GROUNDED, by querying the POPULATION (the accumulated claim graph) rather than a
retrieval sample:

    distinct_categories (scope) → population_claims (grounded companies × cells)
      → build_market_map (per-cell CITED market map)
      → empty-population honest fail-safe (never fabricate)
      → render map + numbered citation panel
      → llm.complete compose (TECH_POPULATION_COMPOSE_PROMPT)   [LLM owns prose]
      → CITATION VALIDATION gate (every surviving [cN] must resolve)  [code owns it]
      → derive() + _render_derivations (grounded reasoning layer)
      → coverage_basis (structured coverage facts)

Grounding is the moat: the compose prompt forbids any uncited proper noun (prompt-
enforced, measured by the live eval), the citation gate GUARANTEES every surviving
`[cN]` resolves to a real citation (code-enforced), and an empty population returns an
HONEST no-data answer rather than parametric fabrication. Fail-safe throughout — an
LLM/DB error returns a clear error dict, never a made-up answer.

Rule 18 split: the LLM owns the meaning/prose; CODE owns the citation-resolution gate
and the coverage facts. Not wired into the main `_do_research` path — it is a separate,
flag-gated endpoint so the OFF path stays byte-identical.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel

from api.claimgraph import ClaimGraphStore
from eigen_kernel.research.reason import derive
from eigen_kernel.runtime.research import _render_derivations
from eigen_vertical_tech.claim_predicates import SLICE1_PREDICATES
from eigen_vertical_tech.landscape_map import build_market_map
from eigen_vertical_tech.population_compose import (
    TECH_POPULATION_COMPOSE_PROMPT,
    render_coverage_facts,
    render_market_map_for_compose,
)

_log = logging.getLogger(__name__)

# Matches a citation marker like `[c12]` (the ids build_market_map assigns are c1, c2…).
_CITE_RE = re.compile(r"\[(c\d+)\]")

_POPULATION_STATEMENT = (
    "This map reflects the grounded company population materialized into the claim "
    "graph as of ingest (companies with active-evidence claims only) — NOT all "
    "startups in the market.")


class _PopulationAnswer(BaseModel):
    """Prose compose output — matches the `_PlainAnswer` shape research.py uses so the
    `llm.complete(..., response_format=…)` call is identical in kind."""
    text: str


@dataclass
class _Finding:
    """Duck-typed finding for `derive()` (it reads `.text` and `.quote`). One per
    citation so every derivation rests on a grounded, cited fact."""
    text: str
    quote: str


def _validate_citations(answer: str, valid_ids: set[str]) -> tuple[str, int]:
    """CODE GATE (Rule 18): every `[cN]` marker in the composed answer must resolve to a
    real citation id from the panel. A marker that does not is a HALLUCINATED reference —
    strip that bracket token from the answer and count it. Returns (cleaned, n_dropped).

    This does NOT catch an UNCITED proper noun (that is what the live eval measures), but
    it GUARANTEES that every surviving `[cN]` in the answer resolves to a stored quote."""
    dropped = 0

    def _sub(m: "re.Match[str]") -> str:
        nonlocal dropped
        if m.group(1) in valid_ids:
            return m.group(0)
        dropped += 1
        return ""

    cleaned = _CITE_RE.sub(_sub, answer or "")
    return cleaned, dropped


def _company_names(market_map: dict) -> dict[str, str]:
    names: dict[str, str] = {}
    for cat in market_map.get("categories") or []:
        for comp in cat.get("companies") or []:
            eid, nm = comp.get("entity_id") or "", comp.get("name") or ""
            if eid and nm:
                names[eid] = nm
    return names


async def answer_from_population(*, question: str, tenant_id: str, dsn: str, llm,
                                 top_categories: int = 12, company_cap: int = 400,
                                 judge_llm=None) -> dict:
    """End-to-end grounded population answer. Returns
      {answer, citations, stats, coverage_basis, n_uncited_dropped, meta,
       derivations_rendered}.
    On an unrecoverable error, returns {error, answer:"", ...} — never a fabricated
    answer. See module docstring for the pipeline + grounding contract."""
    store = ClaimGraphStore(dsn)
    try:
        # 1) SCOPE — the top-N categories by member count (compact map for slice 1).
        cats = await store.distinct_categories(tenant_id=tenant_id)
        scope = cats[:top_categories] if top_categories and top_categories > 0 else cats
        scope_norms = [c["object_norm"] for c in scope] or None

        # 2) POPULATION — grounded companies × their cited cells → market map.
        pop = await store.population_claims(
            tenant_id=tenant_id, category_norms=scope_norms, company_cap=company_cap)
        market_map = build_market_map(pop["companies"], predicates=SLICE1_PREDICATES)

        citations = market_map.get("citations") or []
        stats = market_map.get("stats") or {}

        # coverage_basis: structured facts (the compose ALSO emits a `## Coverage basis`,
        # but the caller gets the facts too). Assembled from cats + pop meta + the honest
        # population statement.
        coverage_basis = {
            "categories_covered": [c["name"] for c in scope],
            "n_categories_total": len(cats),
            "n_categories_in_scope": len(scope),
            "n_companies": stats.get("n_companies", 0),
            "truncation": pop.get("meta") or {},
            "population_statement": _POPULATION_STATEMENT,
            "tenant_id": tenant_id,
        }

        # 3) EMPTY-POPULATION FAIL-SAFE — honest no-data, never parametric fabrication.
        if not market_map.get("categories") or not citations:
            answer = (
                f"No grounded startup population has been ingested into the claim graph "
                f"yet for tenant '{tenant_id}' — there is nothing to map. Once companies "
                f"are extracted into the graph (grounded, with cited evidence), this route "
                f"will cluster them by market category with a citation for every fact.")
            return {
                "answer": answer,
                "citations": [],
                "stats": stats,
                "coverage_basis": coverage_basis,
                "n_uncited_dropped": 0,
                "meta": pop.get("meta") or {},
                "derivations_rendered": "",
                "empty_population": True,
            }

        # 4) COMPOSE — self-contained population-compose prompt as system; rendered map +
        #    citation panel + question + coverage facts as user (match research.py shape).
        rendered_map = render_market_map_for_compose(market_map)
        coverage_facts = render_coverage_facts(coverage_basis)
        user = (f"QUESTION:\n{question}\n\n{rendered_map}\n\n{coverage_facts}")
        comp = await llm.complete(
            system=TECH_POPULATION_COMPOSE_PROMPT,
            messages=[{"role": "user", "content": user}],
            response_format=_PopulationAnswer, max_tokens=4000)
        answer = (comp.parsed.text or "").strip()

        # 5) CITATION VALIDATION GATE (code) — drop any hallucinated `[cN]`.
        valid_ids = {c.get("citation_id") for c in citations if c.get("citation_id")}
        answer, n_dropped = _validate_citations(answer, valid_ids)

        # 6) DERIVE — grounded reasoning layer over the cited facts (additive; a failure
        #    never sinks the answer). Each finding is one citation (text + verbatim quote).
        derivations_rendered = ""
        try:
            names = _company_names(market_map)
            findings = [
                _Finding(
                    text=(f"{names.get(c.get('entity_id') or '', c.get('entity_id') or '')} "
                          f"— {c.get('predicate') or ''}: {c.get('object') or ''}").strip(),
                    quote=c.get("quote") or "")
                for c in citations]
            ds = await derive(question, findings, llm, judge_llm=judge_llm)
            section = _render_derivations(ds)
            if section:
                derivations_rendered = section
                answer = (answer.rstrip() + "\n\n" + section)
        except Exception as e:   # noqa: BLE001 — reasoning is additive, never break the answer
            _log.warning("population_route: derive failed (%s)", str(e)[:120])

        return {
            "answer": answer,
            "citations": citations,
            "stats": stats,
            "coverage_basis": coverage_basis,
            "n_uncited_dropped": n_dropped,
            "meta": pop.get("meta") or {},
            "derivations_rendered": derivations_rendered,
            "empty_population": False,
        }
    except Exception as e:   # noqa: BLE001 — fail-safe: a clear error, never a fabricated answer
        _log.warning("population_route: answer_from_population failed (%s)", str(e)[:200])
        return {
            "answer": "",
            "citations": [],
            "stats": {},
            "coverage_basis": {},
            "n_uncited_dropped": 0,
            "meta": {},
            "derivations_rendered": "",
            "error": f"{type(e).__name__}: {e}",
        }
    finally:
        try:
            await store.close()
        except Exception:   # noqa: BLE001
            pass
