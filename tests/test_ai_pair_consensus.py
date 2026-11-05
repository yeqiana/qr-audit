import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from ai_pair_consensus import audit_pairs


class PairInferenceTests(unittest.TestCase):
    def test_never_converts_pair_hypothesis_into_decode(self):
        inv={"groups":[{"group_id":"G5","pairs":[
            {"pair_id":"p1","left_file_ids":["left"],"right_file_ids":["right"]},
            {"pair_id":"p2","left_file_ids":["l2"],"right_file_ids":["r2"]},
        ]}]}
        attempts=[
            {"image_id":"left","status":"DECODED","payloads":[
                {"identity":{"algorithm":"sha256","scope":"qr-text","value":"abcd"}}]},
            {"image_id":"l2","status":"DECODED","payloads":[
                {"identity":{"algorithm":"sha256","scope":"qr-text","value":"abc"}}]},
            {"image_id":"r2","status":"DECODED","payloads":[
                {"identity":{"algorithm":"sha256","scope":"qr-text","value":"def"}}]},
        ]
        report=audit_pairs(inv,attempts)
        self.assertEqual(report["by_status"]["INFERRED_FROM_PAIR_ONLY"],1)
        self.assertEqual(report["by_status"]["PAYLOAD_CONFLICT_REVIEW"],1)
        self.assertEqual(report["status"],"HYPOTHESIS_ONLY")
        self.assertTrue(all(p["counts_as_newly_decoded"] is False
                            for p in report["pairs"]))
        self.assertEqual(report["pairs"][0]["undecoded_image_ids"],["right"])


if __name__=="__main__":
    unittest.main()
