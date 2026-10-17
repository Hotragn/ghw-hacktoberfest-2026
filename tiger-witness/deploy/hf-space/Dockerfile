# syntax=docker/dockerfile:1
# Witness on a Hugging Face Docker Space (CPU Basic: 2 vCPU / 16 GB RAM / 50 GB ephemeral disk).
# One container: FastAPI API (:7860, public) + worker + llama.cpp server (:8080, loopback only),
# managed by supervise.py. Build context = the Space repo assembled by make-space.sh.
#
# Base: the official llama.cpp server image (Ubuntu 24.04, ships /app/llama-server + its libs).
# Pinned by digest (multi-arch index of ghcr.io/ggml-org/llama.cpp:server, resolved 2026-10-17). Bump deliberately.
FROM ghcr.io/ggml-org/llama.cpp:server@sha256:e83cbdc66e692129e17aad70293366cb00e3acca94b9f197c91a8a56e92201c3
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Ubuntu 24.04 ships python3.12 (the app's target) and a default "ubuntu" user with uid 1000.
# HF runs the container as uid 1000, so replace it with our own "user" (uid 1000) per HF docs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && (userdel -r ubuntu 2>/dev/null || true) \
 && useradd -m -u 1000 user \
 && mkdir -p /models /opt/venv && chown user:user /models /opt/venv

USER 1000
ENV HOME=/home/user \
    PATH=/opt/venv/bin:/home/user/.local/bin:$PATH \
    PYTHON=/opt/venv/bin/python \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 LOG_FORMAT=json \
    PORT=7860 \
    WITNESS_MODEL_CACHE=/home/user/app/models \
    WITNESS_FILES_ROOT=/tmp/witness-files \
    WITNESS_LOCAL_LLM_URL=http://127.0.0.1:8080/v1 \
    WITNESS_LOCAL_LLM_MODEL=qwen3-1.7b \
    LLAMA_MODEL_PATH=/models/model.gguf \
    LLAMA_SERVER=/app/llama-server \
    LLAMA_THREADS=2
WORKDIR /home/user/app

# requirements.lock: every dependency pinned with sha256 hashes (uv pip compile --generate-hashes, linux x86_64,
# py3.12); pip refuses anything unpinned or tampered.
COPY --chown=user requirements.lock .

# Bake the embedding model and the GGUF into the image so a wake from sleep does not re-download.
# Default: Qwen3-1.7B Q4_K_M (~1.1 GB, Apache-2.0). 16 GB RAM also fits Qwen3-4B-Instruct-2507 Q4_0
# (~2.4 GB) but on 2 vCPU it is ~2.5x slower; override BOTH build args (Space variables) QWEN_GGUF_URL + QWEN_GGUF_SHA256.
# llama-server mmaps the GGUF and loads it at container start (not on first request); supervise.py waits for it.
RUN python3 -m venv /opt/venv && pip install --require-hashes --no-deps -r requirements.lock \
 && python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2', cache_dir='/home/user/app/models')"
# Pinned to a repo commit and verified by sha256 (the LFS oid HF publishes), so a swapped file fails the build.
ARG QWEN_GGUF_URL=https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/d7f544eead698dbd1f15126ef60b45a1e1933222/Qwen3-1.7B-Q4_K_M.gguf
ARG QWEN_GGUF_SHA256=b139949c5bd74937ad8ed8c8cf3d9ffb1e99c866c823204dc42c0d91fa181897
RUN curl -fL --proto '=https' --tlsv1.2 --retry 5 -o /models/model.gguf "$QWEN_GGUF_URL" \
 && echo "$QWEN_GGUF_SHA256  /models/model.gguf" | sha256sum -c - \
 && head -c 4 /models/model.gguf | grep -q GGUF

COPY --chown=user tigerkit.py tigerprod.py supervise.py ./
COPY --chown=user witness ./witness
COPY --chown=user sql ./sql
COPY --chown=user static ./static

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=3s CMD ["curl", "-fs", "http://127.0.0.1:7860/healthz"]
# The base image's ENTRYPOINT is llama-server; reset it.
ENTRYPOINT []
CMD ["python", "supervise.py"]
