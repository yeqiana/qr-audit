"""Unit and synthetic end-to-end tests of optional local AI fallback.

An injected test detector simulates local YOLO boxes. No remote models are
used and no synthetic success is described as real-world improvement.
"""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))

import ai_qr_adapter
import ai_recovery_core
from fallback_pipeline import compose_registry,decoder_filters,summarize


class AiConfigTests(unittest.TestCase):
    def _config(self,folder,**overrides):
        root=Path(folder)
        (root/"local-qr-detector.pt").write_bytes(b"dummy-weight-for-offline-contract")
        body={"schema_version":"1.0","detector":{
              "provider":"ultralytics","weights":"local-qr-detector.pt",
              "confidence":.2,"max_candidates":8},"max_attempts":30}
        body.update(overrides)
        cfg=root/"ai.json"
        cfg.write_text(json.dumps(body),encoding="utf-8")
        return cfg

    def test_config_requires_existing_local_weights(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=self._config(d)
            loaded=ai_qr_adapter.read_config(cfg)
            self.assertTrue(Path(loaded["detector_model"]).is_file())
            self.assertEqual(loaded["max_candidates"],8)
            body=json.loads(cfg.read_text())
            body["detector"]["weights"]="missing-model.pt"
            cfg.write_text(json.dumps(body),encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                ai_qr_adapter.read_config(cfg)

    def test_config_rejects_invalid_model_provider_and_budgets(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=self._config(d)
            body=json.loads(cfg.read_text())
            body["detector"]["provider"]="text-generative-model"
            cfg.write_text(json.dumps(body),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"AI_DETECTOR_PROVIDER_UNSUPPORTED"):
                ai_qr_adapter.read_config(cfg)
            body["detector"]["provider"]="ultralytics"
            body["max_attempts"]=100000
            cfg.write_text(json.dumps(body),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"AI_MAX_ATTEMPTS_OUT_OF_BOUNDS"):
                ai_qr_adapter.read_config(cfg)

    def test_composed_ai_can_run_without_boost_or_wechat(self):
        base={"strategies":[{"strategy_id":"V01"},{"strategy_id":"V02"}]}
        composed=compose_registry(base,{"strategies":[]},False,with_ai=True)
        self.assertEqual([x["strategy_id"] for x in composed["strategies"]],
                         ["V01","V02","A01"])
        self.assertEqual(composed["fallback_composition"]["ai_strategy_id"],"A01")
        filters=decoder_filters(["V01","V02"],[],["native"],["native","ai"],
                                False,with_ai=True)
        self.assertEqual(filters["native"],{"V01","V02"})
        self.assertEqual(filters["ai"],{"A01"})
        result=summarize(
            [{"strategy_id":"A01","image_id":"image-1","status":"DECODED",
              "decoder_id":"ai"}],
            {"fallback_composition":composed["fallback_composition"],
             "images":[{"image_id":"image-1","pair_id":None}]}
        )
        self.assertEqual(result["newly_rescued_images"],1)
        self.assertEqual(result["rescue_by_decoder"]["ai"],1)


class AiImageTests(unittest.TestCase):
    def setUp(self):
        try:
            import cv2,numpy as np,qrcode
        except ImportError as exc:
            self.skipTest(f"optional image libraries absent: {exc}")
        self.cv2,self.np,self.qrcode=cv2,np,qrcode

    def _qr(self):
        q=self.qrcode.QRCode(version=2,box_size=7,border=4,
                            error_correction=self.qrcode.constants.ERROR_CORRECT_M)
        q.add_data("qr-ai-synthetic-17")
        q.make(fit=False)
        gray=self.np.asarray(
            q.make_image(fill_color="black",back_color="white").convert("L"))
        return self.cv2.cvtColor(gray,self.cv2.COLOR_GRAY2BGR)

    def test_local_detected_roi_can_decode_real_qr_payload(self):
        image=self._qr()
        h,w=image.shape[:2]
        found=ai_recovery_core.recover(
            image,[{"bbox":[0,0,w,h],"confidence":.95}],
            self.cv2,self.np,max_candidates=2,max_attempts=30,grid_versions=2)
        self.assertIn("qr-ai-synthetic-17",found["payloads"])
        self.assertEqual(found["candidate_count"],1)
        self.assertGreater(found["ai_decode_calls"],0)

    def test_invalid_boxes_and_blank_image_never_generate_content(self):
        image=self.np.full((200,200,3),255,dtype=self.np.uint8)
        boxes=[{"bbox":[-400,-400,-20,-20],"confidence":.99},
               {"bbox":[20,20,180,180],"confidence":.5}]
        found=ai_recovery_core.recover(image,boxes,self.cv2,self.np,
                                       max_attempts=20)
        self.assertEqual(found["payloads"],[])
        self.assertEqual(found["candidate_count"],1)

    def test_geometry_grid_hypotheses_are_bounded(self):
        gray=self.cv2.cvtColor(self._qr(),self.cv2.COLOR_BGR2GRAY)
        guessed=list(ai_recovery_core.module_grids(gray,self.cv2,self.np,max_versions=3))
        self.assertEqual(len(guessed),6)
        self.assertTrue(all(value.size<=ai_recovery_core.MAX_VARIANT_PIXELS
                            for _,value in guessed))

    def test_main_scan_falls_through_to_ai_with_injected_detector(self):
        import scan_images
        root=None
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            cfg=self._make_config(root)
            img_dir=root/"input"/"G5"/"WAVES_QR"
            img_dir.mkdir(parents=True)
            image=self._qr()
            self.assertTrue(self.cv2.imwrite(str(img_dir/"one.png"),image))
            h,w=image.shape[:2]

            class FakeTensor:
                def __init__(self,value):self.value=np.asarray(value)
                def cpu(self):return self
                def numpy(self):return self.value

            np=self.np
            class FakeModel:
                def __init__(self,weight):
                    assert Path(weight).is_file()
                def predict(self,source,**kwargs):
                    boxes=types.SimpleNamespace(
                        xyxy=FakeTensor([[0,0,w,h]]),
                        conf=FakeTensor([.99]))
                    return [types.SimpleNamespace(boxes=boxes,masks=None)]

            def fake_decoders(registry,cv2,zxingcpp=None):
                registry.register("opencv",lambda image,ctx,opts:{
                    "payloads":[],"candidate_count":0
                },version="synthetic-no-decode")
                registry.register("zxingcpp",None,available=False,
                                  unavailable_reason="test-unavailable")
            class FakeUltra:
                YOLO=FakeModel

            real_import=ai_qr_adapter.importlib.import_module
            def injected_import(name,*args,**kwargs):
                return FakeUltra if name=="ultralytics" else real_import(name,*args,**kwargs)
            with (patch.object(scan_images,"register_builtin_decoders",
                               side_effect=fake_decoders),
                  patch.object(ai_qr_adapter.importlib.util,"find_spec",
                               side_effect=lambda name: object() if name=="ultralytics"
                               else __import__("importlib").util.find_spec(name)),
                  patch.object(ai_qr_adapter.importlib,"import_module",
                               side_effect=injected_import)):
                result=scan_images.run_scan(
                    root/"input",root/"reports",decoders=["opencv"],
                    ai_fallback=True,ai_model_config=str(cfg),workers=1)
            self.assertEqual(result["status"],"PASS_BASELINE_ONLY")
            self.assertEqual(result["fallback"]["newly_rescued_images"],1)
            evidence=Path(result["evidence"])
            manifest=json.loads((evidence/"run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["fallback_composition"]["ai_strategy_id"],"A01")
            attempt=[json.loads(row) for row in
                     (evidence/"attempts.jsonl").read_text(encoding="utf-8").splitlines()
                     if row.strip()]
            decoded=[row for row in attempt if
                     row["strategy_id"]=="A01" and row["status"]=="DECODED"]
            self.assertEqual(len(decoded),1)
            self.assertEqual(decoded[0]["payload"],"qr-ai-synthetic-17")
            self.assertEqual(manifest["source_consistency"]["status"],"STABLE")

    def _make_config(self,root):
        (root/"detector.pt").write_bytes(b"fixture-detector")
        cfg=root/"ai.json"
        cfg.write_text(json.dumps({"schema_version":"1.0",
            "detector":{"provider":"ultralytics","weights":"detector.pt"}}))
        return cfg


if __name__=="__main__":
    unittest.main()
