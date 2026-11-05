"""Real input identity and output preservation regression tests (stdlib only)."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import inventory_images
import regression_gate
import scan_images


def make_evidence(root, label, decoded, *, changed_image=False, payload="historical"):
    root = Path(root) / label
    images = root / "input" / "group"
    for side in ("WAVES_QR", "WAVES_QR_RAW"):
        folder = images / side
        folder.mkdir(parents=True)
        value = ("new-input" if changed_image else "stable-image") if side == "WAVES_QR" else "other-input"
        (folder / "sample.png").write_bytes(value.encode("utf-8"))
    inventory = inventory_images.build_inventory(root / "input")
    evidence = root / "report" / "evidence"
    evidence.mkdir(parents=True)
    run_id = label
    manifest = {"run_id": run_id, "strategy_order": ["V01", "V10"],
                "strategies": [
                    {"strategy_id": "V01", "executor_status": "REGISTERED"},
                    {"strategy_id": "V10", "executor_status": "NOT_CONNECTED"},
                ]}
    rows = []
    for group in inventory["groups"]:
        for side in group["sides"]:
            for file in side["files"]:
                is_decoded = side["side_id"] in decoded
                record = {
                    "attempt_id": f"{label}-{file['file_id']}",
                    "run_id": label, "image_id": file["file_id"],
                    "input_sha256": file["sha256"],
                    "status": "DECODED" if is_decoded else "NO_DECODE",
                    "payload": payload if is_decoded else None,
                    "payloads": [payload] if is_decoded else [],
                    "strategy_id": "V01", "decoder_id": "zxingcpp",
                }
                rows.append(record)
    (evidence / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False), encoding="utf-8")
    (evidence / "run-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (evidence / "attempts.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8"
    )
    return evidence


class RegressionGateTests(unittest.TestCase):
    def test_same_hash_and_same_payload_pass_independent_root(self):
        with tempfile.TemporaryDirectory() as folder:
            old = make_evidence(folder, "old", {"WAVES_QR"})
            new = make_evidence(folder, "new", {"WAVES_QR"})
            result = regression_gate.compare_directories(old, new)
            self.assertEqual(result["status"], "PASS_NON_REGRESSION")
            self.assertEqual(result["baseline_success_images"], 1)
            self.assertEqual(result["baseline_success_pairs"], 1)
            self.assertEqual(result["lost_success_images"], 0)
            self.assertEqual(result["lost_success_pairs"], 0)

    def test_losing_one_side_is_regression_even_if_pair_stays_success(self):
        with tempfile.TemporaryDirectory() as folder:
            old = make_evidence(folder, "old", {"WAVES_QR", "WAVES_QR_RAW"})
            new = make_evidence(folder, "new", {"WAVES_QR_RAW"})
            result = regression_gate.compare_directories(old, new)
            self.assertEqual(result["status"], "BLOCKED_RECOGNITION_REGRESSION")
            self.assertEqual(result["lost_success_images"], 1)
            self.assertEqual(result["lost_success_pairs"], 0)

    def test_losing_only_successful_side_blocks_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            old = make_evidence(folder, "old", {"WAVES_QR"})
            new = make_evidence(folder, "new", set())
            result = regression_gate.compare_directories(old, new)
            self.assertEqual(result["lost_success_images"], 1)
            self.assertEqual(result["lost_success_pairs"], 1)
            self.assertEqual(result["status"], "BLOCKED_RECOGNITION_REGRESSION")

    def test_payload_change_fails_even_when_success_counters_same(self):
        with tempfile.TemporaryDirectory() as folder:
            old = make_evidence(folder, "old", {"WAVES_QR"}, payload="correct")
            new = make_evidence(folder, "new", {"WAVES_QR"}, payload="changed")
            result = regression_gate.compare_directories(old, new)
            self.assertEqual(result["baseline_success_images"], result["candidate_success_images"])
            self.assertEqual(result["baseline_success_pairs"], result["candidate_success_pairs"])
            self.assertEqual(result["payload_changed_images"], 1)
            self.assertEqual(result["status"], "BLOCKED_RECOGNITION_REGRESSION")

    def test_different_input_hash_blocks_comparison(self):
        with tempfile.TemporaryDirectory() as folder:
            old = make_evidence(folder, "old", {"WAVES_QR"})
            new = make_evidence(folder, "new", {"WAVES_QR"}, changed_image=True)
            result = regression_gate.compare_directories(old, new)
            self.assertEqual(result["status"], "BLOCKED_INPUT_CHANGED")
            self.assertEqual(result["hash_mismatches"], 1)

    def test_new_image_success_only_is_additional_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            old = make_evidence(folder, "old", {"WAVES_QR"})
            new = make_evidence(folder, "new", {"WAVES_QR", "WAVES_QR_RAW"})
            result = regression_gate.compare_directories(old, new)
            self.assertEqual(result["status"], "PASS_NON_REGRESSION")
            self.assertEqual(result["gained_success_images"], 1)
            self.assertEqual(result["gained_success_pairs"], 0)

    def test_rejects_duplicate_attempt_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            old = make_evidence(folder, "old", {"WAVES_QR"})
            new = make_evidence(folder, "new", {"WAVES_QR"})
            path = new / "attempts.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("\n".join(lines + lines[:1]) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate attempt_id"):
                regression_gate.compare_directories(old, new)

    def test_refuses_missing_required_legacy_executor_before_creating_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "input").mkdir()
            with self.assertRaisesRegex(ValueError, "REQUIRED_STRATEGY_NOT_CONNECTED: V10"):
                scan_images.run_scan(root / "input", root / "results",
                                     required_strategies=["V10"])
            self.assertFalse((root / "results").exists())

    def test_legacy_string_identity_can_be_compared_without_plaintext(self):
        digest = hashlib.sha256(b"older-code").hexdigest()
        row = {
            "status": "DECODED", "payload": None,
            "payloads": [{"identity": "UTF8_TEXT:" + digest}],
        }
        self.assertEqual(regression_gate._identities(row), {
            ("sha256", "decoded_text_utf8", digest)
        })
        row["payloads"][0]["text"] = "tampered"
        with self.assertRaisesRegex(ValueError, "contradicts"):
            regression_gate._identities(row)

    def test_versioned_installer_contains_boost_adapter_and_regression_gate(self):
        import install_tools
        with tempfile.TemporaryDirectory() as folder:
            result = install_tools.install(folder)
            self.assertEqual(result["status"], "INSTALLED")
            exported = Path(result["path"])
            self.assertTrue((exported / "scripts" / "recognition_boost_adapter.py").is_file())
            self.assertTrue((exported / "scripts" / "regression_gate.py").is_file())
            self.assertTrue((exported / "assets" / "strategy-registry.boost.json").is_file())

    def test_cli_block_exit_code_when_scan_regressed(self):
        with tempfile.TemporaryDirectory() as folder:
            old = make_evidence(folder, "old", {"WAVES_QR"})
            new = make_evidence(folder, "new", set())
            self.assertEqual(regression_gate.main([
                "--baseline-evidence", str(old),
                "--candidate-evidence", str(new),
            ]), 3)


if __name__ == "__main__":
    unittest.main()
