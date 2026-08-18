# Eigen API image — the TECH vertical (deep-tech research Q&A). LEAN: serves the API only.
# Structured-API ingest synthesizes markdown; full-text paper ingest (HTML + DOCLING/torch PDF
# parsing) runs on the SEPARATE ingest worker (deploy/Dockerfile.worker), so this image stays small
# and deploys fast. Set EIGEN_INGEST_IN_API=false here so ingestion runs only on the worker.
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# Light, code-independent deps FIRST so their layer caches across code pushes:
# image decode (vision uploads), a light PDF reader for attachments, numpy, and boto3 for R2.
RUN pip install --no-cache-dir Pillow PyMuPDF numpy boto3

# (docling/torch live on the ingest worker image, not here — keeps the API lean.)

# Install the kernel (serve + postgres extras) and the TECH vertical.
COPY packages packages
COPY apps apps
COPY deploy deploy
RUN pip install --no-cache-dir "./packages/kernel[serve,postgres]" ./packages/vertical_tech

# apps/ is not a pip package; put it on the path. Single vertical per deployment.
ENV PYTHONPATH=/app/apps \
    EIGEN_ACTIVE_VERTICAL=tech \
    EIGEN_PROVIDER_MODE=live \
    EIGEN_STRUCTURED_ANSWERS=true \
    EIGEN_VIDEO_ENABLED=false \
    EIGEN_GAP_HEALING=true \
    EIGEN_CONVERSATION=true \
    EIGEN_STREAM=true \
    PORT=8000

EXPOSE 8000
CMD ["bash", "deploy/start.sh"]
