#!/usr/bin/env bash
# Assemble a Hugging Face Space repo from this project.
#   deploy/hf-space/make-space.sh <path-to-cloned-space>     (e.g. ~/witness, cloned from hf.co/spaces/<you>/witness)
# Copies only what the image needs; never copies .env or secrets.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
dst=${1:?usage: make-space.sh <space-repo-dir>}
mkdir -p "$dst"
cp "$here/Dockerfile" "$here/README.md" "$here/supervise.py" "$here/requirements.lock" "$dst/"
cp "$root/requirements.txt" "$root/tigerkit.py" "$root/tigerprod.py" "$dst/"
for d in witness sql static; do
  rm -rf "${dst:?}/$d"
  cp -R "$root/$d" "$dst/$d"
done
find "$dst" -name __pycache__ -type d -prune -exec rm -rf {} +
printf '__pycache__/\n*.pyc\n.env\n' > "$dst/.dockerignore"
echo "assembled Space in $dst; now: cd $dst && git add -A && git commit -m 'deploy witness' && git push"
