"""End-to-end lower-level scan gate: baseline can no longer be skipped by run_scan."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import scan_images


class CoreGateTests(unittest.TestCase):
    def setup_input(self, root, tag):
        inputs = Path(root) / tag / "input" / "group"
        for side, content in (("WAVES_QR", b"stable-image"),
                              ("WAVES_QR_RAW", b"other-input")):
            folder = inputs / side
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "sample.png").write_bytes(content)
        return inputs.parent

    def fake_register(self, specs, strategies, decoders, context):
        strategies.register("V01", lambda path, ctx, _: path, input_mode="source_file")
        decoders.register("fixture", lambda path, ctx, opts: {
            "status": "DECODED", "payloads": ["historical"], "candidate_count": 1,
        })
        return []

    def run_reference(self, root, name, baseline=None):
        with patch.object(scan_images, "get_library", side_effect=RuntimeError("offline")), \
             patch.object(scan_images, "load_adapter_modules", side_effect=self.fake_register):
            return scan_images.run_scan(
                Path(root) / name / "input", Path(root) / name / "reports",
                decoders=["fixture"], adapter_modules=["fixture"],
                baseline_evidence=baseline, require_upgrade_gate=True if baseline else False,
            )

    def test_direct_run_scan_auto_checks_historical_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_input(tmp, "before")
            self.setup_input(tmp, "after")
            old = self.run_reference(tmp, "before")
            new = self.run_reference(tmp, "after", baseline=old["evidence"])
            self.assertEqual(new["status"], "PASS_NON_REGRESSION")
            report = json.loads((Path(new["evidence"]) / "recognition-regression.json").read_text(encoding="utf-8"))
            self.assertEqual(report["lost_success_images"], 0)
            manifest = json.loads((Path(new["evidence"]) / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["recognition_regression_status"], "PASS_NON_REGRESSION")
            self.assertTrue(manifest["upgrade_gate_required"])

    def test_environment_enforces_gate_on_custom_low_level_caller(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_input(tmp, "before")
            self.setup_input(tmp, "after")
            old = self.run_reference(tmp, "before")
            with patch.dict("os.environ", {
                "QR_AUDIT_BASELINE_EVIDENCE": old["evidence"],
                "QR_AUDIT_REQUIRE_BASELINE": "1",
            }):
                new = self.run_reference(tmp, "after")
            self.assertEqual(new["status"], "PASS_NON_REGRESSION")
            self.assertTrue((Path(new["evidence"]) / "recognition-regression.json").is_file())

    def test_bad_baseline_fails_closed_with_original_evidence_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_input(tmp, "new")
            new = self.run_reference(tmp, "new", baseline=Path(tmp) / "missing")
            self.assertEqual(new["status"], "BLOCKED_UNVERIFIABLE")
            self.assertTrue((Path(new["evidence"]) / "recognition-regression.json").is_file())


if __name__ == "__main__":
    unittest.main()
