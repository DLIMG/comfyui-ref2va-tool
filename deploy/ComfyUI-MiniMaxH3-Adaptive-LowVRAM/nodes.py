from __future__ import annotations

import logging

import comfy.patcher_extension
from comfy.ldm.minimax.model import MiniMaxH3Model
from comfy_api.latest import ComfyExtension, io

from .h3_adaptive_low_vram import (
    H3AdaptiveChunkedMLPForward,
    H3AdaptiveChunkedProjectionForward,
    H3_QKV_WIDTH,
)


PREFETCH_WRAPPER_KEY = "minimax_h3_adaptive_low_vram_prefetch"


def h3_disable_prefetch_wrapper(
    executor, x, timestep, context, transformer_options=None, minimax_payload=None, **kwargs,
):
    options = dict(transformer_options or {})
    options["prefetch_dynamic_vbars"] = False
    return executor(x, timestep, context, options, minimax_payload=minimax_payload, **kwargs)


class MiniMaxH3AdaptiveLowVRAMNode(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="MiniMaxH3AdaptiveLowVRAM",
            display_name="MiniMax H3 Adaptive Low VRAM",
            description="Dynamically chunks H3 MLP tokens only when the full activation exceeds the live GPU budget.",
            category="advanced/model_patches",
            is_experimental=True,
            inputs=[
                io.Model.Input("model"),
                io.Boolean.Input("enabled", default=True),
                io.Int.Input("minimum_chunk_tokens", default=2048, min=256, max=32768, step=256),
                io.Int.Input("maximum_chunk_tokens", default=32768, min=2048, max=262144, step=256),
                io.Float.Input("activation_budget_percent", default=4.0, min=1.0, max=25.0, step=0.25),
                io.Float.Input("free_memory_fraction", default=0.5, min=0.1, max=0.9, step=0.05),
                io.Combo.Input("block_prefetch", options=["keep", "disable"], default="keep"),
                io.Boolean.Input("verbose", default=True),
            ],
            outputs=[io.Model.Output()],
        )

    @classmethod
    def execute(
        cls, model: io.Model.Type, enabled: bool, minimum_chunk_tokens: int,
        maximum_chunk_tokens: int, activation_budget_percent: float,
        free_memory_fraction: float, block_prefetch: str, verbose: bool,
    ) -> io.NodeOutput:
        if not enabled:
            return io.NodeOutput(model)
        if minimum_chunk_tokens > maximum_chunk_tokens:
            raise ValueError("minimum_chunk_tokens cannot exceed maximum_chunk_tokens")

        diffusion_model = model.get_model_object("diffusion_model")
        if not isinstance(diffusion_model, MiniMaxH3Model):
            raise ValueError("MiniMax H3 Adaptive Low VRAM requires a native MiniMax H3 model")

        patched = model.clone()
        shared_decisions: set[tuple[str, int, int]] = set()
        for index in range(len(diffusion_model.blocks)):
            mlp_path = f"diffusion_model.blocks.{index}.mlp.forward"
            qkv_path = f"diffusion_model.blocks.{index}.attn.qkv_proj.forward"
            out_proj_path = f"diffusion_model.blocks.{index}.attn.out_proj.forward"
            for path in (mlp_path, qkv_path, out_proj_path):
                if path in model.object_patches:
                    raise ValueError(f"H3 token-local layer is already patched: {path}")
            original_forward = patched.get_model_object(mlp_path)
            patched.add_object_patch(
                mlp_path,
                H3AdaptiveChunkedMLPForward(
                    original_forward,
                    minimum_chunk_tokens,
                    maximum_chunk_tokens,
                    activation_budget_percent,
                    free_memory_fraction,
                    verbose,
                    decision_label="MLP",
                    shared_decisions=shared_decisions,
                ),
            )
            qkv_forward = patched.get_model_object(qkv_path)
            patched.add_object_patch(
                qkv_path,
                H3AdaptiveChunkedProjectionForward(
                    qkv_forward,
                    minimum_chunk_tokens,
                    min(maximum_chunk_tokens, 8192),
                    activation_budget_percent,
                    free_memory_fraction,
                    verbose,
                    expanded_width=H3_QKV_WIDTH,
                    decision_label="QKV",
                    shared_decisions=shared_decisions,
                ),
            )
            out_proj_forward = patched.get_model_object(out_proj_path)
            patched.add_object_patch(
                out_proj_path,
                H3AdaptiveChunkedProjectionForward(
                    out_proj_forward,
                    minimum_chunk_tokens,
                    min(maximum_chunk_tokens, 4096),
                    activation_budget_percent,
                    free_memory_fraction,
                    verbose,
                    expanded_width=5376,
                    decision_label="Attention output projection",
                    shared_decisions=shared_decisions,
                ),
            )

        if block_prefetch == "disable":
            patched.add_wrapper_with_key(
                comfy.patcher_extension.WrappersMP.DIFFUSION_MODEL,
                PREFETCH_WRAPPER_KEY,
                h3_disable_prefetch_wrapper,
            )
        if verbose:
            logging.info(
                "MiniMax H3 Adaptive Low VRAM - patched MLP, QKV, and attention output projection in %d blocks, budget %.2f%%, free fraction %.2f",
                len(diffusion_model.blocks), activation_budget_percent, free_memory_fraction,
            )
        return io.NodeOutput(patched)


class MiniMaxH3AdaptiveLowVRAMExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [MiniMaxH3AdaptiveLowVRAMNode]


def comfy_entrypoint():
    return MiniMaxH3AdaptiveLowVRAMExtension()
