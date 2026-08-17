#!/usr/bin/env python3
"""Eigen download campaign — prod-direct ingest in PRIORITY ORDER (easy sources first).

Enqueues connector jobs against prod `/admin/corpus/ingest`. Ingest cost is embeddings-only
(~$0.02/1M tokens — pennies); the real limits are source rate-limits + time, so the prod worker
paces the queue serially. We do NOT block on unavailable sources (see docs/downloads-blocked.md).

Usage:
  EIGEN_ADMIN_TOKEN=... python scripts/run_downloads.py <tranche> [--limit N] [--dry]
  tranches: depth | formd | openalex | github | all
  --dry prints the jobs without enqueuing.
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.request

PROD = os.environ.get("EIGEN_PROD_URL", "https://eigen-api-production.up.railway.app")

# --- T1a: EDGAR flagship DEPTH (default forms: 10-K/10-Q/S-1/DEF 14A → history + people/comp) ---
# Public leaders across AI, semis, cloud, software, security — deepen the entities we already have.
DEPTH_TICKERS = [
    "NVDA","AMD","INTC","AVGO","MU","QCOM","ARM","MRVL","ON","ADI","TXN","LRCX","AMAT","KLAC","SMCI",
    "MSFT","GOOGL","AMZN","META","AAPL","ORCL","CRM","ADBE","NOW","SNOW","PLTR","AI","PATH","MDB","DDOG",
    "NET","CRWD","PANW","ZS","S","FTNT","OKTA","DELL","HPE","IBM","CSCO","ANET","INTU","WDAY","TEAM",
    # wave 2
    "ADSK","ANSS","CDNS","SNPS","FICO","MSCI","VRSN","AKAM","FFIV","JNPR","HUBS","ZM","DOCU","TWLO",
    "ESTC","GTLB","CFLT","U","RBLX","DASH","ABNB","UBER","SHOP","XYZ","PYPL","COIN","HOOD","SOFI","AFRM",
    "NU","TOST","BILL","MELI","SE","VRT","CRDO","ALAB","TEM","RXRX","SDGR","VEEV","DOCS","HIMS",
]

# --- T1b: EDGAR FORM D (private raises via EDGAR full-text search by name) ---
# Notable US private AI/tech startups that file Reg D. Names matched by EDGAR FTS.
FORMD_NAMES = [
    "OpenAI","Anthropic","Databricks","Scale AI","Anduril Industries","xAI","Cohere","Perplexity AI",
    "Glean Technologies","Together Computer","Groq","SambaNova Systems","Runway AI","Adept AI","Inflection AI",
    "Harvey AI","Sierra","Anysphere","Figure AI","Physical Intelligence","Skild AI","Hippocratic AI","Abridge",
    "Cresta","Writer","Jasper AI","Notion Labs","Rippling","Ramp Business","Brex","Deel","Airtable",
    "Discord","Stripe","Plaid","Chime","Instacart","Canva","Grammarly","Vercel","Retool","Snyk","Wiz",
    # wave 2
    "Mistral AI","Reflection AI","Thinking Machines Lab","Safe Superintelligence","World Labs","Luma AI",
    "Suno","ElevenLabs","Cartesia","Fireworks AI","Baseten","Modal Labs","Replicate","LangChain","LlamaIndex",
    "Pinecone Systems","Chroma","Weaviate","Neon","Supabase","Clerk","Vanta","Mercury Technologies","Column",
    "Modern Treasury","Shield AI","Saronic Technologies","Applied Intuition","Hadrian Automation","Xaira Therapeutics",
    "EvolutionaryScale","Chai Discovery","Cursor","Decagon","Sierra AI","Mercor","Clay","Legora","Cognition AI",
]

# --- T2: OpenAlex topics (peer-reviewed, verified_structured; stamp sector=ai) ---
OPENALEX_QUERIES = [
    "large language model","retrieval augmented generation","transformer architecture",
    "reinforcement learning from human feedback","mixture of experts language model","diffusion model image generation",
    "neural network quantization","approximate nearest neighbor vector search","autonomous language model agents",
    "instruction tuning language model","long context transformer","speculative decoding inference",
    # wave 2
    "model distillation neural network","parameter efficient fine-tuning LoRA","chain of thought reasoning",
    "multimodal large language model","code generation large language model","graph neural network",
    "differential privacy machine learning","dense passage retrieval","knowledge distillation transformer",
    "state space model sequence",
]

# --- T3: GitHub org traction (technical_signal) ---
GITHUB_ORGS = [
    "openai","anthropics","google-deepmind","meta-llama","huggingface","nvidia","pytorch","tensorflow",
    "langchain-ai","run-llama","vllm-project","ggml-org","mistralai","databricks","triton-lang","microsoft",
    "google-research","facebookresearch","EleutherAI","allenai","stanfordnlp","deepset-ai","qdrant","weaviate",
    # wave 2
    "vercel","supabase","pinecone-io","chroma-core","modal-labs","BerriAI","stanford-crfm","unslothai",
    "ollama","comfyanonymous","Lightning-AI","ray-project",
]

def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(PROD + path, method="POST",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json",
                 "X-Admin-Token": os.environ.get("EIGEN_ADMIN_TOKEN", "")})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())

def build(tranche: str, limit: int | None) -> list[dict]:
    jobs: list[dict] = []
    if tranche in ("depth","all"):
        for t in DEPTH_TICKERS:
            jobs.append({"connector":"edgar","query":t,"limit":limit or 12})
    if tranche in ("formd","all"):
        for n in FORMD_NAMES:
            jobs.append({"connector":"edgar","query":n,"limit":limit or 6,"params":{"forms":["D"]}})
    if tranche in ("openalex","all"):
        for qy in OPENALEX_QUERIES:
            jobs.append({"connector":"openalex","query":qy,"limit":limit or 20,"facets":{"sector":"ai"}})
    if tranche in ("github","all"):
        for o in GITHUB_ORGS:
            jobs.append({"connector":"github","query":o,"limit":limit or 8})
    return jobs

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tranche", choices=["depth","formd","openalex","github","all"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    jobs = build(a.tranche, a.limit)
    print(f"tranche={a.tranche}  jobs={len(jobs)}  (limit/job default applied)")
    if a.dry:
        print(json.dumps(jobs[:5], indent=2)); print(f"... ({len(jobs)} total)"); return 0
    if not os.environ.get("EIGEN_ADMIN_TOKEN"):
        print("ERROR: set EIGEN_ADMIN_TOKEN", file=sys.stderr); return 2
    res = _post("/admin/corpus/ingest", {"jobs": jobs})
    print("enqueued:", res)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
