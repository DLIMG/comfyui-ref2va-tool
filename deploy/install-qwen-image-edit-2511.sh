#!/usr/bin/env bash
# Installs the low-VRAM Qwen-Image-Edit-2511 model files into an existing ComfyUI tree.
# Intended for the 12 GB cloud worker; all downloads resume safely after an interruption.
set -euo pipefail

ROOT="/home/tkai/ComfyUI"
MIRROR="https://hf-mirror.com"

mkdir -p "$ROOT/models/unet" "$ROOT/models/text_encoders" "$ROOT/models/vae"

download() {
  local url="$1"
  local target="$2"
  curl --fail --location --retry 5 --retry-delay 5 --continue-at - --output "$target" "$url"
}

download \
  "$MIRROR/unsloth/Qwen-Image-Edit-2511-GGUF/resolve/main/qwen-image-edit-2511-Q4_0.gguf" \
  "$ROOT/models/unet/qwen-image-edit-2511-Q4_0.gguf"
download \
  "$MIRROR/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors" \
  "$ROOT/models/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"
download \
  "$MIRROR/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors" \
  "$ROOT/models/vae/qwen_image_vae.safetensors"

touch /home/tkai/.qwen2511-download-complete
printf 'Qwen Image Edit 2511 model files downloaded successfully.\n'
