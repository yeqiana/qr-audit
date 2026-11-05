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
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "strategy_count": len(ids)}


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
