# Deploying Noesis

One vertical per deployment. The image serves the API + research console.

## Env vars

| Var | Purpose | Example |
|---|---|---|
| `EIGEN_ACTIVE_VERTICAL` | which installed vertical to activate | `medical` |
| `EIGEN_PROVIDER_MODE` | `replay` (offline/free) · `record` (real + save cassette) · `live` (real) | `live` in prod |
| `PORT` | HTTP port | `8000` (Railway sets this) |
| `ANTHROPIC_API_KEY` | LLM (record/live only) | secret |
| `OPENAI_API_KEY` | embeddings (record/live only) | secret |
| `TAVILY_API_KEY` | web search (record/live only) | secret |
| `EIGEN_LLM_MODEL` | override the Anthropic model | `claude-sonnet-5` |
| `EIGEN_CORPUS_DSN` | Postgres+pgvector DSN for the corpus (when wired) | `postgresql://…` |
| `EIGEN_CASSETTE_ROOT` | where cassettes live (replay/record) | `evals/cassettes` |

## Railway

1. New service from this repo (root `railway.toml` builds `deploy/Dockerfile`).
2. Set `EIGEN_ACTIVE_VERTICAL`, `EIGEN_PROVIDER_MODE=live`, and the API keys.
3. Add a Postgres (pgvector) service; set `EIGEN_CORPUS_DSN`.
4. Healthcheck is `/health`; the console is at `/`.

## Local

```bash
EIGEN_ACTIVE_VERTICAL=medical EIGEN_PROVIDER_MODE=replay \
  PYTHONPATH=packages/kernel:packages/vertical_medical:apps \
  .venv/bin/uvicorn api.app:create_app --factory --port 8000
```

## Notes / not-yet-wired
- The default corpus is the vertical's **fixture** until real ingestion → Postgres
  (with OpenAI embeddings) is wired; `/research` in `live` mode already produces
  real answers over it.
- `replay` needs recorded cassettes under `EIGEN_CASSETTE_ROOT`; `live` needs the
  API keys but no cassettes.

## Medical vertical — data infra (added)

- **Dedicated DB:** a fresh pgvector Postgres (container `noesis-db`, port 5434) —
  separate from any other project. `EIGEN_CORPUS_DSN=postgresql://noesis:noesis@localhost:5434/noesis`.
- **Object store (R2):** raw fetched artifacts (assembled trial/label markdown) are
  content-addressed into Cloudflare R2 via `S3ObjectStore`. Env: `R2_BUCKET`,
  `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (see gitignored `.env.medical`).
- **Embeddings:** OpenAI `text-embedding-3-small` (1536-d) — `OPENAI_API_KEY`.
- **Download real data:**
  ```bash
  set -a; . ./.env.medical; set +a
  PYTHONPATH=packages/kernel:packages/vertical_medical:apps \
    .venv/bin/python scripts/ingest_medical.py --condition diabetes --trials 100 --drugs 100 --drug-query "openfda.route:ORAL"
  ```
  Sources: ClinicalTrials.gov v2 (trials) + openFDA drug labels. Raw → R2, index → pgvector.
