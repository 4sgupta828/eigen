#!/usr/bin/env bash
# Eigen INGEST WORKER entrypoint — runs the corpus-ingest drain loop (docling-enabled) + a tiny
# health server on $PORT. Set EIGEN_INGEST_IN_API=false on the API service so ingestion runs ONLY here.
set -euo pipefail
echo "[start] eigen INGEST WORKER — vertical=${EIGEN_ACTIVE_VERTICAL:-?} mode=${EIGEN_PROVIDER_MODE:-replay}"
exec python -m worker.main
