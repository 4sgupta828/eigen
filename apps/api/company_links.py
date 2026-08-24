"""Company hyperlinks with recall (user-chosen: 'link known + web-search unknowns').

The LLM identifies which spans in the answer are COMPANIES (Rule 18 — the model owns the
semantic 'is this a company' decision; a regex/registry-substring matcher would mis-fire on
common words). Each detected company is then resolved STRUCTURALLY:
  - KNOWN (an active entity in our claim graph, exact normalized-name match) → its grounded
    canonical page + the in-product /entity page.
  - UNKNOWN → a scoped web search for that company name (honest 'find more' — NEVER a guessed
    homepage, which we couldn't ground).

Returns [{name, url, eigen_url?, grounded: bool}] where `name` is the EXACT surface form as it
appears in the answer (so the FE can first-occurrence match it). Best-effort: any failure → [].
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from pydantic import BaseModel

_DETECT_SYSTEM = (
    "You extract the COMPANIES / startups / organizations that are discussed as SUBJECTS in the "
    "text below. Return each company's name EXACTLY as it appears in the text (same surface form, "
    "same casing), deduplicated. INCLUDE real companies, startups, labs, and funds. EXCLUDE: "
    "products/models (e.g. GPT-4, Claude), technologies, methods, benchmarks, people's names, "
    "government bodies, generic terms, and any name not written verbatim in the text. If none, "
    "return an empty list.")


class _Companies(BaseModel):
    companies: list[str] = []


def _web_search_url(name: str) -> str:
    return "https://www.google.com/search?q=" + urllib.parse.quote(name)


async def detect_and_resolve_companies(service, store, *, answer: str, ui=None,
                                       tenant_id: str = "demo", max_companies: int = 20) -> list[dict]:
    """LLM-detect companies in `answer`, resolve each to a link. Never raises."""
    text = (answer or "").strip()
    if not text or getattr(service, "llm", None) is None:
        return []
    try:
        comp = await service.llm.complete(
            system=_DETECT_SYSTEM,
            messages=[{"role": "user", "content": text[:8000]}],
            response_format=_Companies, max_tokens=400)
        names = list(getattr(comp.parsed, "companies", []) or [])
    except Exception:  # noqa: BLE001 — best-effort; detection failure must not break the answer
        return []
    # keep only names that ACTUALLY appear verbatim in the answer (the FE matches on this), deduped
    seen: set = set()
    surface: list[str] = []
    for nm in names:
        nm = (nm or "").strip()
        if not nm or nm.lower() in seen:
            continue
        if nm in text:                      # exact surface form present → the FE can link it
            seen.add(nm.lower())
            surface.append(nm)
        if len(surface) >= max_companies:
            break
    if not surface:
        return []

    # resolve against the graph registry (one query), exact normalized-name match
    registry: dict[str, dict] = {}
    if store is not None:
        try:
            from api.claimgraph import normalize_name
            registry = await store.company_norm_map(tenant_id=tenant_id)
        except Exception:  # noqa: BLE001
            registry = {}
    else:
        def normalize_name(s):  # type: ignore
            return (s or "").lower().strip()

    out: list[dict] = []
    for nm in surface:
        key = normalize_name(nm) if registry else nm.lower()
        known = registry.get(key)
        if known:
            eid = known["entity_id"]
            try:
                page = ui.source_url(eid) if ui else None
            except Exception:  # noqa: BLE001
                page = None
            out.append({"name": nm, "entity_id": eid,
                        "url": page or ("/entity/" + urllib.parse.quote(eid, safe="")),
                        "eigen_url": "/entity/" + urllib.parse.quote(eid, safe=""),
                        "grounded": True})
        else:
            out.append({"name": nm, "url": _web_search_url(nm), "grounded": False})
    return out
