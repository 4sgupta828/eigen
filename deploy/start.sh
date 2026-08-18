#!/usr/bin/env bash
# Eigen entrypoint — ONE image, TWO roles (shared railway.toml startCommand runs this for both
# services). EIGEN_ROLE=worker → the corpus-ingest drain loop (docling-enabled) + a health server.
# else (default) → the API (uvicorn). Provider mode via EIGEN_PROVIDER_MODE (replay=offline/free,
# live=real Anthropic/OpenAI/Tavily). pgvector schema is created on demand by the corpus source.
set -euo pipefail
PORT="${PORT:-8000}"
if [ "${EIGEN_ROLE:-api}" = "worker" ]; then
  echo "[start] eigen INGEST WORKER — vertical=${EIGEN_ACTIVE_VERTICAL:-?} mode=${EIGEN_PROVIDER_MODE:-replay} (docling PDF parsing)"
  exec python -m worker.main
fi
echo "[start] eigen api — vertical=${EIGEN_ACTIVE_VERTICAL:-?} mode=${EIGEN_PROVIDER_MODE:-replay} port=$PORT"
exec uvicorn api.app:create_app --factory --host 0.0.0.0 --port "$PORT"
