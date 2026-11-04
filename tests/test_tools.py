import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_contributions
import audit_source
import build_report_models
import evidence_contract
import executor_registry
import inventory_images
import render_reports
import scan_images
import validate_evidence


class FixtureFactory:
    @staticmethod
    def build(root, group_count=1):
        for index in range(group_count):
            group = Path(root) / f"group-{index}"
            left = group / "WAVES_QR"
            right = group / "WAVES_QR_RAW"
            left.mkdir(parents=True)
            right.mkdir(parents=True)
            (left / "sample.png").write_bytes(f"left-{index}".encode())
            (right / "sample.png").write_bytes(f"right-{index}".encode())

        inventory = inventory_images.build_inventory(root)
        registry = {
            "strategies": [
                {"strategy_id": "A", "name_zh": "策略 A", "family": "family_a", "tags": ["family_a"]},
                {"strategy_id": "B", "name_zh": "策略 B", "family": "family_b", "tags": ["family_b"]},
            ]
        }
        source = Path(root) / "scanner.py"
        source.write_text("synthetic source fingerprint\n", encoding="utf-8")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

        images = []
        pair_map = {}
        for group in inventory["groups"]:
            for pair in group["pairs"]:
                for file_id in pair["left_file_ids"] + pair["right_file_ids"]:
                    pair_map[file_id] = pair
            for side in group["sides"]:
                for item in side["files"]:
                    pair = pair_map[item["file_id"]]
                    images.append({
                        "image_id": item["file_id"], "group_id": group["group_id"],
                        "side_id": side["side_id"], "path": item["absolute_path"],
                        "relative_path": item["relative_path"], "sha256": item["sha256"],
                        "pair_id": pair["pair_id"], "pair_key": pair["pair_key"],
                        "pair_status": pair["pair_status"],
                    })

        inventory_after = copy.deepcopy(inventory)
        manifest = {
            "schema_version": "2.0", "run_id": "run-fixture", "mode": "contribution",
            "input_root": inventory["input_root"],
            "inventory_sha256": evidence_contract.canonical_sha256(inventory),
            "input_inventory_after_sha256": evidence_contract.canonical_sha256({
                key: value for key, value in inventory_after.items() if key != "generated_at"
            }),
            "strategy_registry_sha256": evidence_contract.canonical_sha256(registry),
            "source_fingerprint": {"files": [{"path": str(source), "sha256": source_hash}]},
            "strategy_order": ["A", "B"],
            "strategies": registry["strategies"],
            "decoders": [{"decoder_id": "decoder-1", "version": "fixture-1", "available": True}],
            "images": images,
            "input_consistency": scan_images.compare_inventory_snapshots(inventory, inventory_after),
        }
        attempts = []
        for image in images:
            for strategy_id in ("A", "B"):
                decoded = (
                    (image["side_id"] == "WAVES_QR" and strategy_id == "A")
                    or (image["side_id"] == "WAVES_QR_RAW" and strategy_id == "B")
                )
                row = {
                    "attempt_id": f"run-fixture-{image['image_id']}-{strategy_id}-decoder-1-1",
                    "attempt_index": 1, "run_id": "run-fixture",
                    "image_id": image["image_id"], "group_id": image["group_id"],
                    "side_id": image["side_id"], "relative_path": image["relative_path"],
                    "input_sha256": image["sha256"], "pair_id": image["pair_id"],
                    "strategy_id": strategy_id, "decoder_id": "decoder-1",
                    "status": "DECODED" if decoded else "NO_DECODE",
                    "duration_ms": 1.5, "executed_at": "2026-11-04T00:00:00Z",
                    "payload": f"payload-{image['group_id']}" if decoded else None,
                    "payload_sha256": (
                        hashlib.sha256(f"payload-{image['group_id']}".encode()).hexdigest()
                        if decoded else None
                    ),
                    "payload_hash_algorithm": "sha256" if decoded else None,
                    "payload_hash_scope": "decoded_text_utf8" if decoded else None,
                    "payloads": [f"payload-{image['group_id']}"] if decoded else [],
                    "error": None, "skip_reason": None,
                }
                attempts.append(row)
        return inventory, inventory_after, registry, manifest, attempts


