import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import executor_registry
import scan_images


class RuntimeSourceFileModeTests(unittest.TestCase):
    def _fixture(self, root):
        path = Path(root) / "sample.png"
        path.write_bytes(b"synthetic-qr-standin")
        return {
            "image_id": "img", "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "group_id": "group", "side_id": "LEFT",
            "relative_path": "sample.png", "pair_id": "pair",
        }

    def test_source_file_mode_never_calls_pixel_loader(self):
        with tempfile.TemporaryDirectory() as temp:
            image = self._fixture(temp)
            strategies = executor_registry.StrategyExecutorRegistry()
            decoders = executor_registry.DecoderExecutorRegistry()
            strategies.register(
                "V01", lambda path, context, params: path, input_mode="source_file",
            )
            decoders.register(
                "native", lambda image, context, options: {
                    "status": "DECODED", "payloads": ["native-ok"], "candidate_count": 1,
                    "native_strategy_id": context["strategy_id"], "native_decoder_id": "ZXing-C++",
                },
            )
            records, success = scan_images.execute_image_matrix(
                "run1", image, ["V01"], strategies, decoders, ["native"],
                "contribution", lambda _: (_ for _ in ()).throw(
                    AssertionError("pixel loader was incorrectly called")
                ), {"cv2": None, "numpy": None, "require_image_dependencies": True},
            )
            self.assertTrue(success)
            self.assertEqual(records[0]["status"], "DECODED")
            self.assertEqual(records[0]["input_mode"], "source_file")
            self.assertEqual(records[0]["native_strategy_id"], "V01")
            self.assertEqual(records[0]["variant_sha256"], image["sha256"])
            self.assertIsNone(records[0]["variant_width"])

    def test_native_skip_and_not_run_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            image = self._fixture(temp)
            strategies = executor_registry.StrategyExecutorRegistry()
            decoders = executor_registry.DecoderExecutorRegistry()
            strategies.register("V04", lambda path, ctx, params: path, input_mode="source_file")
            for status, reason in (
                ("SKIPPED_INELIGIBLE", "WRONG_IMAGE_CLASS"),
                ("NOT_RUN", "NATIVE_DEPENDENCY_MISSING"),
            ):
                decoders.register(
                    status, lambda img, ctx, options, st=status, why=reason: {
                        "status": st, "payloads": [], "candidate_count": 0,
                        "skip_reason": why,
                    },
                )
            records, success = scan_images.execute_image_matrix(
                "run1", image, ["V04"], strategies, decoders,
                ["SKIPPED_INELIGIBLE", "NOT_RUN"], "contribution",
                lambda _: None, {"require_image_dependencies": True},
            )
            self.assertFalse(success)
            self.assertEqual(records[0]["status"], "SKIPPED_INELIGIBLE")
            self.assertEqual(records[1]["status"], "NOT_RUN")

    def test_unavailable_cv2_is_not_a_false_image_ineligible(self):
        with tempfile.TemporaryDirectory() as temp:
            image = self._fixture(temp)
            strategies = executor_registry.StrategyExecutorRegistry()
            decoders = executor_registry.DecoderExecutorRegistry()
            strategies.register("V02", lambda pixels, ctx, params: pixels)
            decoders.register("native", lambda *args: {})
            records, _ = scan_images.execute_image_matrix(
                "run1", image, ["V02"], strategies, decoders, ["native"],
                "contribution", lambda _: None, {"cv2": None, "numpy": None,
                                                 "require_image_dependencies": True},
            )
            self.assertEqual(records[0]["status"], "NOT_RUN")
            self.assertIn("DEPENDENCY_MISSING", records[0]["skip_reason"])

    def test_native_status_payload_contradiction_is_an_error(self):
        with tempfile.TemporaryDirectory() as temp:
            image = self._fixture(temp)
            strategies = executor_registry.StrategyExecutorRegistry()
            decoders = executor_registry.DecoderExecutorRegistry()
            strategies.register("V01", lambda p, ctx, params: p, input_mode="source_file")
            decoders.register("native", lambda *args: {
                "status": "NO_DECODE", "payloads": ["fabricated"], "candidate_count": 0
            })
            records, _ = scan_images.execute_image_matrix(
                "run1", image, ["V01"], strategies, decoders, ["native"],
                "contribution", lambda _: None, {},
            )
            self.assertEqual(records[0]["status"], "ERROR")
            self.assertIn("contradicts", records[0]["error"])


if __name__ == "__main__":
    unittest.main()
