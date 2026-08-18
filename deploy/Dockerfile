# Eigen API image — the TECH vertical (deep-tech research Q&A).
# Mostly lean: arXiv/EDGAR ingest synthesizes markdown from structured APIs. FULL-TEXT paper ingest is
# HTML-first (no heavy deps); DOCLING is the PDF-FALLBACK parser (its one heavy dep is torch), imported
# lazily so the serving path never loads it. No Node/ffmpeg video add-on.
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# Light, code-independent deps FIRST so their layer caches across code pushes:
# image decode (vision uploads), a light PDF reader for attachments, numpy, and boto3 for R2.
RUN pip install --no-cache-dir Pillow PyMuPDF numpy boto3

# DOCLING — the full-text PDF-fallback parser (arXiv HTML covers most papers with no heavy dep; docling
# handles PDF-only/older papers). CPU-only torch to keep the image as small as this dep allows. Its own
# cached layer so code pushes don't rebuild it. Imported lazily in the arxiv connector.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu docling

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
