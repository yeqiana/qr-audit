"""Fail-closed tests for *actually executing* three offline recognition fallbacks."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fallback_pipeline import compose_registry, decoder_filters, summarize
import scan_images


class FallbackPlanTests(unittest.TestCase):
    def test_base_order_and_ids_are_not_replaced(self):
        base = {"schema_version": "1.0", "strategies": [
            {"strategy_id": "V01"}, {"strategy_id": "V10"}, {"strategy_id": "R02"}
        ]}
        boost = {"strategies": [
            {"strategy_id": "B01"}, {"strategy_id": "B02"},
            {"strategy_id": "B06"}, {"strategy_id": "B08"}
        ]}
        plan = compose_registry(base, boost, with_wechat=True)
        self.assertEqual([s["strategy_id"] for s in plan["strategies"]],
                         ["V01", "V10", "R02", "B01", "B02", "B06", "B08", "W01"])
        self.assertEqual([s["strategy_id"] for s in base["strategies"]], ["V01", "V10", "R02"])
        self.assertEqual(plan["fallback_composition"]["wechat_strategy_id"], "W01")
        with self.assertRaisesRegex(ValueError, "FALLBACK_STRATEGY_COLLISION"):
            compose_registry(plan, boost, with_wechat=False)

    def test_decoder_filters_keep_native_source_file_baseline_only(self):
        filters = decoder_filters(
            ["V01", "V10"], ["B01", "B06", "B08"],
            ["native"], ["native", "opencv", "zxingcpp", "wechat"], True
        )
        self.assertEqual(filters["native"], {"V01", "V10"})
        self.assertEqual(filters["opencv"], {"B01", "B06", "B08"})
        self.assertEqual(filters["zxingcpp"], {"B01", "B06", "B08"})
        self.assertEqual(filters["wechat"], {"B06", "B08", "W01"})

    def test_rescue_summary_counts_only_newly_decoded_pairs(self):
        manifest = {
            "fallback_composition": {
                "base_strategy_ids": ["V01", "V10"],
                "boost_strategy_ids": ["B01", "B06", "B07"],
                "wechat_strategy_id": "W01",
            },
            "images": [
                {"image_id": "a", "pair_id": "p1", "pair_status": "PAIRED"},
                {"image_id": "b", "pair_id": "p1", "pair_status": "PAIRED"},
                {"image_id": "c", "pair_id": "p2", "pair_status": "PAIRED"},
                {"image_id": "d", "pair_id": "p2", "pair_status": "PAIRED"},
                {"image_id": "e", "pair_id": "p3", "pair_status": "PAIRED"},
                {"image_id": "f", "pair_id": "p3", "pair_status": "PAIRED"},
            ]
        }
        rows = [
            {"image_id": "a", "strategy_id": "V10", "status": "DECODED"},
            {"image_id": "c", "strategy_id": "B06", "status": "DECODED"},
            {"image_id": "d", "strategy_id": "W01", "status": "DECODED"},
            {"image_id": "b", "strategy_id": "B07", "status": "DECODED"},
        ]
        result = summarize(rows, manifest)
        self.assertEqual(result["baseline_success_images"], 1)
        self.assertEqual(result["newly_rescued_images"], 3)
        self.assertEqual(result["newly_rescued_pairs"], 1)
        self.assertEqual(result["final_success_images"], 4)
        self.assertEqual(result["final_success_pairs"], 2)
        self.assertEqual(result["status"], "OBSERVED_UNVERIFIED")

    def test_missing_wechat_model_fails_before_creating_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_root = Path(tmp) / "input"
            input_root.mkdir()
            with self.assertRaisesRegex(ValueError, "WECHAT_FALLBACK_REQUIRES"):
                scan_images.run_scan(input_root, Path(tmp) / "out",
                                     wechat_fallback=True)
            self.assertFalse((Path(tmp) / "out").exists())

    def test_unmodified_default_still_excludes_boost(self):
        base = json.loads((ROOT / "assets/strategy-registry.initial.json").read_text(encoding="utf-8"))
        self.assertEqual([s["strategy_id"] for s in base["strategies"]],
                         [f"V{i:02d}" for i in range(1, 29)])


class FallbackImageTests(unittest.TestCase):
    def test_boost_runs_after_default_and_preserves_manifest_provenance(self):
        try:
            import cv2
            import numpy as np
            import qrcode
        except ImportError as exc:
            self.skipTest(f"optional image libraries absent: {exc}")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "input" / "G5" / "WAVES_QR"
            folder.mkdir(parents=True)
            qr = qrcode.QRCode(version=1, box_size=1, border=0,
                               error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data("qr-17")
            qr.make(fit=False)
            raw = (1 - np.asarray(qr.get_matrix(), dtype=np.uint8)) * 255
            self.assertTrue(cv2.imwrite(str(folder / "crop.png"), raw))
            outcome = scan_images.run_scan(
                root / "input", root / "results", decoders=["opencv"],
                workers=1, boost_fallback=True
            )
            self.assertEqual(outcome["status"], "PASS_BASELINE_ONLY")
            evidence = Path(outcome["evidence"])
            summary = json.loads((evidence / "fallback-summary.json").read_text(encoding="utf-8"))
            manifest = json.loads((evidence / "run-manifest.json").read_text(encoding="utf-8"))
            effective = json.loads((evidence / "strategy-registry.effective.json").read_text(encoding="utf-8"))
            self.assertEqual([x["strategy_id"] for x in effective["strategies"][:28]],
                             [f"V{i:02d}" for i in range(1, 29)])
            self.assertEqual([x["strategy_id"] for x in effective["strategies"][-9:]],
                             [f"B{i:02d}" for i in range(1, 10)])
            self.assertEqual(manifest["fallback_composition"]["base_strategy_ids"],
                             [f"V{i:02d}" for i in range(1, 29)])
            self.assertEqual(summary["baseline_success_images"], 0)
            self.assertGreaterEqual(summary["newly_rescued_images"], 1)
            attempts = [json.loads(x) for x in (evidence / "attempts.jsonl").read_text(
                encoding="utf-8").splitlines()]
            self.assertTrue(any(x["status"] == "DECODED"
                                and x["strategy_id"].startswith("B")
                                and x["payload"] == "qr-17" for x in attempts))
            # ZXing-C++ is optional in the CI image-only environment;
            # when installed it must be included as a genuine B decoder.
            zxing_attempts = [x for x in attempts if x["decoder_id"] == "zxingcpp"]
            if zxing_attempts:
                self.assertTrue(all(x["strategy_id"].startswith("B")
                                    or x["status"] == "SKIPPED_INELIGIBLE"
                                    or x["status"] == "SKIPPED_EARLY_STOP"
                                    for x in zxing_attempts))
            self.assertEqual(manifest["source_consistency"]["status"], "STABLE")


if __name__ == "__main__":
    unittest.main()
