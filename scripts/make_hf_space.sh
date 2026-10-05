#!/usr/bin/env bash
# Assemble a Hugging Face Docker Space folder from the current commit (tracked files only, so
# .env and other ignored files can never be included). Nothing is published.
set -euo pipefail
out="${1:?usage: make_hf_space.sh <output-dir>}"
root="$(git rev-parse --show-toplevel)"
rm -rf "$out" && mkdir -p "$out"
git -C "$root" archive HEAD | tar -x -C "$out"
cp "$root/deploy/huggingface/README.md" "$out/README.md"
rm -rf "$out/deploy" "$out/tasks"
echo "Space folder ready: $out"
