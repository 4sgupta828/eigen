# Eigen image — the TECH vertical (deep-tech research Q&A). ONE image, TWO roles (deploy/start.sh
# dispatches on EIGEN_ROLE): the API service serves; the separate ingest-WORKER service runs the corpus
# drain (full-text HTML + DOCLING/torch PDF parsing). docling is a cached layer, so API code pushes
# don't rebuild it, and it's imported lazily so serving never loads torch. No Node/ffmpeg video add-on.
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# Light, code-independent deps FIRST so their layer caches across code pushes:
# image decode (vision uploads), a light PDF reader for attachments, numpy, and boto3 for R2.
RUN pip install --no-cache-dir Pillow PyMuPDF numpy boto3

# DOCLING — full-text PDF-fallback parser for the WORKER role (arXiv HTML covers most papers with no
# heavy dep). CPU-only torch; own cached layer so code pushes don't rebuild it; imported lazily so the
# API role never loads it.
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
