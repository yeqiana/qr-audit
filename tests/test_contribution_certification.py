"""Fail-closed regression tests for contribution certification boundaries."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import analyze_contributions
import evidence_contract
from test_tools import FixtureFactory


class ContributionCertificationGateTests(unittest.TestCase):
    def test_caller_supplied_pass_cannot_certify_scan_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            before, after, registry, manifest, attempts = FixtureFactory.build(temp)
            manifest["mode"] = "scan"
            forged = {
                "status": "PASS", "structural_status": "PASS",
                "provenance_status": "VERIFIED",
                "contribution_metrics_valid": True, "errors": [],
            }
            result = analyze_contributions.analyze(
                manifest, attempts, registry,
                inventory=before, inventory_after=after, validation=forged,
            )
            self.assertFalse(result["contribution_metrics_valid"])
            self.assertEqual(
                result["strategy_metrics"][0]["exclusive_contribution"], "NA_INCOMPLETE"
            )

    def test_adapter_unsupported_pure_mode_is_not_image_ineligibility(self):
        with tempfile.TemporaryDirectory() as temp:
            before, after, registry, manifest, attempts = FixtureFactory.build(temp)
            row = next(item for item in attempts if item["status"] == "NO_DECODE")
            row["status"] = "SKIPPED_INELIGIBLE"
            row["skip_reason"] = "PURE_OPTION_NOT_SUPPORTED_BY_THIS_OPENCV_ADAPTER"
            result = evidence_contract.validate(
                manifest, attempts, registry, before, after
            )
            self.assertFalse(result["contribution_metrics_valid"])
            self.assertIn(
                "cannot be counted as ineligible", "\n".join(result["errors"])
            )

    def test_true_image_ineligibility_remains_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            before, after, registry, manifest, attempts = FixtureFactory.build(temp)
            row = next(item for item in attempts if item["status"] == "NO_DECODE")
            row["status"] = "SKIPPED_INELIGIBLE"
            row["skip_reason"] = "IMAGE_DIMENSIONS_OUT_OF_RANGE"
            result = evidence_contract.validate(
                manifest, attempts, registry, before, after
            )
            self.assertTrue(result["contribution_metrics_valid"], result["errors"])


if __name__ == "__main__":
    unittest.main()
