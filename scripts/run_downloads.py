#!/usr/bin/env python3
"""Eigen download campaign — prod-direct ingest in PRIORITY ORDER (easy sources first).

Enqueues connector jobs against prod `/admin/corpus/ingest`. Ingest cost is embeddings-only
(~$0.02/1M tokens — pennies); the real limits are source rate-limits + time, so the prod worker
paces the queue serially. We do NOT block on unavailable sources (see docs/downloads-blocked.md).

Usage:
  EIGEN_ADMIN_TOKEN=... python scripts/run_downloads.py <tranche> [--limit N] [--dry]
  tranches: depth | formd | openalex | arxiv | s2 | crossref | wikidata | hn | github | recent | all
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

# --- T2: Semantic Scholar (citation graph, verified_structured/technical_signal; keyless+backoff) ---
S2_QUERIES = [
    "large language model","retrieval augmented generation","mixture of experts",
    "reinforcement learning from human feedback","parameter efficient fine tuning","chain of thought reasoning",
    "multimodal large language model","transformer efficient attention","llm agents tool use",
    "neural network quantization","dense retrieval","diffusion models generative",
]

# --- T2: Crossref (DOI/venue authority + citations, verified_structured/technical_signal; keyless) ---
CROSSREF_QUERIES = [
    "large language model","retrieval augmented generation","mixture of experts transformer",
    "reinforcement learning from human feedback","parameter efficient fine tuning","vector database search",
    "neural machine translation attention","diffusion model image synthesis","graph neural network",
    "self supervised representation learning","knowledge graph embedding","federated learning privacy",
]

# --- T2: arXiv preprints (technical_signal, unreviewed; keyless; stamp sector=ai) ---
ARXIV_QUERIES = [
    "large language model inference","retrieval augmented generation","llm agents tool use",
    "mixture of experts","parameter efficient fine tuning","llm reasoning chain of thought",
    "long context transformer","speculative decoding","model quantization llm","vector database ann search",
    "multimodal foundation model","diffusion model","reinforcement learning human feedback",
    "code generation llm","llm evaluation benchmark",
]

# --- T2: Wikidata company profiles (KEYLESS Crunchbase fallback: founders/ownership/M&A; reference tier) ---
WIKIDATA_NAMES = [
    "OpenAI","Anthropic","Databricks","Scale AI","Anduril Industries","xAI","Cohere","Perplexity AI",
    "Mistral AI","Hugging Face","Groq","SambaNova Systems","Cerebras Systems","Together AI","Runway",
    "Stripe","Databricks","Canva","Figma","Notion","Rippling","Ramp","Brex","Plaid","Chime","Discord",
    "NVIDIA","Advanced Micro Devices","Palantir Technologies","CrowdStrike","Snowflake Inc","Datadog",
    "Palo Alto Networks","ServiceNow","Cloudflare","MongoDB","Atlassian","Shopify","Coinbase","Block Inc",
]

# --- T3: Hacker News via Algolia (KEYLESS sentiment fallback; sentiment_signal tier, labeled) ---
HN_QUERIES = [
    "OpenAI","Anthropic","NVIDIA","CrowdStrike","Databricks","Palantir","Snowflake","Datadog",
    "large language model","AI agents","vector database","retrieval augmented generation",
    "Mistral","Perplexity","Cursor","llama","GPU shortage","AI regulation",
]

# --- Reddit: broader-community SENTIMENT signal (needs EIGEN_REDDIT_CLIENT_ID/SECRET in prod).
# (subreddit, query) pairs — scoped search of the high-signal AI/tech/startup communities.
REDDIT_QUERIES = [
    ("MachineLearning", "large language model"), ("MachineLearning", "benchmark"),
    ("LocalLLaMA", "open weights model"), ("LocalLLaMA", "quantization"),
    ("artificial", "AGI"), ("singularity", "frontier model"),
    ("OpenAI", "GPT"), ("StableDiffusion", "image model"),
    ("startups", "AI startup funding"), ("venturecapital", "AI investment"),
    ("hardware", "GPU"), ("datascience", "RAG"),
]

# --- Hugging Face Hub: model-adoption signal (technical_signal); keyless, EIGEN_HF_TOKEN optional ---
HF_QUERIES = [
    "large language model","text generation","embedding","reranker","vision language model",
    "code generation","speech recognition","diffusion","mixture of experts","function calling",
    "llama","mistral","qwen","gemma","phi","deepseek",
]
# --- Stack Overflow: developer-adoption signal (sentiment_signal); keyless ---
SO_QUERIES = [
    "langchain","llama.cpp","vllm","transformers huggingface","openai api","pgvector",
    "retrieval augmented generation","fine-tuning LLM","ollama","llama-index","cuda out of memory",
    "vector database",
]
# --- OpenReview: peer-reviewed research (verified_structured when accepted); keyless ---
OPENREVIEW_QUERIES = [
    "large language models","retrieval augmented generation","mixture of experts","in-context learning",
    "reinforcement learning from human feedback","diffusion models","state space models",
    "long context transformers","efficient inference","agentic reasoning",
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
    if tranche in ("arxiv","all"):
        for qy in ARXIV_QUERIES:
            jobs.append({"connector":"arxiv","query":qy,"limit":limit or 20,"facets":{"sector":"ai"}})
    if tranche in ("s2","all"):
        for qy in S2_QUERIES:
            jobs.append({"connector":"semantic_scholar","query":qy,"limit":limit or 20,"facets":{"sector":"ai"}})
    if tranche in ("crossref","all"):
        for qy in CROSSREF_QUERIES:
            jobs.append({"connector":"crossref","query":qy,"limit":limit or 20,"facets":{"sector":"ai"}})
    if tranche in ("wikidata","all"):
        for nm in WIKIDATA_NAMES:
            jobs.append({"connector":"wikidata","query":nm,"limit":limit or 1})
    if tranche in ("hn","all"):
        for qy in HN_QUERIES:
            jobs.append({"connector":"hackernews","query":qy,"limit":limit or 25})
    if tranche in ("github","all"):
        for o in GITHUB_ORGS:
            jobs.append({"connector":"github","query":o,"limit":limit or 8})
    if tranche in ("reddit","all"):
        for sub, qy in REDDIT_QUERIES:
            jobs.append({"connector":"reddit","query":qy,"limit":limit or 25,
                         "params":{"subreddit":sub}})
    if tranche in ("hf","all"):
        for qy in HF_QUERIES:
            jobs.append({"connector":"huggingface","query":qy,"limit":limit or 30,"facets":{"sector":"ai"}})
    if tranche in ("stackoverflow","all"):
        for qy in SO_QUERIES:
            jobs.append({"connector":"stackoverflow","query":qy,"limit":limit or 25})
    if tranche in ("openreview","all"):
        for qy in OPENREVIEW_QUERIES:
            jobs.append({"connector":"openreview","query":qy,"limit":limit or 30,"facets":{"sector":"ai"}})
    # RECENT lane: re-pull the paper sources newest-first / floored at >=2010 so the corpus isn't
    # relevance-skewed to old highly-cited work. Not part of "all" (it re-queries the same topics with
    # a freshness filter) — run explicitly: `run_downloads.py recent`.
    if tranche == "recent":
        # arXiv dates are reliable → newest-first is clean. OpenAlex/Crossref have bogus "forthcoming"
        # future dates, so we FLOOR at >=2010 WITHOUT a date sort (relevance within the recent window)
        # to avoid surfacing 2050/2114 junk. S2 floors by year.
        _floor = {"from_year": "2010"}
        for qy in ARXIV_QUERIES:
            jobs.append({"connector":"arxiv","query":qy,"limit":limit or 30,"facets":{"sector":"ai"},"params":{"sort":"recent"}})
        for qy in OPENALEX_QUERIES:
            jobs.append({"connector":"openalex","query":qy,"limit":limit or 30,"facets":{"sector":"ai"},"params":_floor})
        for qy in S2_QUERIES:
            jobs.append({"connector":"semantic_scholar","query":qy,"limit":limit or 30,"facets":{"sector":"ai"},"params":_floor})
        for qy in CROSSREF_QUERIES:
            jobs.append({"connector":"crossref","query":qy,"limit":limit or 30,"facets":{"sector":"ai"},"params":_floor})
    return jobs

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tranche", choices=["depth","formd","openalex","arxiv","s2","crossref","wikidata","hn","reddit","hf","stackoverflow","openreview","github","recent","all"])
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