class InventoryTests(unittest.TestCase):
    def test_mixed_pair_and_standalone_directories_are_all_discovered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "paired" / "WAVES_QR").mkdir(parents=True)
            (root / "paired" / "WAVES_QR_RAW").mkdir()
            (root / "paired" / "WAVES_QR" / "a.png").write_bytes(b"a")
            (root / "paired" / "WAVES_QR_RAW" / "a.png").write_bytes(b"b")
            (root / "standalone").mkdir()
            (root / "standalone" / "solo.png").write_bytes(b"c")
            result = inventory_images.build_inventory(root)
            self.assertEqual({g["group_name"] for g in result["groups"]}, {"paired", "standalone"})
            self.assertEqual(result["image_file_count"], 3)

    def test_pair_ids_are_group_scoped_for_same_pair_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for group in ("g1", "g2"):
                for side in ("WAVES_QR", "WAVES_QR_RAW"):
                    folder = root / group / side
                    folder.mkdir(parents=True)
                    (folder / "same.png").write_bytes(f"{group}-{side}".encode())
            result = inventory_images.build_inventory(root)
            pair_ids = [g["pairs"][0]["pair_id"] for g in result["groups"]]
            self.assertEqual(len(set(pair_ids)), 2)

    def test_single_directory_and_report_exclusion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "x.png").write_bytes(b"x")
            (root / "report").mkdir()
            (root / "report" / "ignored.png").write_bytes(b"ignored")
            result = inventory_images.build_inventory(root)
            self.assertEqual(result["image_file_count"], 1)
            self.assertEqual(result["groups"][0]["pairs"][0]["pair_status"], "SINGLE")


