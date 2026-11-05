"""Synthetic QR ground truth checks: opt-in reference algorithms only."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import executor_registry
import recognition_boost_adapter
import scan_images


class RecognitionBoostTests(unittest.TestCase):
    def test_reference_registry_is_distinct_from_original_28(self):
        original = json.loads(
            (ROOT / "assets/strategy-registry.initial.json").read_text(encoding="utf-8")
        )
        boost = json.loads(
            (ROOT / "assets/strategy-registry.boost.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [item["strategy_id"] for item in original["strategies"]],
            [f"V{i:02d}" for i in range(1, 29)],
        )
        self.assertEqual(
            [item["strategy_id"] for item in boost["strategies"]],
            ["B01", "B02", "B03", "B04", "B05"],
        )
        self.assertTrue(boost["policy"]["requires_opt_in"])

    def test_missing_image_dependencies_do_not_silently_register(self):
        with self.assertRaisesRegex(RuntimeError, "BOOST_REQUIRES"):
            recognition_boost_adapter.register_qr_audit(
                executor_registry.StrategyExecutorRegistry(), None,
                {"cv2": None, "numpy": None},
            )

    def test_known_payload_recovered_from_missing_quiet_zone_and_gradient(self):
        try:
            import cv2
            import numpy as np
            import qrcode
        except ImportError as exc:
            self.skipTest(f"Optional recognition test dependencies absent: {exc}")
        expected = "qr-17"
        qr = qrcode.QRCode(
            version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1, border=0,
        )
        qr.add_data(expected)
        qr.make(fit=False)
        pixels = (1 - np.asarray(qr.get_matrix(), dtype=np.uint8)) * 255
        dark = (pixels * 0.10 + 115).astype(np.uint8)
        gradient = np.clip(
            np.linspace(45, 150, pixels.shape[1])[None, :] + pixels * .30,
            0, 255,
        ).astype(np.uint8)
        strategies = executor_registry.StrategyExecutorRegistry()
        recognition_boost_adapter.register_qr_audit(
            strategies, None, {"cv2": cv2, "numpy": np}
        )
        detector = cv2.QRCodeDetector()
        for variant, image, strategy_id in (
            ("missing-quiet-zone", pixels, "B02"),
            ("low-contrast", dark, "B03"),
            ("uneven-lighting", gradient, "B05"),
        ):
            with self.subTest(variant=variant):
                output = strategies.get(strategy_id).transform(
                    image, {"cv2": cv2, "numpy": np}, {}
                )
                decoded, _, _ = detector.detectAndDecode(output)
                self.assertEqual(decoded, expected)

    def test_full_new_run_exposes_selected_registry_and_verified_sources(self):
        try:
            import cv2
            import numpy as np
            import qrcode
        except ImportError as exc:
            self.skipTest(f"Optional recognition test dependencies absent: {exc}")
        from evidence_contract import validate
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inp = root / "input" / "pair" / "WAVES_QR"
            inp.mkdir(parents=True)
            qr = qrcode.QRCode(
                version=1, error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=1, border=0,
            )
            qr.add_data("qr-17")
            qr.make(fit=False)
            raw = (1 - np.asarray(qr.get_matrix(), dtype=np.uint8)) * 255
            self.assertTrue(cv2.imwrite(str(inp / "one.png"), raw))
            registry_path = ROOT / "assets/strategy-registry.boost.json"
            outcome = scan_images.run_scan(
                root / "input", root / "reports", decoders=["opencv"],
                mode="contribution", adapter_modules=["recognition_boost_adapter"],
                workers=1, registry_path=registry_path,
            )
            self.assertEqual(outcome["status"], "PASS_BASELINE_ONLY")
            evidence = Path(outcome["evidence"])
            manifest = json.loads(
                (evidence / "run-manifest.json").read_text(encoding="utf-8")
            )
            attempts = [
                json.loads(line)
                for line in (evidence / "attempts.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(manifest["strategy_order"], ["B01", "B02", "B03", "B04", "B05"])
            self.assertEqual(len(attempts), 5)
            self.assertTrue(any(r["status"] == "DECODED" for r in attempts))
            inventory = json.loads((evidence / "inventory.json").read_text(encoding="utf-8"))
            after = json.loads((evidence / "inventory-after.json").read_text(encoding="utf-8"))
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            check = validate(manifest, attempts, registry, inventory, after)
            self.assertEqual(check["structural_status"], "PASS", check["errors"][:5])
            self.assertEqual(check["provenance_status"], "VERIFIED")
            self.assertTrue(check["contribution_metrics_valid"])


if __name__ == "__main__":
    unittest.main()
