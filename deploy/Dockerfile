# Noesis API image — medical vertical, with the answer-video add-on (Node + ffmpeg).
FROM python:3.13-slim

WORKDIR /app

# System deps: ffmpeg (video assembly) + Node 20 (the answer-video generator runs via tsx).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg ffmpeg \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip

# Heavy, code-independent deps FIRST so their layers cache across code pushes:
# vision-upload media decoders (images / PDF pages / DICOM) + boto3 for durable video (R2),
# and docling (factra-style PDF → layout/table-aware markdown for guideline full-text ingestion;
# PyMuPDF stays the fallback engine — EIGEN_PDF_ENGINE=pymupdf forces it if docling misbehaves).
RUN pip install --no-cache-dir Pillow PyMuPDF pydicom numpy boto3
RUN pip install --no-cache-dir docling

# Install the kernel (serve + postgres extras) and the medical vertical.
COPY packages packages
COPY apps apps
COPY deploy deploy
RUN pip install --no-cache-dir "./packages/kernel[serve,postgres]" ./packages/vertical_medical

# Build the self-contained answer-video generator (Node). tsx is a runtime dep so the
# generator runs in-container; @napi-rs/canvas ships prebuilt linux-x64 binaries.
RUN cd apps/video && npm install --no-audit --no-fund

# apps/ is not a pip package; put it on the path. Single vertical per deployment.
ENV PYTHONPATH=/app/apps \
    EIGEN_ACTIVE_VERTICAL=medical \
    EIGEN_PROVIDER_MODE=live \
    EIGEN_STRUCTURED_ANSWERS=true \
    EIGEN_VIDEO_ENABLED=true \
    EIGEN_GAP_HEALING=true \
    EIGEN_CONVERSATION=true \
    EIGEN_STREAM=true \
    PORT=8000

EXPOSE 8000
CMD ["bash", "deploy/start.sh"]
