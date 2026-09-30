from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path
import sys
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from h3_adaptive_low_vram import H3AdaptiveChunkedMLPForward, H3AdaptiveChunkedProjectionForward


class FakeTensor:
    def __init__(self, tokens: int, element_bytes: int = 2):
        self.shape = (tokens, 5376)
        self.device = "cuda:0"
        self._element_bytes = element_bytes

    def element_size(self) -> int:
        return self._element_bytes


class AdaptiveBudgetTests(unittest.TestCase):
    def wrapper(self) -> H3AdaptiveChunkedMLPForward:
        return H3AdaptiveChunkedMLPForward(lambda value: value, 2048, 32768, 4.0, 0.5)

    @patch("torch.cuda.mem_get_info", return_value=(8 * 1024**3, 12 * 1024**3))
    def test_small_input_uses_native_direct_path(self, _mem_info):
        self.assertEqual(self.wrapper()._chunk_tokens(FakeTensor(4096)), 4096)

    @patch("torch.cuda.mem_get_info", return_value=(8 * 1024**3, 12 * 1024**3))
    def test_large_input_uses_calculated_chunk(self, _mem_info):
        selected = self.wrapper()._chunk_tokens(FakeTensor(40000))
        self.assertGreaterEqual(selected, 2048)
        self.assertLess(selected, 40000)
        self.assertEqual(selected % 256, 0)

    @patch("torch.cuda.mem_get_info", return_value=(8 * 1024**2, 12 * 1024**3))
    def test_low_live_free_memory_falls_back_to_minimum(self, _mem_info):
        self.assertEqual(self.wrapper()._chunk_tokens(FakeTensor(40000)), 2048)

    @patch("torch.cuda.mem_get_info", return_value=(8 * 1024**3, 12 * 1024**3))
    def test_projection_is_chunked_and_preserves_different_output_width(self, _mem_info):
        calls = []

        def project(value):
            calls.append(value.shape[0])
            return torch.zeros((value.shape[0], 12), dtype=value.dtype)

        wrapper = H3AdaptiveChunkedProjectionForward(
            project, 2, 4, 4.0, 0.5, expanded_width=12,
        )
        result = wrapper(torch.zeros((10, 4), dtype=torch.float16))
        self.assertEqual(result.shape, (10, 12))
        self.assertEqual(calls, [4, 4, 2])


if __name__ == "__main__":
    unittest.main()
