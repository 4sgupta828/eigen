#!/usr/bin/env bash
# Eigen API entrypoint. Single vertical per deployment (EIGEN_ACTIVE_VERTICAL).
# Provider mode (EIGEN_PROVIDER_MODE): replay = offline/free; live = real
# Anthropic/OpenAI/Tavily (needs the API keys). The pgvector schema is created on
# demand by the corpus source, so there is no separate migrate step yet.
set -euo pipefail
PORT="${PORT:-8000}"
echo "[start] eigen api — vertical=${EIGEN_ACTIVE_VERTICAL:-?} mode=${EIGEN_PROVIDER_MODE:-replay} port=$PORT"
exec uvicorn api.app:create_app --factory --host 0.0.0.0 --port "$PORT"
