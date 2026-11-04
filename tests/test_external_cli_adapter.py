import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import external_cli_adapter
import executor_registry


SYNTHETIC_SCANNER = r'''
import argparse, hashlib, json
p = argparse.ArgumentParser()
for field in ("image", "image-id", "sha256", "run", "strategy", "strategy-id", "decoder-id"):
    p.add_argument("--" + field, required=True)
args = p.parse_args()
payload = "synthetic-" + args.strategy
status = "DECODED"
if args.strategy == "skip": status = "SKIPPED_INELIGIBLE"
if args.strategy == "foreign": status = "DECODED"
response = {
    "run_id": args.run, "image_id": args.image_id,
    "input_sha256": args.sha256,
    "strategy_id": "OTHER" if args.strategy == "foreign" else args.strategy_id,
    "native_strategy": args.strategy,
    "decoder_id": args.decoder_id, "status": status,
    "payloads": [payload] if status == "DECODED" else [],
    "candidate_count": 1 if status == "DECODED" else 0,
    "skip_reason": "SYNTHETIC_INELIGIBLE" if status == "SKIPPED_INELIGIBLE" else None,
}
print(json.dumps(response))
'''


class ExternalCliBridgeTests(unittest.TestCase):
    def make_fixture(self, temp, native_strategy="working"):
        root = Path(temp)
        scanner = root / "mock_scanner.py"
        scanner.write_text(SYNTHETIC_SCANNER, encoding="utf-8")
        image = root / "sample.png"
        image.write_bytes(b"synthetic-image")
        image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
        config = root / "bridge.json"
        config.write_text(json.dumps({
            "schema_version": "1.0", "scanner_version": "synthetic-v1",
            "command": {
                "executable": sys.executable,
                "args": [
                    str(scanner), "--image", "{image_path}",
                    "--image-id", "{image_id}", "--sha256", "{input_sha256}",
                    "--run", "{run_id}", "--strategy", "{native_strategy}",
                    "--strategy-id", "{strategy_id}", "--decoder-id", "{decoder_id}",
                ],
                "timeout_seconds": 10,
            },
            "decoder": {"decoder_id": "native", "native_decoder": "synthetic"},
            "strategies": [{"strategy_id": "V04", "native_strategy": native_strategy}],
            "source_files": [str(scanner)],
        }), encoding="utf-8")
        image_meta = {
            "image_id": "img1", "sha256": image_sha, "path": str(image),
            "relative_path": "sample.png", "group_id": "g1",
            "side_id": "SINGLE", "pair_id": "pair1",
        }
        return config, image_meta

    def register(self, config):
        strategies = executor_registry.StrategyExecutorRegistry()
        decoders = executor_registry.DecoderExecutorRegistry()
        context = {"source_files": [], "dependencies": []}
        with patch.dict(os.environ, {external_cli_adapter.CONFIG_ENV: str(config)}):
            external_cli_adapter.register_qr_audit(strategies, decoders, context)
        return strategies, decoders, context

    def test_real_subprocess_success_correlates_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            config, image = self.make_fixture(temp)
            strategies, decoders, context = self.register(config)
            self.assertEqual(strategies.get("V04").input_mode, "source_file")
            self.assertIn(str(config), context["source_files"])
            decode_context = dict(context, image_meta=image, run_id="runA", strategy_id="V04", decoder_id="native")
            result = decoders.get("native").decode(str(image["path"]), decode_context, {})
            self.assertEqual(result["status"], "DECODED")
            self.assertEqual(result["payloads"], ["synthetic-working"])

    def test_wrong_run_or_strategy_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            config, image = self.make_fixture(temp, "foreign")
            _, decoders, context = self.register(config)
            decode_context = dict(context, image_meta=image, run_id="runA", strategy_id="V04", decoder_id="native")
            with self.assertRaisesRegex(ValueError, "strategy_id"):
                decoders.get("native").decode(image["path"], decode_context, {})

    def test_skipped_is_not_disguised_as_decode_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            config, image = self.make_fixture(temp, "skip")
            _, decoders, context = self.register(config)
            result = decoders.get("native").decode(image["path"], dict(
                context, image_meta=image, run_id="runA", strategy_id="V04", decoder_id="native"
            ), {})
            self.assertEqual(result["status"], "SKIPPED_INELIGIBLE")
            self.assertEqual(result["skip_reason"], "SYNTHETIC_INELIGIBLE")

    def test_wrong_image_hash_fails_before_call(self):
        with tempfile.TemporaryDirectory() as temp:
            config, image = self.make_fixture(temp)
            image["sha256"] = "0" * 64
            _, decoders, context = self.register(config)
            with self.assertRaisesRegex(ValueError, "hash changed"):
                decoders.get("native").decode(image["path"], dict(
                    context, image_meta=image, run_id="runA", strategy_id="V04", decoder_id="native"
                ), {})

    def test_invalid_config_cannot_register_fake_strategies(self):
        with tempfile.TemporaryDirectory() as temp:
            config, image = self.make_fixture(temp)
            data = json.loads(config.read_text(encoding="utf-8"))
            data["strategies"].append(dict(data["strategies"][0]))
            config.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate bridge strategy"):
                self.register(config)


if __name__ == "__main__":
    unittest.main()
