"""Frozen-source and bounded image concurrency smoke tests (no CV libraries)."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import scan_images


class FreshImageWorkersTests(unittest.TestCase):
    def test_source_snapshot_detects_changes_and_missing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scanner.py"
            path.write_text("version-a", encoding="utf-8")
            before = {"files": [{
                "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }]}
            self.assertEqual(scan_images.verify_source_snapshot(before)["status"], "STABLE")
            path.write_text("version-b", encoding="utf-8")
            self.assertEqual(scan_images.verify_source_snapshot(before)["status"], "CHANGED")
            path.unlink()
            self.assertEqual(scan_images.verify_source_snapshot(before)["status"], "CHANGED")

    def test_bounded_parallel_results_are_ordered_and_complete(self):
        items = list(range(41))
        for workers in (1, 2, 4, 8):
            self.assertEqual(
                list(scan_images.ordered_image_map(lambda x: (x, x * 2), items, workers)),
                [(x, x * 2) for x in items],
            )
        self.assertEqual(list(scan_images.ordered_image_map(lambda x: x, [], 4)), [])

    def test_serial_parallel_scan_have_identical_evidence_cells(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = root / "input"
            for side in ("WAVES_QR", "WAVES_QR_RAW"):
                path = inputs / "group" / side / "sample.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("fake-" + side).encode("utf-8"))

            def fake_register(specs, strategies, decoders, context):
                strategies.register(
                    "V01", lambda path, ctx, params: path, input_mode="source_file"
                )
                decoders.register(
                    "fixture", lambda path, ctx, options: {
                        "status": "DECODED", "payloads": ["test-only"],
                        "candidate_count": 1,
                    }
                )
                return []

            outputs = []
            with patch.object(scan_images, "get_library", side_effect=RuntimeError("offline")), \
                 patch.object(scan_images, "load_adapter_modules", side_effect=fake_register):
                for workers in (1, 4):
                    result = scan_images.run_scan(
                        inputs, root / "reports", decoders=["fixture"],
                        adapter_modules=["fixture"], workers=workers,
                    )
                    self.assertEqual(result["status"], "PASS_BASELINE_ONLY")
                    self.assertEqual(result["source_consistency"]["status"], "STABLE")
                    evidence = Path(result["evidence"])
                    manifest = json.loads(
                        (evidence / "run-manifest.json").read_text(encoding="utf-8")
                    )
                    self.assertEqual(manifest["execution"]["workers"], workers)
                    rows = [
                        json.loads(line)
                        for line in (evidence / "attempts.jsonl").read_text(
                            encoding="utf-8"
                        ).splitlines()
                    ]
                    outputs.append([
                        (row["image_id"], row["strategy_id"],
                         row["decoder_id"], row["status"],
                         row["payload_sha256"])
                        for row in rows
                    ])
            self.assertEqual(outputs[0], outputs[1])

    def test_rejects_invalid_worker_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            for workers in (0, 9, -1, True, "4"):
                with self.assertRaisesRegex(ValueError, "workers"):
                    scan_images.run_scan(temp, temp, workers=workers)


if __name__ == "__main__":
    unittest.main()
