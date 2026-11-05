"""Synthetic QR geometry and real fallback routing (model weights mocked).

No claim is made about actual WeChat model recognition quality.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import recognition_boost_adapter as boost
from fallback_pipeline import decoder_filters


class GeometryRecoveryTests(unittest.TestCase):
    def setUp(self):
        try:
            import cv2
            import numpy as np
            import qrcode
        except ImportError as exc:
            self.skipTest(f"optional CV test dependencies not installed: {exc}")
        self.cv2, self.np, self.qrcode = cv2, np, qrcode

    def image(self, border=4, box_size=8):
        q = self.qrcode.QRCode(version=2, box_size=box_size, border=border,
                              error_correction=self.qrcode.constants.ERROR_CORRECT_M)
        q.add_data("geometry-proof-17")
        q.make(fit=False)
        return self.np.asarray(q.make_image(fill_color="black", back_color="white").convert("L"))

    def test_adaptive_scale_no_longer_fails_at_700_square(self):
        blank = self.np.full((700, 700), 165, dtype=self.np.uint8)
        for sid in ("quiet_zone", "gamma", "sauvola", "flatfield"):
            with self.subTest(variant=sid):
                output = boost._enhance(blank, {"cv2": self.cv2, "numpy": self.np}, sid)
                self.assertLessEqual(output.size, boost.MAX_OUTPUT_PIXELS)
                self.assertEqual(output.ndim, 2)
                self.assertEqual(output.dtype, self.np.uint8)
                self.assertGreater(output.shape[0], 700)

    def test_frames_over_budget_are_safely_bounded(self):
        blank = self.np.full((3100, 3100), 170, dtype=self.np.uint8)
        output = boost._pad_upscale(blank, self.cv2)
        self.assertLessEqual(output.size, boost.MAX_OUTPUT_PIXELS)
        self.assertEqual(output.ndim, 2)
        self.assertTrue(output.shape[0] > 0)

    def test_detected_qr_can_be_rectified_with_known_truth(self):
        source = self.image()
        height, width = source.shape
        src = self.np.float32([
            [0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]
        ])
        dst = self.np.float32([[20, 20], [250, 30], [230, 245], [12, 220]])
        warped = self.cv2.warpPerspective(
            source, self.cv2.getPerspectiveTransform(src, dst),
            (280, 280), borderValue=255
        )
        rectified = boost._enhance(
            warped, {"cv2": self.cv2, "numpy": self.np}, "rectify_roi"
        )
        self.assertLessEqual(rectified.size, boost.MAX_OUTPUT_PIXELS)
        decoded, _, _ = self.cv2.QRCodeDetector().detectAndDecode(rectified)
        self.assertEqual(decoded, "geometry-proof-17")

    def test_no_qr_detected_falls_back_without_false_claim(self):
        blank = self.np.full((700, 700), 230, dtype=self.np.uint8)
        restored = boost._enhance(blank, {"cv2": self.cv2, "numpy": self.np}, "rectify_roi")
        self.assertLessEqual(restored.size, boost.MAX_OUTPUT_PIXELS)
        self.assertEqual(self.cv2.QRCodeDetector().detectAndDecode(restored)[0], "")

    def test_wechat_receives_curated_enhanced_strategies_only(self):
        filtered = decoder_filters(
            ["V01", "V10"], [f"B{i:02d}" for i in range(1, 10)],
            ["native"], ["native", "opencv", "wechat"], True
        )
        self.assertEqual(
            filtered["wechat"], {"B02", "B04", "B06", "B08", "B09", "W01"}
        )
        self.assertEqual(filtered["native"], {"V01", "V10"})
        original = decoder_filters(
            ["V01", "V10"], [f"B{i:02d}" for i in range(1, 10)],
            ["wechat"], ["wechat"], True
        )
        self.assertTrue({"V01", "V10"}.issubset(original["wechat"]))

    def test_wechat_model_receives_enhanced_pixels_end_to_end(self):
        import scan_images
        import wechat_decoder_adapter

        class FakeModel:
            def detectAndDecode(self, image):
                observed.append(tuple(image.shape))
                # Deliberately mock *routing*, not model accuracy:
                # the fixture returns its test identity only for B02+ pixels.
                if image.ndim == 2 and image.shape[0] >= 100:
                    return ["mocked-wechat-result"], [[0, 0, 1, 1]]
                return [], []

        observed = []
        def fake_standard_decoders(registry, cv2, zxingcpp=None):
            registry.register("opencv", lambda image, context, options:
                              {"payloads": [], "candidate_count": 0},
                              version="fixture-no-decode")
            registry.register("zxingcpp", None, version="UNAVAILABLE", available=False,
                              unavailable_reason="not needed for fixture")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_dir = root / "input" / "G5" / "WAVES_QR"
            image_dir.mkdir(parents=True)
            q = self.qrcode.QRCode(
                version=1, box_size=1, border=0,
                error_correction=self.qrcode.constants.ERROR_CORRECT_M,
            )
            q.add_data("fixture-17")
            q.make(fit=False)
            source = (1 - self.np.asarray(q.get_matrix(), dtype=self.np.uint8)) * 255
            self.assertTrue(self.cv2.imwrite(str(image_dir / "crop.png"), source))
            model_count = 2 if int(self.cv2.__version__.split(".", 1)[0]) >= 5 else 4
            model_dir = root / "models"
            model_dir.mkdir()
            names = []
            for i in range(model_count):
                name = f"test-model-{i}.dat"
                (model_dir / name).write_bytes(b"fixture-not-real-weights")
                names.append(name)
            config = model_dir / "models.json"
            config.write_text(json.dumps({"models": names}), encoding="utf-8")
            with (patch.dict(os.environ, {"QR_AUDIT_WECHAT_MODEL_CONFIG": str(config)}),
                  patch.object(scan_images, "register_builtin_decoders",
                               side_effect=fake_standard_decoders),
                  patch.object(wechat_decoder_adapter, "_factory",
                               return_value=lambda *paths: FakeModel())):
                result = scan_images.run_scan(
                    root / "input", root / "report", decoders=["opencv"],
                    workers=1, boost_fallback=True, wechat_fallback=True
                )
            self.assertEqual(result["status"], "PASS_BASELINE_ONLY")
            evidence = Path(result["evidence"])
            attempts = [json.loads(line) for line in (evidence / "attempts.jsonl").read_text(
                encoding="utf-8").splitlines()]
            matched = [r for r in attempts if r["decoder_id"] == "wechat"
                       and r["strategy_id"] == "B02" and r["status"] == "DECODED"]
            self.assertEqual(len(matched), 1)
            self.assertEqual(matched[0]["payload"], "mocked-wechat-result")
            self.assertTrue(observed)
            summary = json.loads((evidence / "fallback-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["rescue_by_decoder"]["wechat"], 1)
            self.assertEqual(summary["rescue_by_strategy_decoder"]["B02/wechat"], 1)
            self.assertEqual(summary["status"], "OBSERVED_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
