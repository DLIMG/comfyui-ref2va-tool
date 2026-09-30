from __future__ import annotations

from collections.abc import Callable
import logging

import torch


H3_EXPANDED_MLP_WIDTH = 28672
H3_QKV_WIDTH = 5376 * 3
MIB = 1024 * 1024


def _round_down(value: int, step: int) -> int:
    return max(step, value // step * step)


class H3AdaptiveChunkedMLPForward:
    """Run the native H3 MLP directly when it fits, otherwise token-chunk it."""

    def __init__(
        self,
        original_forward: Callable[[torch.Tensor], torch.Tensor],
        minimum_chunk_tokens: int,
        maximum_chunk_tokens: int,
        activation_budget_percent: float,
        free_memory_fraction: float,
        verbose: bool = False,
        expanded_width: int = H3_EXPANDED_MLP_WIDTH,
        decision_label: str = "MLP",
        shared_decisions: set[tuple[str, int, int]] | None = None,
    ):
        self.original_forward = original_forward
        self.minimum_chunk_tokens = minimum_chunk_tokens
        self.maximum_chunk_tokens = maximum_chunk_tokens
        self.activation_budget_percent = activation_budget_percent
        self.free_memory_fraction = free_memory_fraction
        self.verbose = verbose
        self.expanded_width = expanded_width
        self.decision_label = decision_label
        self.shared_decisions = shared_decisions if shared_decisions is not None else set()

    def _chunk_tokens(self, x: torch.Tensor) -> int:
        token_count = int(x.shape[0])
        bytes_per_token = self.expanded_width * x.element_size()
        free_bytes, total_bytes = torch.cuda.mem_get_info(x.device)

        # The total-VRAM share makes the decision stable across DynamicVRAM
        # weight paging. Runtime free memory may only lower the selected size.
        total_budget = int(total_bytes * self.activation_budget_percent / 100.0)
        free_budget = int(free_bytes * self.free_memory_fraction)
        minimum_budget = self.minimum_chunk_tokens * bytes_per_token
        budget = max(minimum_budget, min(total_budget, max(free_budget, minimum_budget)))

        full_expanded_bytes = token_count * bytes_per_token
        if full_expanded_bytes <= budget and token_count <= self.maximum_chunk_tokens:
            return token_count

        candidate = _round_down(budget // bytes_per_token, 256)
        return max(
            self.minimum_chunk_tokens,
            min(candidate, self.maximum_chunk_tokens, token_count),
        )

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        token_count = int(x.shape[0])
        chunk_tokens = self._chunk_tokens(x)
        decision = (self.decision_label, token_count, chunk_tokens)
        if self.verbose and decision not in self.shared_decisions:
            logging.info(
                "MiniMax H3 Adaptive Low VRAM %s - %d tokens, selected chunk %d%s",
                self.decision_label,
                token_count,
                chunk_tokens,
                " (native direct path)" if chunk_tokens >= token_count else "",
            )
            self.shared_decisions.add(decision)

        if token_count <= chunk_tokens:
            return self.original_forward(x)

        output = torch.empty_like(x)
        for start in range(0, token_count, chunk_tokens):
            end = min(start + chunk_tokens, token_count)
            chunk_output = self.original_forward(x[start:end])
            output[start:end].copy_(chunk_output)
            del chunk_output
        return output


class H3AdaptiveChunkedProjectionForward(H3AdaptiveChunkedMLPForward):
    """Chunk a token-local projection whose output width differs from its input."""

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        token_count = int(x.shape[0])
        chunk_tokens = self._chunk_tokens(x)
        decision = (self.decision_label, token_count, chunk_tokens)
        if self.verbose and decision not in self.shared_decisions:
            logging.info(
                "MiniMax H3 Adaptive Low VRAM %s - %d tokens, selected chunk %d%s",
                self.decision_label,
                token_count,
                chunk_tokens,
                " (native direct path)" if chunk_tokens >= token_count else "",
            )
            self.shared_decisions.add(decision)

        if token_count <= chunk_tokens:
            return self.original_forward(x)

        output = None
        for start in range(0, token_count, chunk_tokens):
            end = min(start + chunk_tokens, token_count)
            chunk_output = self.original_forward(x[start:end])
            if output is None:
                output = torch.empty(
                    (token_count, *chunk_output.shape[1:]),
                    dtype=chunk_output.dtype,
                    device=chunk_output.device,
                )
            output[start:end].copy_(chunk_output)
            del chunk_output
        return output
