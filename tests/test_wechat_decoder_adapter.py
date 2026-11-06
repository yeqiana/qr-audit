"""Offline WeChatQRCode adapter protocol tests without proprietary model files."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import executor_registry
import wechat_decoder_adapter


class WeChatDecoderTests(unittest.TestCase):
    def build(self, temp, version, paths):
        root = Path(temp)
        files = []
        for i in range(paths):
            file = root / f"model-{i}.onnx"
            file.write_bytes(b"test-model-marker")
            files.append(file.name)
        config = root / "models.json"
        config.write_text(json.dumps({"models": files}), encoding="utf-8")
        calls = []
        class Detector:
            def detectAndDecode(self, image):
                return ["test-payload"], [[0, 0, 1, 1]]
        def factory(*args):
            calls.append(args)
            return Detector()
        cv2 = SimpleNamespace(__version__=version, wechat_qrcode_WeChatQRCode=factory)
        return cv2, config, calls

    def test_4x_and_5x_validate_model_count(self):
        with tempfile.TemporaryDirectory() as folder:
            cv2, path, calls = self.build(folder, "5.0.0", 2)
            ds = executor_registry.DecoderExecutorRegistry()
            ctx = {"cv2": cv2, "source_files": [], "dependencies": []}
            with patch.dict(os.environ, {"QR_AUDIT_WECHAT_MODEL_CONFIG": str(path)}):
                wechat_decoder_adapter.register_qr_audit(None, ds, ctx)
            self.assertTrue(ds.get("wechat").available)
            result = ds.get("wechat").decode(None, {}, {})
            self.assertEqual(result["payloads"], ["test-payload"])
            self.assertEqual(len(calls[0]), 2)
            self.assertIn(os.path.normcase(str(path)),
                          [os.path.normcase(p) for p in ctx["source_files"]])
            self.assertEqual(len(ctx["source_files"]), 3)

        with tempfile.TemporaryDirectory() as folder:
            cv2, path, calls = self.build(folder, "4.13.0", 4)
            ds = executor_registry.DecoderExecutorRegistry()
            with patch.dict(os.environ, {"QR_AUDIT_WECHAT_MODEL_CONFIG": str(path)}):
                wechat_decoder_adapter.register_qr_audit(None, ds, {"cv2": cv2})
            ds.get("wechat").decode(None, {}, {})
            self.assertEqual(len(calls[0]), 4)

    def test_incompatible_model_count_fails_before_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            cv2, path, _ = self.build(folder, "5.0", 4)
            ds = executor_registry.DecoderExecutorRegistry()
            with patch.dict(os.environ, {"QR_AUDIT_WECHAT_MODEL_CONFIG": str(path)}):
                with self.assertRaisesRegex(ValueError, "requires exactly 2"):
                    wechat_decoder_adapter.register_qr_audit(None, ds, {"cv2": cv2})

    def test_missing_model_or_module_is_explicit_not_run(self):
        ds = executor_registry.DecoderExecutorRegistry()
        with patch.dict(os.environ, {}, clear=True):
            wechat_decoder_adapter.register_qr_audit(None, ds, {"cv2": None})
        self.assertFalse(ds.get("wechat").available)
        self.assertIn("UNAVAILABLE", ds.get("wechat").unavailable_reason)

    def test_engine_is_reused_only_in_the_same_thread(self):
        with tempfile.TemporaryDirectory() as folder:
            cv2, path, calls = self.build(folder, "5.0", 2)
            ds = executor_registry.DecoderExecutorRegistry()
            with patch.dict(os.environ, {"QR_AUDIT_WECHAT_MODEL_CONFIG": str(path)}):
                wechat_decoder_adapter.register_qr_audit(None, ds, {"cv2": cv2})
            decoder = ds.get("wechat")
            decoder.decode(None, {}, {})
            decoder.decode(None, {}, {})
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

