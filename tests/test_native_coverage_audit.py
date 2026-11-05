"""Do not confuse reference strategy registrations with native execution."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from native_coverage_audit import audit


class NativeCoverageTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "run_id": "test-native",
            "strategy_order": ["V01", "V04", "V10", "V11", "V12", "R02"],
            "strategies": [
                {"strategy_id": "V01", "executor_status": "REGISTERED"},
                *[{"strategy_id": sid, "executor_status": "NOT_CONNECTED"}
                  for sid in ("V04", "V10", "V11", "V12")],
                {"strategy_id": "R02", "executor_status": "REGISTERED"},
            ],
        }

    def test_reference_r02_does_not_certify_native_v10(self):
        result = audit(self.manifest, [{
            "strategy_id": "R02", "status": "DECODED", "native_strategy_id": "pure",
            "native_decoder_id": "zxing", "bridge_config_sha256": "a" * 64,
        }])
        self.assertEqual(result["status"], "BLOCKED_NATIVE_WIRING")
        self.assertEqual([x["status"] for x in result["required"]],
                         ["NOT_CONNECTED"] * 4)

    def test_only_full_native_attestation_passes(self):
        attempts = []
        for sid in ("V04", "V10", "V11", "V12"):
            next(x for x in self.manifest["strategies"] if x["strategy_id"] == sid)[
                "executor_status"
            ] = "REGISTERED"
            attempts.append({
                "strategy_id": sid, "status": "DECODED", "native_strategy_id": sid + "-native",
                "native_decoder_id": "zxing", "bridge_config_sha256": "a" * 64,
            })
        result = audit(self.manifest, attempts)
        self.assertEqual(result["status"], "PASS_NATIVE_EXECUTION_EVIDENCE")
        self.assertTrue(all(x["native_attested"] == 1 for x in result["required"]))

    def test_unobserved_or_unattested_is_not_pass(self):
        for x in self.manifest["strategies"]:
            if x["strategy_id"] in ("V04", "V10", "V11", "V12"):
                x["executor_status"] = "REGISTERED"
        self.assertEqual(audit(self.manifest, [])["required"][0]["status"],
                         "NOT_OBSERVED")
        self.assertEqual(audit(self.manifest, [
            {"strategy_id": "V04", "status": "DECODED"}], required=["V04"]
        )["required"][0]["status"], "NATIVE_PROVENANCE_INCOMPLETE")

    def test_unknown_strategy_record_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside frozen registry"):
            audit(self.manifest, [{"strategy_id": "V99", "status": "DECODED"}])


if __name__ == "__main__":
    unittest.main()
