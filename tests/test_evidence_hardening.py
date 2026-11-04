import base64
import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import evidence_contract
from test_tools import FixtureFactory


class EvidenceHardeningTests(unittest.TestCase):
    def fixture(self, temp):
        return FixtureFactory.build(temp)

    def test_status_cannot_claim_failure_and_decoded_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            before, after, registry, manifest, attempts = self.fixture(temp)
            altered = copy.deepcopy(attempts)
            decoded = next(row for row in altered if row["status"] == "DECODED")
            decoded["status"] = "NO_DECODE"
            check = evidence_contract.validate(manifest, altered, registry, before, after)
            self.assertFalse(check["contribution_metrics_valid"])
            self.assertIn("must not contain decoded payloads", "\n".join(check["errors"]))

    def test_raw_bytes_and_decoded_text_cannot_be_silently_equated(self):
        text = "visible text"
        digest = hashlib.sha256(b"other bytes").hexdigest()
        with self.assertRaisesRegex(ValueError, "requires raw_bytes_base64"):
            evidence_contract.payload_identities({
                "status": "DECODED",
                "payloads": [{"text": text, "identity": {
                    "algorithm": "sha256", "scope": "raw_bytes", "value": digest
                }}],
            })
        actual = evidence_contract.payload_identities({
            "status": "DECODED",
            "payloads": [{
                "text": text,
                "raw_bytes_base64": base64.b64encode(b"other bytes").decode("ascii"),
                "identity": {"algorithm": "sha256", "scope": "raw_bytes", "value": digest},
            }],
        })
        self.assertEqual(actual, [("sha256", "raw_bytes", digest)])

    def test_pair_id_cannot_cross_group_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            before, after, registry, manifest, attempts = FixtureFactory.build(temp, group_count=2)
            altered = copy.deepcopy(manifest)
            first_pair = altered["images"][0]["pair_id"]
            for image in altered["images"][2:]:
                image["pair_id"] = first_pair
            check = evidence_contract.validate(altered, attempts, registry, before, after)
            self.assertFalse(check["contribution_metrics_valid"])
            self.assertIn("pair_id collides across", "\n".join(check["errors"]))

    def test_retry_cannot_mix_not_run_and_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            before, after, registry, manifest, attempts = self.fixture(temp)
            altered = copy.deepcopy(attempts)
            retry = copy.deepcopy(altered[0])
            retry["attempt_id"] += "-retry"
            retry["attempt_index"] = 2
            retry["status"] = "NOT_RUN"
            retry["skip_reason"] = "DECODER_UNAVAILABLE"
            retry["payload"] = None
            retry["payload_sha256"] = None
            retry["payloads"] = []
            altered.append(retry)
            check = evidence_contract.validate(manifest, altered, registry, before, after)
            self.assertFalse(check["contribution_metrics_valid"])
            self.assertIn("mixes NOT_RUN", "\n".join(check["errors"]))


    def test_nested_verified_raw_hash_supports_top_level_identity(self):
        text = "decoded text"
        payload_bytes = b"original raw bytes"
        digest = hashlib.sha256(payload_bytes).hexdigest()
        record = {
            "payload": text, "payload_sha256": digest,
            "payload_hash_algorithm": "sha256", "payload_hash_scope": "raw_bytes",
            "payloads": [{
                "text": text, "raw_bytes_base64": base64.b64encode(payload_bytes).decode(),
                "identity": {"algorithm": "sha256", "scope": "raw_bytes", "value": digest}
            }],
        }
        self.assertEqual(
            evidence_contract.payload_identities(record),
            [("sha256", "raw_bytes", digest)],
        )

if __name__ == "__main__":
    unittest.main()
