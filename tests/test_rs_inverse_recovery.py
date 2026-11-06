"""Offline Reed–Solomon erasure and strict NN inverse-resampling tests.

Test payloads are synthetic fixtures; production algorithms never consume them.
"""
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import qr_erasure_recovery
import module_recovery


class ErasureRecoveryTests(unittest.TestCase):
    def setUp(self):
        try:
            import numpy as np
            import cv2
            import qrcode
            import zxingcpp
        except ImportError as exc:
            self.skipTest(f"optional image dependency absent: {exc}")
        self.np,self.cv2,self.qrcode,self.zxing=np,cv2,qrcode,zxingcpp

    def build(self):
        qr=self.qrcode.QRCode(version=2,
              error_correction=self.qrcode.constants.ERROR_CORRECT_M,
              box_size=5,border=4)
        text="QR-AUDIT-SYNTH-20261106-05-006-V3"
        qr.add_data(text)
        qr.make(fit=False)
        img=self.np.asarray(qr.make_image(fill_color="black",back_color="white").convert("L"))
        self.assertEqual(qr.version,2)
        self.assertEqual(img.shape,(165,165))
        return qr,img,text

    def test_erasure_only_gf256_solves_full_codeword_syndromes(self):
        qr,_,_=self.build()
        original=list(qr.data_cache)
        self.assertEqual(len(original),44)
        self.assertEqual(qr_erasure_recovery.correct_erasures(original,[]),original)
        indices=[0,2,3,8,11,17,21,23,25,27,32,35,37,40,43]
        damaged=original.copy()
        for index in indices:
            damaged[index]=0
        corrected=qr_erasure_recovery.correct_erasures(damaged,indices)
        self.assertEqual(corrected,original)
        self.assertIsNone(qr_erasure_recovery.correct_erasures(damaged,list(range(17))))
        damaged=original.copy()
        damaged[20]^=0x40
        self.assertIsNone(qr_erasure_recovery.correct_erasures(damaged,[]))

    def test_exact_version2_m_modules_verified_without_fixture_data(self):
        qr,img,payload=self.build()
        matrix=self.np.asarray(qr.get_matrix(),dtype=self.np.uint8)[4:-4,4:-4]
        candidate={
            "version":2,
            "expected":module_recovery.function_pattern(2,self.np),
            "values":self.np.where(matrix,0,255).astype(self.np.uint8),
            "valid":self.np.ones((25,25),dtype=bool),
            "threshold":0,
        }
        result=qr_erasure_recovery.recover_erasure_grid(candidate,self.np)
        self.assertIsNotNone(result)
        self.np.testing.assert_array_equal(result["grid"],matrix)
        self.assertEqual(result["erased_codewords"],0)

    def test_cropped_qr_v2_m_recovers_via_true_rs_erasures(self):
        _,original,payload=self.build()
        cropped=original[26:-26,26:-26]
        result=module_recovery.recover_image(
            cropped,self.cv2,self.np,self.zxing,
            max_version=4,top_k=24,max_decode=48,
            enable_rs_erasures=True,max_extra_decode=12,
        )
        self.assertEqual(result["recovery_method"],"rs_erasure_v2m")
        self.assertEqual([x["payload"] for x in result["hits"]],[payload])
        self.assertLessEqual(result["rs_erasure_codewords"],16)

    def test_nearest_downup_inverse_recovers_decoder_verified_payload(self):
        try:
            import scipy
        except ImportError:
            self.skipTest("Scipy optional inverse solver is absent")
        _,original,payload=self.build()
        small=self.cv2.resize(original,(36,36),interpolation=self.cv2.INTER_AREA)
        blurry=self.cv2.resize(small,(165,165),interpolation=self.cv2.INTER_NEAREST)
        result=module_recovery.recover_image(
            blurry,self.cv2,self.np,self.zxing,
            max_version=4,top_k=24,max_decode=48,
            enable_inverse_resample=True,max_extra_decode=12,
        )
        self.assertEqual(result["recovery_method"],"inverse_nearest_v2")
        self.assertEqual([x["payload"] for x in result["hits"]],[payload])
        self.assertEqual(result["inverse_source_resolution"],36)

    def test_nearest_inverse_rejects_unrelated_photo_and_noise(self):
        from qr_inverse_resample import invert_nearest_modules
        rng=self.np.random.default_rng(13)
        expected=module_recovery.function_pattern(2,self.np)
        for image in (
            rng.integers(0,256,(165,165),dtype=self.np.uint8),
            self.np.full((165,165),255,dtype=self.np.uint8),
            rng.integers(0,256,(150,150),dtype=self.np.uint8),
        ):
            self.assertIsNone(invert_nearest_modules(image,self.cv2,self.np,expected,.85))

    def test_rs_format_invalid_or_non_v2_fails_closed(self):
        np=self.np
        candidate={
            "version":2,
            "expected":module_recovery.function_pattern(2,np),
            "values":np.full((25,25),255,dtype=np.uint8),
            "valid":np.zeros((25,25),dtype=bool),
            "threshold":0,
        }
        self.assertIsNone(qr_erasure_recovery.recover_erasure_grid(candidate,np))
        candidate["version"]=3
        self.assertIsNone(qr_erasure_recovery.recover_erasure_grid(candidate,np))



class ThirdStageConfigTests(unittest.TestCase):
    def test_opt_in_rs_and_inverse_budgets(self):
        import json
        import tempfile
        import ai_qr_adapter
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"local.pt").write_bytes(b"only-contract-not-a-real-model")
            config=root/"ai.json"
            body={"schema_version":"1.0",
                  "detector":{"provider":"ultralytics","weights":"local.pt",
                              "imgsz":640,"batch":1},
                  "module_recovery":{"enabled":True,"rs_erasures":True,
                      "inverse_resample":True,"max_extra_decode":12}}
            config.write_text(json.dumps(body),encoding="utf-8")
            parsed=ai_qr_adapter.read_config(config)
            self.assertTrue(parsed["module_recovery"]["rs_erasures"])
            self.assertTrue(parsed["module_recovery"]["inverse_resample"])
            self.assertEqual(parsed["module_recovery"]["max_extra_decode"],12)
            body["module_recovery"]["inverse_resample"]="true"
            config.write_text(json.dumps(body),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"AI_MODULE_RECOVERY_OPTION_INVALID"):
                ai_qr_adapter.read_config(config)

    def test_rejects_unbounded_rs_attempt_count(self):
        import json
        import tempfile
        import ai_qr_adapter
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"local.pt").write_bytes(b"only-contract-not-a-real-model")
            config=root/"ai.json"
            body={"schema_version":"1.0",
                  "detector":{"provider":"ultralytics","weights":"local.pt"},
                  "module_recovery":{"enabled":True,"rs_erasures":True,
                      "max_extra_decode":1000000}}
            config.write_text(json.dumps(body),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"AI_MAX_EXTRA_DECODE_OUT_OF_BOUNDS"):
                ai_qr_adapter.read_config(config)

if __name__=="__main__":
    unittest.main()