class EvidenceContractTests(unittest.TestCase):
    def test_valid_v2_evidence_verifies_all_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            result = evidence_contract.validate(manifest, attempts, registry, inventory, inventory_after)
            self.assertEqual(result["status"], "PASS", result["errors"])
            self.assertEqual(result["provenance_status"], "VERIFIED")
            self.assertTrue(result["contribution_metrics_valid"])

    def test_rejects_foreign_run_image_hash_and_invalid_duration(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            broken = copy.deepcopy(attempts)
            broken[0]["run_id"] = "run-from-another-experiment"
            broken[1]["input_sha256"] = "0" * 64
            broken[2]["duration_ms"] = -0.1
            broken[3]["pair_id"] = "foreign-pair"
            result = evidence_contract.validate(manifest, broken, registry, inventory, inventory_after)
            self.assertEqual(result["status"], "FAIL")
            joined = "\n".join(result["errors"])
            self.assertIn("run_id does not match", joined)
            self.assertIn("input_sha256 does not match", joined)
            self.assertIn("duration_ms", joined)
            self.assertIn("pair_id does not match", joined)
            self.assertFalse(result["contribution_metrics_valid"])

    def test_rejects_payload_hash_mismatch_and_duplicate_retry_index(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            broken = copy.deepcopy(attempts)
            decoded = next(row for row in broken if row["status"] == "DECODED")
            decoded["payload_sha256"] = "0" * 64
            duplicate = copy.deepcopy(broken[0])
            duplicate["attempt_id"] += "-duplicate"
            broken.append(duplicate)
            result = evidence_contract.validate(manifest, broken, registry, inventory, inventory_after)
            joined = "\n".join(result["errors"])
            self.assertIn("payload_sha256 does not match", joined)
            self.assertIn("duplicate attempt_index", joined)
            self.assertFalse(result["contribution_metrics_valid"])

    def test_current_input_file_change_blocks_contribution(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            Path(manifest["images"][0]["path"]).write_bytes(b"changed-after-scan")
            result = evidence_contract.validate(manifest, attempts, registry, inventory, inventory_after)
            self.assertFalse(result["contribution_metrics_valid"])
            self.assertIn("input file SHA-256 changed after scan", "\n".join(result["errors"]))

    def test_after_inventory_cannot_be_forged_as_stable(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            inventory_after["groups"][0]["sides"][0]["files"][0]["sha256"] = "e" * 64
            result = evidence_contract.validate(manifest, attempts, registry, inventory, inventory_after)
            self.assertFalse(result["contribution_metrics_valid"])
            joined = "\n".join(result["errors"])
            self.assertIn("input_inventory_after_sha256 mismatch", joined)
            self.assertIn("input files changed during scan", joined)

    def test_source_fingerprint_change_invalidates_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            source_path = Path(manifest["source_fingerprint"]["files"][0]["path"])
            source_path.write_text("modified source after scan\n", encoding="utf-8")
            result = evidence_contract.validate(manifest, attempts, registry, inventory, inventory_after)
            self.assertFalse(result["contribution_metrics_valid"])
            self.assertIn("source fingerprint is not verified", "\n".join(result["errors"]))

    def test_cli_and_unified_validation_use_the_same_contract(self):
        self.assertIs(validate_evidence.validate, evidence_contract.validate)

    def test_hash_only_payload_requires_explicit_algorithm_and_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            row = next(item for item in attempts if item["status"] == "DECODED")
            row["payload"] = None
            row["payloads"] = []
            row["payload_hash_algorithm"] = None
            row["payload_hash_scope"] = None
            result = evidence_contract.validate(manifest, attempts, registry, inventory, inventory_after)
            self.assertIn("requires explicit payload_hash_algorithm and payload_hash_scope",
                          "\n".join(result["errors"]))

    def test_rejects_truncated_strategy_scope_and_unverified_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            manifest["strategy_order"] = ["A"]
            manifest["strategies"] = [registry["strategies"][0]]
            manifest["strategy_registry_sha256"] = evidence_contract.canonical_sha256(
                {"strategies": [registry["strategies"][0]]}
            )
            result = evidence_contract.validate(manifest, attempts, registry, inventory, inventory_after)
            self.assertIn("strategy_order differs from frozen registry", "\n".join(result["errors"]))
            self.assertFalse(result["contribution_metrics_valid"])

    def test_input_snapshot_detects_changed_added_and_deleted_files(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            after = copy.deepcopy(inventory)
            group = after["groups"][0]
            left_file = group["sides"][0]["files"][0]
            left_file["sha256"] = "f" * 64
            right_file = group["sides"][1]["files"][0]
            group["sides"][1]["files"].remove(right_file)
            added = copy.deepcopy(left_file)
            added["file_id"] = "new-file-id"
            added["relative_path"] = "new.png"
            group["sides"][0]["files"].append(added)
            diff = scan_images.compare_inventory_snapshots(inventory, after)
            self.assertEqual(diff["status"], "CHANGED")
            self.assertEqual(len(diff["changed"]), 1)
            self.assertEqual(len(diff["added"]), 1)
            self.assertEqual(len(diff["deleted"]), 1)


class ContributionTests(unittest.TestCase):
    def test_file_loss_and_pair_loss_are_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp, group_count=2)
            validation = evidence_contract.validate(manifest, attempts, registry, inventory, inventory_after)
            result = analyze_contributions.analyze(
                manifest, attempts, registry, inventory=inventory, inventory_after=inventory_after, validation=validation
            )
            self.assertTrue(result["contribution_metrics_valid"], result["incomplete_reasons"])
            self.assertEqual(result["all_success_images"], 4)
            self.assertEqual(result["eligible_pair_count"], 2)
            self.assertEqual(result["all_success_pairs"], 2)
            file_loss = next(
                row for row in result["file_group_removal_loss"]
                if row["scope"] == "GLOBAL" and row["strategy_group"] == "family:family_a"
            )
            pair_loss = next(
                row for row in result["pair_group_removal_loss"]
                if row["scope"] == "GLOBAL" and row["strategy_group"] == "family:family_a"
            )
            self.assertEqual(file_loss["removal_loss"], 2)
            self.assertEqual(pair_loss["removal_loss"], 0)
            self.assertEqual(len({g["pairs"][0]["pair_id"] for g in inventory["groups"]}), 2)

    def test_multiple_qr_codes_in_one_attempt_are_not_a_payload_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            for row in attempts:
                if row["status"] == "DECODED":
                    row["payloads"] = ["symbol-a", "symbol-b"]
                    row["all_payloads"] = ["symbol-a", "symbol-b"]
                    row["payload"] = "symbol-a"
                    row["payload_sha256"] = hashlib.sha256(b"symbol-a").hexdigest()
            validation = evidence_contract.validate(manifest, attempts, registry, inventory, inventory_after)
            result = analyze_contributions.analyze(
                manifest, attempts, registry, inventory=inventory,
                inventory_after=inventory_after, validation=validation,
            )
            self.assertEqual(result["payload_conflict_images"], 0)
            self.assertEqual(result["payload_not_comparable_images"], 0)

    def test_retry_conflict_invalidates_contribution(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            row = next(item for item in attempts if item["status"] == "DECODED")
            retry = copy.deepcopy(row)
            retry["attempt_id"] += "-retry"
            retry["attempt_index"] = 2
            retry["payload"] = "different"
            retry["payloads"] = ["different"]
            retry["payload_sha256"] = hashlib.sha256(b"different").hexdigest()
            attempts.append(retry)
            result = evidence_contract.validate(manifest, attempts, registry, inventory, inventory_after)
            self.assertFalse(result["contribution_metrics_valid"])
            self.assertIn("retry payload identities conflict", "\n".join(result["errors"]))


class PayloadAndReportTests(unittest.TestCase):
    def test_hash_only_different_payloads_are_not_same(self):
        left_hash = hashlib.sha256(b"left").hexdigest()
        right_hash = hashlib.sha256(b"right").hexdigest()
        left = build_report_models.result_for_file("left", {"left": [{
            "status": "DECODED", "payload_sha256": left_hash,
            "payload_hash_algorithm": "sha256", "payload_hash_scope": "decoded_text_utf8",
        }]})
        right = build_report_models.result_for_file("right", {"right": [{
            "status": "DECODED", "payload_sha256": right_hash,
            "payload_hash_algorithm": "sha256", "payload_hash_scope": "decoded_text_utf8",
        }]})
        state, review, success = build_report_models.compare_pair_payloads(
            "PAIRED", [left], [right]
        )
        self.assertEqual(state, "DIFFERENT")
        self.assertTrue(review)
        self.assertTrue(success)

    def test_different_payload_hash_scopes_are_not_comparable(self):
        left = build_report_models.result_for_file("left", {"left": [{
            "status": "DECODED", "payload_sha256": hashlib.sha256(b"left").hexdigest(),
            "payload_hash_algorithm": "sha256", "payload_hash_scope": "raw_bytes",
        }]})
        right = build_report_models.result_for_file("right", {"right": [{
            "status": "DECODED", "payload_sha256": hashlib.sha256(b"right").hexdigest(),
            "payload_hash_algorithm": "sha256", "payload_hash_scope": "decoded_text_utf8",
        }]})
        state, review, _ = build_report_models.compare_pair_payloads("PAIRED", [left], [right])
        self.assertEqual(state, "NOT_COMPARABLE")
        self.assertTrue(review)

    def test_multi_qr_payload_sets_are_order_independent(self):
        first = build_report_models.result_for_file("a", {"a": [{
            "status": "DECODED", "payloads": ["one", "two"],
        }]})
        second = build_report_models.result_for_file("b", {"b": [{
            "status": "DECODED", "payloads": ["two", "one"],
        }]})
        state, review, _ = build_report_models.compare_pair_payloads(
            "PAIRED", [first], [second]
        )
        self.assertEqual(state, "SAME")
        self.assertFalse(review)

    def test_report_model_uses_same_hash_comparison_and_manual_review(self):
        with tempfile.TemporaryDirectory() as temp:
            inventory, inventory_after, registry, manifest, attempts = FixtureFactory.build(temp)
            left_hash = hashlib.sha256(b"left-payload").hexdigest()
            right_hash = hashlib.sha256(b"right-payload").hexdigest()
            for row in attempts:
                if row["status"] == "DECODED":
                    row["payload"] = None
                    row["payloads"] = []
                    row["payload_sha256"] = (
                        left_hash if row["side_id"] == "WAVES_QR" else right_hash
                    )
                    row["payload_hash_algorithm"] = "sha256"
                    row["payload_hash_scope"] = "decoded_text_utf8"
            validation = {"status": "PASS", "structural_status": "PASS",
                          "provenance_status": "VERIFIED", "errors": []}
            report = build_report_models.report_model(
                inventory, manifest, attempts, validation
            )[0]["reports"][2]
            pair_row = report["sections"][1]["rows"][0]
            self.assertEqual(pair_row[8], "DIFFERENT")
            self.assertEqual(pair_row[9], "是")
            self.assertEqual(pair_row[7], "✓")

    def test_renderer_escapes_untrusted_payload_and_writes_md_html(self):
        model = {
            "schema_version": "1.0",
            "reports": [{
                "file_stem": "safe-report", "title": "<script>alert(1)</script>",
                "status": "PARTIAL", "sections": [{
                    "type": "table", "headers": ["payload", "status"],
                    "rows": [[{"text": "https://example.test/?x=1|<script>", "code": True}, "DECODED"]],
                }],
            }],
        }
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "model.json"
            source.write_text(json.dumps(model), encoding="utf-8")
            result = render_reports.render(source, Path(temp) / "out")
            self.assertEqual(len(result), 1)
            markdown = (Path(temp) / "out" / "safe-report.md").read_text(encoding="utf-8")
            html = (Path(temp) / "out" / "safe-report.html").read_text(encoding="utf-8")
            self.assertIn("\\|", markdown)
            self.assertIn("&lt;script&gt;", html)
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertIn("default-src 'none'", html)


class ExecutorContractTests(unittest.TestCase):
    class FakeImage:
        shape = (8, 8, 3)
        def tobytes(self):
            return b"fake-image"

    def _registries(self, decoder):
        strategies = executor_registry.StrategyExecutorRegistry()
        decoders = executor_registry.DecoderExecutorRegistry()
        strategies.register("S1", lambda image, context, params: image, version="fixture-1")
        strategies.register("S2", lambda image, context, params: image, version="fixture-2")
        decoders.register("D1", decoder, version="decoder-fixture-1")
        return strategies, decoders

    def _image(self):
        return {
            "image_id": "img-1", "group_id": "group-1", "side_id": "L",
            "relative_path": "x.png", "sha256": "a" * 64, "pair_id": "pair-1",
        }

    def test_scan_mode_early_stops_but_contribution_mode_executes_all(self):
        strategies, decoders = self._registries(
            lambda image, context, options: {"payloads": ["ok"], "candidate_count": 1}
        )
        loader = lambda meta: self.FakeImage()
        scan_rows, _ = scan_images.execute_image_matrix(
            "run-1", self._image(), ["S1", "S2"], strategies, decoders,
            ["D1"], "scan", loader, {},
        )
        contribution_rows, _ = scan_images.execute_image_matrix(
            "run-2", self._image(), ["S1", "S2"], strategies, decoders,
            ["D1"], "contribution", loader, {},
        )
        self.assertEqual([row["status"] for row in scan_rows], ["DECODED", "SKIPPED_EARLY_STOP"])
        self.assertEqual([row["status"] for row in contribution_rows], ["DECODED", "DECODED"])

    def test_ineligible_unimplemented_and_exception_are_distinct(self):
        strategies, decoders = self._registries(
            lambda image, context, options: {"payloads": [], "candidate_count": 0}
        )
        strategies.register(
            "S_INELIGIBLE", lambda image, context, params: image,
            applicability=lambda meta, context, params: (False, "LOW_RESOLUTION"),
        )
        strategies.register(
            "S_ERROR", lambda image, context, params: (_ for _ in ()).throw(RuntimeError("fixture failure"))
        )
        rows, _ = scan_images.execute_image_matrix(
            "run-3", self._image(),
            ["S_INELIGIBLE", "S_ERROR", "S_NOT_REGISTERED"],
            strategies, decoders, ["D1"], "contribution",
            lambda meta: self.FakeImage(), {},
        )
        self.assertEqual([row["status"] for row in rows],
                         ["SKIPPED_INELIGIBLE", "ERROR", "NOT_RUN"])
        self.assertEqual(rows[0]["skip_reason"], "LOW_RESOLUTION")
        self.assertIn("fixture failure", rows[1]["error"])
        self.assertIn("NOT_IMPLEMENTED", rows[2]["skip_reason"])

    def test_decoder_hash_only_identity_is_preserved(self):
        digest = hashlib.sha256(b"raw-payload-bytes").hexdigest()
        strategies, decoders = self._registries(
            lambda image, context, options: {
                "payloads": [{
                    "identity": {"algorithm": "sha256", "scope": "raw_bytes", "value": digest}
                }],
                "candidate_count": 1,
            }
        )
        rows, _ = scan_images.execute_image_matrix(
            "run-5", self._image(), ["S1"], strategies, decoders,
            ["D1"], "contribution", lambda meta: self.FakeImage(), {},
        )
        self.assertEqual(rows[0]["status"], "DECODED")
        self.assertEqual(rows[0]["payload_hash_scope"], "raw_bytes")
        self.assertEqual(evidence_contract.payload_identities(rows[0]), [
            ("sha256", "raw_bytes", digest)
        ])

    def test_decoder_exception_is_recorded_as_error(self):
        strategies, decoders = self._registries(
            lambda image, context, options: (_ for _ in ()).throw(RuntimeError("decoder failed"))
        )
        rows, _ = scan_images.execute_image_matrix(
            "run-4", self._image(), ["S1"], strategies, decoders,
            ["D1"], "contribution", lambda meta: self.FakeImage(), {},
        )
        self.assertEqual(rows[0]["status"], "ERROR")
        self.assertIn("decoder failed", rows[0]["error"])


class AuditTests(unittest.TestCase):
    def test_source_search_is_hint_only(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "scanner.py").write_text("cv2.QRCodeDetector()\n", encoding="utf-8")
            result = audit_source.analyze(temp)
            self.assertEqual(result["source_hints"][0]["audit_state"], "HINT_ONLY")


if __name__ == "__main__":
    unittest.main()
