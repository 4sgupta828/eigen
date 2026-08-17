# Eigen — Download Campaign: BLOCKED items (do after the easy tranches)

Living tracker. The easy/priority tranches run via `scripts/run_downloads.py` (prod-direct
`/admin/corpus/ingest`). These items are **blocked on external access or a missing connector** —
we do NOT block the campaign on them; we keep downloading everything else and come back here.

Status legend: 🔴 blocked (needs access/build) · 🟡 partial (works but throttled/thin) · 🟢 unblocked.

| # | Source | Value | Blocker | Unblock step | Status |
|---|--------|-------|---------|--------------|--------|
| 1 | **Patents (USPTO PatentsView)** | Granted patents = IP-moat / prior-art evidence (`primary_filing` when granted). | PatentsView **suspended new API-key grants** (confirmed Aug 2026); `connectors/patentsview.py` is DORMANT. | Switch source: **Google Patents Public Data** (BigQuery `patents-public-data`, no key, bulk) OR **EPO OPS** (free tier, register app) OR **USPTO bulk data** (PatentsView bulk TSV downloads, no key). Build a `google_patents`/`epo_ops` connector reusing the granted-vs-pending → tier mapping. | 🔴 |
| 2 | **Semantic Scholar (S2 Graph API)** | Citation graph + strong CS/AI coverage; complements OpenAlex. | No connector built yet. | Build `connectors/semantic_scholar.py` (discover→list→fetch); free, optional API key for higher rate. DOI-dedup vs arXiv+OpenAlex. | 🔴 |
| 3 | **Crossref** | DOI/venue authority metadata. | No connector built. | Build `connectors/crossref.py` (REST, `mailto` polite pool). Mostly metadata — lower priority than S2. | 🔴 |
| 4 | **News / sentiment — GDELT** | Market sentiment / news tone (`sentiment_signal`, lowest tier, never controlling). | GDELT hard-throttles bulk (≈1 req/5s, IP bans); connector is best-effort. **Deferred by design** (corpus-first defers sentiment). | Run in small, paced batches later, or use the GDELT 2.0 DOC API with tight rate limits; keep it labeled signal only. | 🟡 |
| 5 | **Hacker News (Firebase API)** | Developer sentiment / launches (`sentiment_signal`). | Deferred by design (sentiment tier); no connector built. | Build a small `hackernews` connector later; label as signal, never fact. | 🟡 |
| 6 | **Commercial DBs — Crunchbase / PitchBook / Dealroom / CB Insights** | Private funding rounds, cap tables, investor lists — the deepest private-diligence data. | Paid/licensed; no connector can legally fetch. | Product/licensing decision. Until then these stay **recommend-only** in the gap prompt (`gaps.py`). | 🔴 |
| 7 | **Product Hunt / Gartner / IDC** | Launch traction / analyst reports. | Paid or ToS-restricted. | Recommend-only. | 🔴 |

## Notes
- **Form D** (private raises) is NOT blocked — the EDGAR connector fetches it via full-text search
  by name (`forms:["D"]`); it runs in the easy tranches.
- **DOI-dedup arXiv↔OpenAlex** is a code quality fix (not a download blocker) — track separately;
  currently the same paper can embed twice at two tiers.
