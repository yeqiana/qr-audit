"""qr-audit unified CLI with shared evidence validation."""
import argparse
import json
import sys
from pathlib import Path

import audit_source
import analyze_contributions
import build_report_models
import scan_images
from evidence_contract import validate
from validate_evidence import load_jsonl


def json_print(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="qr-audit 统一入口：scan / audit / contribution / all")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("scan", "all"):
        command = sub.add_parser(name, help="离线扫描并生成每组 3 份 MD + 3 份 HTML")
        command.add_argument("--input-root", required=True)
        command.add_argument("--report-root", required=True)
        command.add_argument("--workspace-root")
        command.add_argument("--decoder", action="append")
        command.add_argument("--adapter-module", action="append", default=[])
        command.add_argument("--experiment-mode", choices=["scan", "contribution"], default="scan")
        command.add_argument("--left-name", default="WAVES_QR")
        command.add_argument("--right-name", default="WAVES_QR_RAW")
        command.add_argument("--max-pixels", type=int, default=50000000)
        command.add_argument("--workers", type=int, default=1,
                             help="1-8 image threads; benchmark before raising the default")
        command.add_argument("--registry-path",
                             help="optional isolated strategy registry; defaults to original V01-V28")
        command.add_argument("--source-root", help="all 模式只读检索源码候选位置")

    audit = sub.add_parser("audit", help="源码候选审计（关键词命中不是实现确认）")
    audit.add_argument("--source-root", required=True)
    audit.add_argument("--output", required=True)

    contribution = sub.add_parser("contribution", help="校验并分析完整贡献度实验")
    contribution.add_argument("--manifest", required=True)
    contribution.add_argument("--attempts", required=True)
    contribution.add_argument("--inventory", required=True)
    contribution.add_argument("--inventory-after", required=True)
    contribution.add_argument("--out-dir", required=True)
    contribution.add_argument(
        "--registry",
        default=str(Path(__file__).resolve().parents[1] / "assets" / "strategy-registry.initial.json"),
    )

    args = parser.parse_args()
    try:
        if args.command == "audit":
            outcome = audit_source.analyze(args.source_root)
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(outcome, stream, ensure_ascii=False, indent=2)
            json_print({
                "status": "HINT_ONLY", "source_files": outcome["files_scanned"],
                "hits": len(outcome["source_hints"]), "file": str(path),
            })
            return 0

        if args.command == "contribution":
            manifest = _load_json(args.manifest)
            attempts = load_jsonl(args.attempts)
            inventory = _load_json(args.inventory)
            inventory_after = _load_json(args.inventory_after)
            registry = _load_json(args.registry)
            check = validate(
                manifest, attempts, registry=registry, inventory=inventory,
                inventory_after=inventory_after,
            )
            if not check["contribution_metrics_valid"]:
                json_print({"status": "BLOCKED_INCOMPLETE_EXPERIMENT", "validation": check})
                return 3
            result = analyze_contributions.analyze(
                manifest, attempts, registry, inventory=inventory,
                inventory_after=inventory_after, validation=check,
            )
            if not result["contribution_metrics_valid"]:
                json_print({
                    "status": "BLOCKED_INCOMPLETE_EXPERIMENT",
                    "reasons": result["incomplete_reasons"],
                })
                return 3
            out = Path(args.out_dir)
            out.mkdir(parents=True, exist_ok=False)
            targets = [
                out / "contribution-summary.json",
                out / "strategy-contribution-file.csv",
                out / "strategy-contribution-pair.csv",
                out / "strategy-group-removal-loss-file.csv",
                out / "strategy-group-removal-loss-pair.csv",
                out / "strategy-contribution-by-scope.csv",
            ]
            targets[0].write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            analyze_contributions.write_csv(targets[1], result["strategy_metrics"])
            analyze_contributions.write_csv(targets[2], result["pair_strategy_metrics"])
            analyze_contributions.write_csv(targets[3], result["file_group_removal_loss"])
            analyze_contributions.write_csv(targets[4], result["pair_group_removal_loss"])
            analyze_contributions.write_csv(targets[5], result["strategy_metrics_by_scope"])
            json_print({
                "status": "PASS", "images": result["image_count"],
                "success_images": result["all_success_images"],
                "eligible_pairs": result["eligible_pair_count"],
                "success_pairs": result["all_success_pairs"], "out_dir": str(out.resolve()),
            })
            return 0

        run_result = scan_images.run_scan(
            args.input_root, args.report_root, args.workspace_root, args.decoder,
            args.max_pixels, args.left_name, args.right_name,
            args.experiment_mode, args.adapter_module, workers=args.workers,
            registry_path=args.registry_path,
        )
        evidence = Path(run_result["evidence"])
        manifest = _load_json(evidence / "run-manifest.json")
        attempts = load_jsonl(evidence / "attempts.jsonl")
        inventory = _load_json(evidence / "inventory.json")
        inventory_after = _load_json(evidence / "inventory-after.json")
        registry = _load_json(
            args.registry_path or
            Path(__file__).resolve().parents[1] / "assets" / "strategy-registry.initial.json"
        )
        check = validate(
            manifest, attempts, registry=registry, inventory=inventory,
            inventory_after=inventory_after,
        )
        report_result = build_report_models.build(run_result["run_root"])
        contribution_output = None
        if args.experiment_mode == "contribution" and check["contribution_metrics_valid"]:
            contribution_result = analyze_contributions.analyze(
                manifest, attempts, registry, inventory=inventory,
                inventory_after=inventory_after, validation=check,
            )
            contribution_dir = evidence / "contribution"
            contribution_dir.mkdir(exist_ok=False)
            (contribution_dir / "contribution-summary.json").write_text(
                json.dumps(contribution_result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            analyze_contributions.write_csv(
                contribution_dir / "strategy-contribution-file.csv", contribution_result["strategy_metrics"]
            )
            analyze_contributions.write_csv(
                contribution_dir / "strategy-contribution-pair.csv", contribution_result["pair_strategy_metrics"]
            )
            analyze_contributions.write_csv(
                contribution_dir / "strategy-group-removal-loss-file.csv", contribution_result["file_group_removal_loss"]
            )
            analyze_contributions.write_csv(
                contribution_dir / "strategy-group-removal-loss-pair.csv", contribution_result["pair_group_removal_loss"]
            )
            analyze_contributions.write_csv(
                contribution_dir / "strategy-contribution-by-scope.csv", contribution_result["strategy_metrics_by_scope"]
            )
            contribution_output = str(contribution_dir)

        if run_result["status"] == "BLOCKED_SOURCE_CHANGED":
            status = "BLOCKED_SOURCE_CHANGED"
            exit_code = 3
        elif run_result["status"] == "BLOCKED_INPUT_CHANGED":
            status = "BLOCKED_INPUT_CHANGED"
            exit_code = 3
        elif args.experiment_mode == "contribution" and not check["contribution_metrics_valid"]:
            status = "BLOCKED_INCOMPLETE_EXPERIMENT"
            exit_code = 3
        elif check["status"] != "PASS":
            status = "BLOCKED_EVIDENCE_INVALID"
            exit_code = 3
        else:
            status = "PASS_BASELINE_ONLY" if args.experiment_mode == "scan" else "PASS_CONTRIBUTION"
            exit_code = 0

        info = {
            "status": status, "run_root": run_result["run_root"],
            "groups": len(report_result["groups"]), "reports_per_group": 3,
            "image_count": run_result["image_count"],
            "decoded_images": run_result["decoded_images"],
            "input_consistency": run_result["input_consistency"],
            "source_consistency": run_result["source_consistency"],
            "workers": run_result["workers"],
            "validation": check, "contribution_output": contribution_output,
            "note": (
                "常规扫描允许提前停止；只有 contribution 模式且全部策略执行器、输入、注册表和源码指纹均核验通过，"
                "才允许输出有效贡献度。"
            ),
        }
        if args.command == "all":
            if args.source_root:
                audit_result = audit_source.analyze(args.source_root)
                audit_path = evidence / "audit-hints.json"
                audit_path.write_text(
                    json.dumps(audit_result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                info["source_audit"] = "HINT_ONLY"
                info["audit_hits"] = len(audit_result["source_hints"])
            info["full_contribution"] = (
                "VALID" if check["contribution_metrics_valid"]
                else "BLOCKED_UNTIL_COMPLETE_CONTRIBUTION_RUN"
            )
        json_print(info)
        return exit_code
    except Exception as exc:
        json_print({"status": "BLOCKED", "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
