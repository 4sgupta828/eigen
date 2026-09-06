"""Startup Search — a detached feature: a grounded, public-source startup index with typed facets, a brief →
contract compiler, a deterministic evaluator (kernel `eigen_kernel.facets`) and card results.

Layout: `schema.py` (the vocabulary), `store.py` (tables + the facet store adapter), `sources/` (YC, SEC Form D
bulk, ATS boards, company sites), `extract.py` (DeepSeek schema-driven extraction with verbatim-quote gates),
`resolve.py` (Form D issuer ↔ company), `derive.py` (computed facets with a `basis`), `compile.py` (brief →
contract), `routes.py` (the API). Spec: docs/specs/startup-search.md."""
