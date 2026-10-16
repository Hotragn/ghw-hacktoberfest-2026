#!/usr/bin/env bash
# Downloads Qwen3-1.7B Q4_K_M (Apache-2.0) for the llama.cpp service and verifies it is a GGUF file.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p models
f=models/Qwen3-1.7B-Q4_K_M.gguf
url=${QWEN_GGUF_URL:-https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf}
if [ ! -s "$f" ]; then
  curl -fL --retry 5 -o "$f.part" "$url"
  mv "$f.part" "$f"
fi
head -c 4 "$f" | grep -q GGUF || { echo "not a GGUF file: $f" >&2; exit 1; }
ls -lh "$f"
