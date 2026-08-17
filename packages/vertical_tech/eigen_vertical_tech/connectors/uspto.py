"""USPTO connector — US patents via the USPTO Open Data Portal (ODP / "PatentSearch").

REPLACES the dormant PatentsView connector (PatentsView suspended issuing new API keys). Same
KEYED, fail-safe contract: reads EIGEN_USPTO_KEY and sends it as the `X-API-KEY` header; without
a key the connector WARNS and discover_entities returns [] (inert — never errors an ingest job).

Evidence tiering is unchanged and delegated to the shared `patent_doc` module: a GRANTED patent is
a legal record → `primary_filing`; a pre-grant APPLICATION is intent, not fact → `technical_signal`
(evidence_kind reads facets `source_kind=patent` + `grant_status`). We read the DECLARED grant
status from the record; we never infer meaning (Rule 18).

discover_entities({"query": topic | assignee, "limit": N}) searches live (limit capped at 50).
Tests inject `patents` (already in patent_doc shape) so they run fully offline.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse

from eigen_kernel.contract.dto import DocumentRef, EntityRef

from .. import patent_doc
from ._http import HttpStrategy

# ─── LIVE-API SINGLE POINT OF CHANGE ────────────────────────────────────────────────────────────
# USPTO Open Data Portal patent-search endpoint. The ODP docs are JS-rendered (not machine-fetchable
# at build time), so the exact search path + raw field names below are the ONE place to adjust once
# confirmed against https://data.uspto.gov/apis (the offline contract does NOT depend on these — all
# tests inject already-normalized fixtures and never hit the network). ODP is a POST-body search API.
SEARCH_URL = "https://api.uspto.gov/api/v1/patent/applications/search"
KEY_HEADER = "X-API-KEY"


def _granted(rec: dict) -> bool:
    """Structural read of the record's declared grant status — NOT a semantic inference."""
    gs = str(rec.get("grant_status") or "").lower()
    return gs in ("granted", "grant", "true", "1", "yes")


def _normalize(raw: dict) -> dict:
    """Map ONE raw USPTO ODP record → patent_doc's expected shape. IDEMPOTENT.

    Injected fixtures are already in patent_doc shape (they carry `patent_title`/`assignees`), so
    they pass straight through unchanged. Live ODP records are mapped here — this mapping is the
    single point of change if ODP field names differ from the assumptions below.
    """
    # Already normalized (fixture or a prior pass) → return as-is (idempotent).
    if "patent_title" in raw and "assignees" in raw:
        return raw

    # ── ODP raw → patent_doc keys (adjust here once ODP field names are confirmed) ──
    num = raw.get("patentNumber") or raw.get("patent_number") or raw.get("documentNumber") \
        or raw.get("applicationNumberText") or raw.get("document_number")
    title = raw.get("inventionTitle") or raw.get("invention_title") or raw.get("patentTitle") \
        or raw.get("title")
    abstract = raw.get("abstractText") or raw.get("abstract") or raw.get("patent_abstract")
    date = raw.get("grantDate") or raw.get("patentIssueDate") or raw.get("publicationDate") \
        or raw.get("filingDate") or raw.get("patent_date")

    # Assignees / applicants → list[{"assignee_organization": org}] (patent_doc reads that shape).
    assignees: list[dict] = []
    for a in (raw.get("assignees") or raw.get("assigneeBag")
              or raw.get("applicants") or raw.get("applicantBag") or []):
        if isinstance(a, dict):
            org = a.get("assignee_organization") or a.get("organizationName") \
                or a.get("applicantNameText") or a.get("name")
            if org:
                assignees.append({"assignee_organization": str(org)})
        elif isinstance(a, str) and a.strip():
            assignees.append({"assignee_organization": a.strip()})

    # grant vs pre-grant publication → grant_status ("granted" | "application"). A granted patent
    # carries a grant/issue date or an explicit grant flag; otherwise it is a pre-grant publication.
    is_grant = bool(raw.get("grantDate") or raw.get("patentIssueDate")) \
        or str(raw.get("documentKind") or raw.get("kindCode") or "").upper().startswith("B") \
        or str(raw.get("recordType") or "").lower() in ("grant", "granted")
    grant_status = "granted" if is_grant else "application"

    rec = {
        "patent_id": str(num or "").strip(),
        "patent_title": str(title or "").strip(),
        "assignees": assignees,
        "grant_status": grant_status,
        "patent_date": str(date or ""),
    }
    if abstract:
        rec["patent_abstract"] = str(abstract).strip()
    for cpc_key in ("cpc_current", "cpcs"):
        if raw.get(cpc_key):
            rec[cpc_key] = raw[cpc_key]
    return rec


_log = logging.getLogger(__name__)


class UsptoConnector:
    key = "uspto"

    def __init__(self, *, patents: list[dict] | None = None, page_size: int = 20):
        self.fetch_strategy = HttpStrategy(base_delay=2.0, max_retries=4)
        self._page_size = page_size
        self._key = os.environ.get("EIGEN_USPTO_KEY", "")
        self._by_id: dict[str, dict] = {}
        for p in (patents or []):
            rec = _normalize(p)
            pid = patent_doc.patent_id(rec)
            if pid:
                self._by_id[pid] = rec

    async def _search(self, query: str, limit: int) -> list[dict]:
        if not self._key:
            _log.warning("uspto: EIGEN_USPTO_KEY not set — skipping (no patents ingested)")
            return []
        n = min(50, max(1, limit))
        # ODP is a POST-body search; HttpStrategy is GET-only, so pass the query as URL params and
        # let the ODP gateway accept them (single point of change — adjust with SEARCH_URL above).
        params = {"q": query, "rows": n}
        url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
        raw = await self.fetch_strategy.fetch(url, headers={KEY_HEADER: self._key})
        data = json.loads(raw)
        records = data.get("patentBag") or data.get("results") or data.get("patents") or []
        return [_normalize(r) for r in records if isinstance(r, dict)][:limit]

    async def discover_entities(self, window: dict) -> list[EntityRef]:
        win = window or {}
        q = str(win.get("query") or "").strip()
        if not q and self._by_id:
            recs = list(self._by_id.values())
        elif q:
            limit = int(win.get("limit", self._page_size))
            recs = await self._search(q, limit)
            for r in recs:
                pid = patent_doc.patent_id(r)
                if pid:
                    self._by_id[pid] = r
        else:
            recs = []
        return [EntityRef(source_key=self.key, native_id=patent_doc.patent_id(r),
                          title=patent_doc.title(r),
                          facets=patent_doc.facets(r, granted=_granted(r)))
                for r in recs if patent_doc.patent_id(r)]

    async def list_documents(self, entity: EntityRef) -> list[DocumentRef]:
        p = self._by_id.get(entity.native_id)
        facets = patent_doc.facets(p, granted=_granted(p)) if p else dict(entity.facets)
        return [DocumentRef(source_key=self.key, native_id=entity.native_id, title=entity.title,
                            content_type="text/markdown", facets=facets,
                            entity_ids=(entity.native_id,))]

    async def fetch_artifact(self, doc: DocumentRef) -> bytes:
        p = self._by_id.get(doc.native_id) or {"patent_id": doc.native_id}
        return patent_doc.to_markdown(p, granted=_granted(p)).encode("utf-8")
