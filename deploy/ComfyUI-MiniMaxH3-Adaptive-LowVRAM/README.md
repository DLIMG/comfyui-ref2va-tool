# MiniMax H3 Adaptive Low VRAM

Local deployment package for the Ref2VA workstation. It patches only MiniMax H3
MLP, attention QKV, and attention output projection forwards. A full operation is used when its
real token count fits the calculated activation budget; otherwise the token
axis is divided into the largest safe chunks selected from total and currently
free CUDA memory. QKV chunks are capped at 8192 tokens. Attention output
projection chunks are capped at 4096 tokens to avoid unsupported Ampere
cuBLASLt INT8 matrix shapes.

Install this directory as:

```text
/home/tkai/ComfyUI/custom_nodes/ComfyUI-MiniMaxH3-Adaptive-LowVRAM
```

Restart ComfyUI and verify that `/object_info/MiniMaxH3AdaptiveLowVRAM` returns
the node schema. No Python dependencies are added.

The MLP object-patching structure is derived from
[`lericogit/ComfyUI-MiniMaxH3-LowVRAM`](https://github.com/lericogit/ComfyUI-MiniMaxH3-LowVRAM)
under the MIT License. This local variant adds runtime token/VRAM budgeting and
an automatic native direct path.
