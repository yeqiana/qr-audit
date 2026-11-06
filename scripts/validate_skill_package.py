import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "SKILL.md", "README.md", "assets/strategy-registry.initial.json",
    "scripts/run.py", "scripts/inventory_images.py", "scripts/scan_images.py",
    "scripts/external_cli_adapter.py",
    "scripts/executor_registry.py", "scripts/evidence_contract.py",
    "scripts/build_report_models.py", "scripts/render_reports.py",
    "scripts/analyze_contributions.py", "scripts/validate_evidence.py",
    "scripts/audit_source.py", "scripts/install_tools.py", "tests/test_tools.py",
    "tests/test_external_cli_adapter.py", "tests/test_runtime_source_file.py",
    "tests/test_evidence_hardening.py", "docs/real-scanner-onboarding.md",
    "tests/test_contribution_certification.py", "docs/local-runner-p0-acceptance.md",
    "tests/test_scan_fresh_workers.py", "docs/scanning-optimization.md",
    "scripts/recognition_boost_adapter.py",
    "assets/strategy-registry.boost.json",
    "tests/test_recognition_boost.py", "docs/recognition-boost.md",
    "scripts/regression_gate.py", "tests/test_regression_gate.py",
    "docs/recognition-regression-gate.md",
    "tests/test_run_scan_gate.py",
    "scripts/native_coverage_audit.py", "tests/test_native_coverage_audit.py",
    "docs/native-coverage-acceptance.md",
    "tests/test_brightness_boost.py", "docs/brightness-experiment.md",
    "scripts/wechat_decoder_adapter.py", "tests/test_wechat_decoder_adapter.py",
    "docs/wechat-decoder-experiment.md",
    "scripts/fallback_pipeline.py", "tests/test_fallback_pipeline.py",
    "tests/test_geometry_recovery.py", "docs/recognition-recovery-v152.md",
    "docs/failure-fallback-usage.md",
    "scripts/ai_recovery_core.py", "scripts/ai_qr_adapter.py",
    "scripts/ai_pair_consensus.py", "assets/ai-recovery.example.json",
    "tests/test_ai_qr_recovery.py", "tests/test_ai_pair_consensus.py",
    "docs/ai-recovery-experiment.md",
    "scripts/module_recovery.py", "tests/test_module_recovery.py",
    "docs/module-recovery-experiment.md", "tests/test_report_effective_registry.py",
]


def check():
    missing = [path for path in REQUIRED if not (ROOT / path).is_file()]
    registry = json.loads((ROOT / "assets/strategy-registry.initial.json").read_text(encoding="utf-8"))
    ids = [item["strategy_id"] for item in registry["strategies"]]
    header = (ROOT / "SKILL.md").read_text(encoding="utf-8").splitlines()[:4]
    errors = []
    if missing:
        errors.append("缺少文件: " + str(missing))
    if ids != [f"V{i:02d}" for i in range(1, 29)]:
        errors.append("28 策略编号错误")
    if "name: qr-audit" not in header:
        errors.append("SKILL 名称不是 qr-audit")
    if any("qr-offline-scan-audit" in path.read_text(encoding="utf-8") for path in ROOT.rglob("*.md")):
        errors.append("残留旧 Skill 名称")
    manifest = json.loads((ROOT / "PACKAGE-MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("version") != "2.0.0-ai.2":
        errors.append("发布清单版本与当前 Skill 版本不匹配")
    listed = set()
    for entry in manifest.get("files", []):
        name = entry.get("path")
        if not isinstance(name, str) or not name or name in listed or (
            Path(name).is_absolute() or ".." in Path(name).parts
        ):
            errors.append("发布清单中的路径无效或重复: " + str(name))
            continue
        listed.add(name)
        path = ROOT / name
        if not path.is_file():
            errors.append("发布文件不存在: " + name)
            continue
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != entry.get("sha256") or len(body) != entry.get("size_bytes"):
            errors.append("发布文件指纹或长度不匹配: " + name)
    for name in REQUIRED:
        if name not in listed:
            errors.append("必需文件未列入发布清单: " + name)
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "strategy_count": len(ids)}


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
