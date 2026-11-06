"""Standalone module-recovery tests: checksums are supplied by real decoders."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ai_qr_adapter
import module_recovery


class GridRecoveryTests(unittest.TestCase):
    def setUp(self):
        try:
            import cv2
            import numpy as np
            import qrcode
            import zxingcpp
        except ImportError as exc:
            self.skipTest(f"optional test dependency absent: {exc}")
        self.cv2, self.np, self.qrcode, self.zxing = cv2, np, qrcode, zxingcpp

    def _qr(self, payload, border=4):
        q = self.qrcode.QRCode(version=3, box_size=4, border=border,
            error_correction=self.qrcode.constants.ERROR_CORRECT_H)
        q.add_data(payload)
        q.make(fit=False)
        return q, self.np.asarray(
            q.make_image(fill_color="black", back_color="white").convert("L")
        )

    def test_function_matrix_matches_qr_spec(self):
        q, img = self._qr("QR-AUDIT-SYNTH-20261106-05-005-V2")
        expected = module_recovery.function_pattern(3, self.np)
        actual = self.np.asarray(q.get_matrix(), dtype=self.np.uint8)[4:-4, 4:-4]
        mask = expected >= 0
        self.assertGreater(mask.sum(), 100)
        self.np.testing.assert_array_equal(actual[mask], expected[mask])

    def test_cropped_qr_recovers_without_payload_guess(self):
        payload = "QR-AUDIT-SYNTH-20261106-05-005-V2"
        _, original = self._qr(payload)
        cropped = original[22:-22,22:-22].copy()
        result = module_recovery.recover_image(
            cropped, self.cv2, self.np, self.zxing,
            max_version=4, top_k=24, max_decode=48
        )
        self.assertIn(payload, [x["payload"] for x in result["hits"]])
        self.assertGreater(result["candidate_count"], 0)

    def test_pair_fusion_is_decoder_verified(self):
        payload = "QR-AUDIT-SYNTH-20261106-05-005-V2"
        _, original = self._qr(payload)
        left, right = original[20:-20, 20:-20], original[22:-22, 22:-22]
        result = module_recovery.recover_pair(
            left, right, self.cv2, self.np, self.zxing,
            max_version=4, top_k=16, max_decode=48,
        )
        self.assertIn(payload, [x["payload"] for x in result["hits"]])

    def test_blank_never_fabricates_qr_text(self):
        blank = self.np.full((140,140),255,dtype=self.np.uint8)
        result = module_recovery.recover_image(
            blank,self.cv2,self.np,self.zxing,max_version=4,top_k=12,max_decode=24
        )
        self.assertEqual(result["hits"], [])

    def test_grid_rejects_non_uint8_and_pixel_over_budget(self):
        for image in (
            self.np.zeros((100,100),dtype=self.np.float32),
            self.np.zeros((3000,3000),dtype=self.np.uint8),
        ):
            with self.assertRaisesRegex(ValueError,"MODULE_GRID_INPUT_OUT_OF_BOUNDS"):
                module_recovery.sample_candidates(image,self.cv2,self.np)

    def test_config_toggle_is_opt_in_and_bounded(self):
        with tempfile.TemporaryDirectory() as dirname:
            folder=Path(dirname)
            (folder/"model.pt").write_bytes(b"fake-contract-weight")
            config=folder/"local.json"
            body={"schema_version":"1.0","detector":{
                    "provider":"ultralytics","weights":"model.pt",
                    "device":"cuda:0","imgsz":640,"batch":1}}
            config.write_text(json.dumps(body),encoding="utf-8")
            parsed=ai_qr_adapter.read_config(config)
            self.assertFalse(parsed["module_recovery"]["enabled"])
            self.assertEqual(parsed["imgsz"],640)
            body["module_recovery"]={"enabled":True,"max_version":10,
                                      "top_k":24,"max_decode":48}
            config.write_text(json.dumps(body),encoding="utf-8")
            self.assertTrue(ai_qr_adapter.read_config(config)["module_recovery"]["enabled"])
            body["module_recovery"]["max_version"]=40
            config.write_text(json.dumps(body),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"AI_MAX_VERSION_OUT_OF_BOUNDS"):
                ai_qr_adapter.read_config(config)
            body["module_recovery"]["max_version"]=10
            body["detector"]["batch"]=2
            config.write_text(json.dumps(body),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"AI_BATCH_OUT_OF_BOUNDS"):
                ai_qr_adapter.read_config(config)

    def test_model_inference_forces_640_and_batch_one(self):
        seen=[]
        class Fake:
            def predict(self,**kwargs):
                seen.append(kwargs)
                return []
        config={"confidence":.2,"max_candidates":8,
                "device":"cuda:0","imgsz":640,"batch":1}
        self.assertEqual(ai_qr_adapter._infer_boxes(
            Fake(),self.np.zeros((64,64,3),dtype=self.np.uint8),
            self.cv2,self.np,config),[])
        self.assertEqual(seen[0]["imgsz"],640)
        self.assertEqual(seen[0]["batch"],1)
        self.assertEqual(seen[0]["device"],"cuda:0")


if __name__ == "__main__":
    unittest.main()
