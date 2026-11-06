"""A report must validate against the strategy registry that actually ran."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import build_report_models as reports


class ReportRegistryTests(unittest.TestCase):
    def _run(self,with_effective):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name)
            evidence=folder/"evidence"
            evidence.mkdir()
            (evidence/"inventory.json").write_text(
                json.dumps({"groups":[]}),encoding="utf-8")
            (evidence/"inventory-after.json").write_text(
                json.dumps({"groups":[]}),encoding="utf-8")
            (evidence/"attempts.jsonl").write_text("",encoding="utf-8")
            (evidence/"run-manifest.json").write_text(
                json.dumps({"strategy_order":["V01","A01"],
                "input_consistency":{"status":"STABLE"}}),encoding="utf-8")
            if with_effective:
                expected={"strategies":[
                    {"strategy_id":"V01"},{"strategy_id":"A01"}]}
                (evidence/"strategy-registry.effective.json").write_text(
                    json.dumps(expected),encoding="utf-8")
            else:
                expected=json.loads(
                    (ROOT/"assets/strategy-registry.initial.json").read_text(
                        encoding="utf-8"))
            validation={"status":"PASS","structural_status":"PASS",
                        "provenance_status":"VERIFIED","errors":[]}
            with patch.object(reports,"validate",return_value=validation) as v, \
                 patch.object(reports,"render",return_value=[]):
                result=reports.build(folder)
            self.assertEqual(v.call_args.kwargs["registry"],expected)
            self.assertEqual(result["validation"]["status"],"PASS")
            overview=json.loads(
                (folder/"overview-model.json").read_text(encoding="utf-8"))
            self.assertEqual(overview["reports"][0]["status"],"COMPLETE")

    def test_scan_uses_effective_registered_strategies(self):
        self._run(True)

    def test_legacy_scan_falls_back_to_initial_registry(self):
        self._run(False)


if __name__=="__main__":
    unittest.main()
