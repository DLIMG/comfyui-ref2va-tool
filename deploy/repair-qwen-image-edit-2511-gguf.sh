#!/usr/bin/env bash
# Resume and verify the Qwen Image Edit 2511 GGUF download.
set -euo pipefail

ROOT="/home/tkai/ComfyUI"
TARGET="$ROOT/models/unet/qwen-image-edit-2511-Q4_0.gguf"
URL="https://hf-mirror.com/unsloth/Qwen-Image-Edit-2511-GGUF/resolve/main/qwen-image-edit-2511-Q4_0.gguf"
EXPECTED_SIZE=11852773984
EXPECTED_SHA256="4b537c1e238f315fb4774e3ae677037b3d8bfde3e50a95d0b0a68dd9597b4f82"

rm -f /home/tkai/.qwen2511-download-complete

while true; do
  ACTUAL_SIZE=$(stat -c %s "$TARGET" 2>/dev/null || printf '0')
  if [ "$ACTUAL_SIZE" -eq "$EXPECTED_SIZE" ]; then
    break
  fi
  if [ "$ACTUAL_SIZE" -gt "$EXPECTED_SIZE" ]; then
    echo "Downloaded file exceeds expected size: $ACTUAL_SIZE" >&2
    exit 1
  fi
  echo "Resuming GGUF: $ACTUAL_SIZE / $EXPECTED_SIZE bytes"
  curl --fail --location --retry 5 --retry-all-errors --retry-delay 10 \
    --continue-at "$ACTUAL_SIZE" --output "$TARGET" "$URL" || true
  sleep 5
done

ACTUAL_SHA256=$(sha256sum "$TARGET" | awk '{print $1}')
if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
  echo "SHA-256 verification failed: $ACTUAL_SHA256" >&2
  exit 1
fi

touch /home/tkai/.qwen2511-download-complete
echo "Qwen Image Edit 2511 GGUF verified successfully."
