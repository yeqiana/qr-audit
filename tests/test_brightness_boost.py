"""Brightness-oriented B06-B08 experiments; known synthetic QR truth."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import executor_registry
import recognition_boost_adapter as boost


class BrightnessBoostTests(unittest.TestCase):
    def setUp(self):
        try:
            import cv2
            import numpy as np
            import qrcode
        except ImportError as exc:
            self.skipTest(f"optional image test dependencies not installed: {exc}")
        self.cv2 = cv2
        self.np = np
        qr = qrcode.QRCode(
            version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1, border=0,
        )
        qr.add_data("bright-17")
        qr.make(fit=False)
        self.code = (1 - np.asarray(qr.get_matrix(), dtype=np.uint8)) * 255
        self.strategies = executor_registry.StrategyExecutorRegistry()
        boost.register_qr_audit(
            self.strategies, None, {"cv2": cv2, "numpy": np}
        )
        self.context = {"cv2": cv2, "numpy": np}

    def apply(self, strategy_id, image):
        return self.strategies.get(strategy_id).transform(image, self.context, {})

    def test_brightness_output_is_bounded_and_binary_when_requested(self):
        for sid in ("B06", "B07", "B08"):
            with self.subTest(strategy=sid):
                image = self.apply(sid, self.code)
                self.assertEqual(image.ndim, 2)
                self.assertEqual(image.dtype, self.np.uint8)
                self.assertLessEqual(image.size, boost.MAX_OUTPUT_PIXELS)
                self.assertEqual(image.shape, (self.code.shape[0] * 4 + 32,
                                               self.code.shape[1] * 4 + 32))
                if sid != "B06":
                    self.assertTrue(set(self.np.unique(image)).issubset({0, 255}))

    def test_flatfield_recovers_known_payload_under_dark_and_gradient(self):
        np, cv2 = self.np, self.cv2
        detector = cv2.QRCodeDetector()
        sources = {
            "dark_low_contrast": (self.code * .10 + 115).astype(np.uint8),
            "uneven_lighting": np.clip(
                np.linspace(45, 150, self.code.shape[1])[None, :] + self.code * .30,
                0, 255
            ).astype(np.uint8),
        }
        for label, source in sources.items():
            with self.subTest(sample=label):
                output = self.apply("B08", source)
                decoded, _, _ = detector.detectAndDecode(output)
                self.assertEqual(decoded, "bright-17")

    def test_blank_image_never_returns_a_false_payload(self):
        for sid in ("B06", "B07", "B08"):
            with self.subTest(strategy=sid):
                blank = self.np.full((45, 45), 235, dtype=self.np.uint8)
                decoded, _, _ = self.cv2.QRCodeDetector().detectAndDecode(
                    self.apply(sid, blank)
                )
                self.assertEqual(decoded, "")


if __name__ == "__main__":
    unittest.main()
