"""Build three per-group report models from validated evidence and one shared MD/HTML renderer."""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from evidence_contract import payload_identities, payload_identity_label, compare_identity_sets, validate
from render_reports import render


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def attempts_jsonl(path):
    rows = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def safe_dir(name):
    import re
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name).strip(" .")
    return value[:100] or "group"


def _payload_text_map(records):
    result = {}
    for record in records:
        items = record.get("payloads")
        if items is None:
            items = record.get("all_payloads")
        if items is None and record.get("payload") not in (None, ""):
            items = [record["payload"]]
        for item in items or []:
            if isinstance(item, str):
                from evidence_contract import text_identity
                identity = text_identity(item)
                key = (identity["algorithm"], identity["scope"], identity["value"])
                result[key] = item
            elif isinstance(item, dict):
                text_value = item.get("text", item.get("payload"))
                if text_value is not None:
                    from evidence_contract import text_identity
                    identity = item.get("identity") or text_identity(text_value)
                    if isinstance(identity, dict) and all(identity.get(key) for key in ("algorithm", "scope", "value")):
                        key = (identity["algorithm"], identity["scope"], identity["value"])
                        result[key] = text_value
    return result


def result_for_file(file_id, attempts):
    records = attempts.get(file_id, [])
    decoded = [row for row in records if row.get("status") == "DECODED"]
    identity_sets = []
    all_identities = set()
    identity_error = False
    for row in decoded:
        try:
            current = set(payload_identities(row))
        except ValueError:
            current = set()
            identity_error = True
        identity_sets.append(tuple(sorted(current)))
        all_identities.update(current)
    scopes = {(identity[0], identity[1]) for identity in all_identities}
    incomparable = len(scopes) > 1
    conflict = identity_error or any(not identities for identities in identity_sets) or (
        len(set(identity_sets)) > 1 and not incomparable
    )
    if conflict:
        status = "PAYLOAD_CONFLICT"
    elif incomparable:
        status = "NOT_COMPARABLE"
    elif decoded:
        status = "DECODED"
    elif any(row.get("status") == "DETECTED_ONLY" for row in records):
        status = "DETECTED_ONLY"
    elif any(row.get("status") == "ERROR" for row in records):
        status = "ERROR"
    elif any(row.get("status") == "NO_DECODE" for row in records):
        status = "NO_DECODE"
    else:
        status = "NOT_RUN"

    text_map = _payload_text_map(decoded)
    display = []
    for identity in sorted(all_identities):
        display.append(text_map.get(identity, "[hash-only] " + payload_identity_label(identity)))
    executed = [row for row in records if row.get("status") in (
        "DECODED", "DETECTED_ONLY", "NO_DECODE", "ERROR"
    )]
    return {
        "file_id": file_id, "status": status,
        "payload_display": " | ".join(display),
        "payload_identities": sorted(all_identities),
        "strategy": ", ".join(sorted({row.get("strategy_id", "") for row in decoded})),
        "decoder": ", ".join(sorted({row.get("decoder_id", "") for row in decoded})),
        "attempts": len(executed), "skipped": len(records) - len(executed),
        "duration_ms": round(sum(float(row.get("duration_ms", 0) or 0) for row in executed), 2),
        "review": status != "DECODED",
        "decoded": bool(decoded),
    }


def _side_payload_result(results):
    successful = [result for result in results if result["decoded"]]
    if not successful:
        return {"decoded": False, "conflict": False, "identities": set()}
    if any(result["status"] == "PAYLOAD_CONFLICT" for result in successful):
        return {"decoded": True, "conflict": True, "not_comparable": False, "identities": set().union(
            *(result["payload_identities"] for result in successful)
        )}
    if any(result["status"] == "NOT_COMPARABLE" for result in successful):
        return {"decoded": True, "conflict": False, "not_comparable": True, "identities": set().union(
            *(result["payload_identities"] for result in successful)
        )}
    identities = set().union(*(result["payload_identities"] for result in successful))
    # Multiple successful files on one side must agree on their payload set.
    sets = {tuple(result["payload_identities"]) for result in successful}
    return {"decoded": True, "conflict": len(sets) > 1, "not_comparable": False, "identities": identities}


def compare_pair_payloads(pair_status, left_results, right_results):
    left = _side_payload_result(left_results)
    right = _side_payload_result(right_results)
    any_success = left["decoded"] or right["decoded"]
    if pair_status != "PAIRED":
        return ("NOT_COMPARABLE", True, any_success)
    if not left["decoded"] or not right["decoded"]:
        return ("ONE_SIDE_ONLY" if any_success else "NO_SUCCESS", True, any_success)
    if left["conflict"] or right["conflict"]:
        return ("PAYLOAD_CONFLICT", True, any_success)
    if left.get("not_comparable") or right.get("not_comparable"):
        return ("NOT_COMPARABLE", True, any_success)
    comparison = compare_identity_sets(left["identities"], right["identities"])
    if comparison == "SAME":
        return ("SAME", False, any_success)
    if comparison == "DIFFERENT":
        return ("DIFFERENT", True, any_success)
    return ("NOT_COMPARABLE", True, any_success)


def report_model(inventory, manifest, attempts, validation=None):
    validation = validation or {
        "status": "NOT_RUN", "provenance_status": "NOT_VERIFIED",
        "contribution_metrics_valid": False, "errors": ["validation was not supplied"],
    }
    by_image = defaultdict(list)
    for attempt in attempts:
        by_image[attempt["image_id"]].append(attempt)

    output = []
    now = datetime.now(timezone.utc).isoformat()
    strategy_count = len(manifest.get("strategy_order", []))
    for group in inventory.get("groups", []):
        group_name = group["group_name"]
        group_id = group["group_id"]
        original_sides = list(group["sides"])
        if len(original_sides) == 1 and original_sides[0]["side_id"] == "SINGLE":
            side_names = ["SINGLE", inventory["right_directory"]]
            sides = original_sides + [{
                "side_id": inventory["right_directory"], "directory_present": False,
                "files": [], "image_count": 0,
            }]
        else:
            side_names = [inventory["left_directory"], inventory["right_directory"]]
            sides = original_sides

        by_side = {side["side_id"]: side for side in sides}
        files = {
            item["file_id"]: item
            for side in sides for item in side.get("files", [])
        }
        results = {
            file_id: result_for_file(file_id, by_image)
            for file_id in files
        }
        reports = []

        for index, side_name in enumerate(side_names, 1):
            side = by_side.get(side_name, {
                "side_id": side_name, "directory_present": False, "files": [],
            })
            rows = []
            counts = defaultdict(int)
            for item in side.get("files", []):
                result = results[item["file_id"]]
                counts[result["status"]] += 1
                rows.append([
                    item["relative_path"], result["status"], result["strategy"],
                    result["decoder"], {"text": result["payload_display"], "code": True},
                    str(result["duration_ms"]), "是" if result["review"] else "否",
                ])
            needs_review = (
                not side.get("directory_present")
                or counts["NOT_RUN"] > 0
                or counts["NO_DECODE"] > 0
                or counts["DETECTED_ONLY"] > 0
                or counts["ERROR"] > 0
                or counts["PAYLOAD_CONFLICT"] > 0
                or counts["NOT_COMPARABLE"] > 0
                or manifest.get("input_consistency", {}).get("status") != "STABLE"
                or validation.get("provenance_status") != "VERIFIED"
            )
            reports.append({
                "file_stem": f"{index}. {group_name}-{side_name}-扫描结果",
                "title": f"{group_name} / {side_name} 扫描结果",
                "generated_at": now, "status": "PARTIAL" if needs_review else "COMPLETE",
                "metrics": [
                    {"label": "目录存在", "value": str(bool(side.get("directory_present")))},
                    {"label": "图片文件数", "value": len(side.get("files", []))},
                    {"label": "策略定义数", "value": strategy_count},
                    {"label": "实际执行次数", "value": sum(results[x["file_id"]]["attempts"] for x in side.get("files", []))},
                    {"label": "离线解码成功", "value": counts["DECODED"] + counts["PAYLOAD_CONFLICT"]},
                    {"label": "候选检测", "value": counts["DETECTED_ONLY"]},
                    {"label": "载荷冲突", "value": counts["PAYLOAD_CONFLICT"]},
                    {"label": "载荷不可比较", "value": counts["NOT_COMPARABLE"]},
                    {"label": "待人工复核", "value": sum(results[x["file_id"]]["review"] for x in side.get("files", []))},
                ],
                "sections": [
                    {"type": "paragraph", "text": (
                        f"run_id={manifest.get('run_id', 'UNKNOWN')}；目录侧={side_name}；"
                        f"证据结构={validation.get('structural_status', validation.get('status'))}；"
                        f"来源核验={validation.get('provenance_status', 'NOT_VERIFIED')}；"
                        f"输入一致性={manifest.get('input_consistency', {}).get('status', 'NOT_VERIFIED')}；"
                        "微信 App 实扫：NOT_TESTED；业务可用性：NOT_VERIFIED。"
                    )},
                    {"type": "table", "title": "扫描明细",
                     "headers": ["目录/图片名称", "离线状态", "成功策略", "解码器",
                                 "载荷/身份", "实际执行耗时(ms)", "人工复核"],
                     "rows": rows},
                    {"type": "paragraph", "text": (
                        "DECODED 仅表示本地解码器返回载荷；多码按身份集合保留。"
                        "哈希脱敏展示不影响比较身份。原图和历史结果均未修改。"
                    )},
                ],
            })

        left_name, right_name = side_names
        paired_rows = []
        stats = defaultdict(int)
        for pair in group.get("pairs", []):
            left_ids = pair.get("left_file_ids", [])
            right_ids = pair.get("right_file_ids", [])
            left_files = [files[file_id]["relative_path"] for file_id in left_ids if file_id in files]
            right_files = [files[file_id]["relative_path"] for file_id in right_ids if file_id in files]
            left_results = [results[file_id] for file_id in left_ids if file_id in results]
            right_results = [results[file_id] for file_id in right_ids if file_id in results]
            left_status = " / ".join(result["status"] for result in left_results) or "MISSING"
            right_status = " / ".join(result["status"] for result in right_results) or "MISSING"
            consistency, review, any_success = compare_pair_payloads(
                pair.get("pair_status"), left_results, right_results
            )
            if any_success:
                stats["any_success"] += 1
            if consistency in ("DIFFERENT", "PAYLOAD_CONFLICT"):
                stats["payload_conflicts"] += 1
            if consistency == "NOT_COMPARABLE":
                stats["payload_not_comparable"] += 1
            if review:
                stats["review"] += 1
            if pair.get("pair_status") != "PAIRED":
                stats["unpaired"] += 1
            paired_rows.append([
                pair.get("pair_id", ""), pair.get("pair_key", ""), pair.get("pair_status", "UNKNOWN"),
                ", ".join(left_files) or "MISSING", left_status,
                ", ".join(right_files) or "MISSING", right_status,
                "✓" if any_success else "✗", consistency, "是" if review else "否",
            ])

        reports.append({
            "file_stem": f"3. {group_name}-二维码-总扫描结果",
            "title": f"{group_name} / 二维码配对总扫描结果",
            "generated_at": now,
            "status": "PARTIAL" if (
                stats["review"] or manifest.get("input_consistency", {}).get("status") != "STABLE"
            ) else "COMPLETE",
            "metrics": [
                {"label": "图片文件总数", "value": group["stats"]["image_file_count"]},
                {"label": "配对数", "value": group["stats"]["pair_count"]},
                {"label": "任一目录解码通过", "value": stats["any_success"]},
                {"label": "未配对/歧义条目", "value": stats["unpaired"]},
                {"label": "载荷不一致/冲突", "value": stats["payload_conflicts"]},
                {"label": "载荷不可比较", "value": stats["payload_not_comparable"]},
                {"label": "待人工复核", "value": stats["review"]},
            ],
            "sections": [
                {"type": "paragraph", "text": (
                    f"run_id={manifest.get('run_id', 'UNKNOWN')}；组内 pair_id 防止跨组同名混合。"
                    "任一侧有离线解码结果则打 ✓；仅单侧成功仍需复核。"
                    "SAME 仅在哈希算法和数据范围一致且身份集合相等时使用。"
                    "微信实扫 NOT_TESTED，业务有效性 NOT_VERIFIED。"
                )},
                {"type": "table", "title": "配对明细",
                 "headers": ["pair_id", "配对键", "配对情况", f"{left_name} 图片",
                             f"{left_name} 状态", f"{right_name} 图片", f"{right_name} 状态",
                             "任一目录离线解码", "载荷比较", "人工复核"],
                 "rows": paired_rows},
            ],
        })
        output.append({
            "group_id": group_id, "group_name": group_name,
            "reports": reports, "metrics": dict(stats),
        })
    return output


def build(run_root):
    run_root = Path(run_root).resolve()
    evidence = run_root / "evidence"
    inventory = read_json(evidence / "inventory.json")
    manifest = read_json(evidence / "run-manifest.json")
    attempts = attempts_jsonl(evidence / "attempts.jsonl")
    effective_registry_path = evidence / "strategy-registry.effective.json"
    registry_path = (
        effective_registry_path if effective_registry_path.is_file()
        else Path(__file__).resolve().parents[1] / "assets" / "strategy-registry.initial.json"
    )
    registry = read_json(registry_path)
    inventory_after = read_json(evidence / "inventory-after.json")
    validation = validate(
        manifest, attempts, registry=registry, inventory=inventory,
        inventory_after=inventory_after,
    )
    all_models = report_model(inventory, manifest, attempts, validation)
    summary = []
    for number, group in enumerate(all_models, 1):
        group_dir = run_root / (f"{number:02d}-" + safe_dir(group["group_name"]))
        group_dir.mkdir(exist_ok=False)
        model_file = group_dir / "report-model.json"
        model_file.write_text(json.dumps({
            "schema_version": "1.0", "reports": group["reports"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        rendered = render(model_file, group_dir)
        summary.append({
            "group": group["group_name"], "path": str(group_dir),
            "documents": len(rendered), "metrics": group["metrics"],
        })

    overview = {
        "schema_version": "1.0",
        "reports": [{
            "file_stem": "0. 扫描总览", "title": "二维码离线扫描总览",
            "status": "PARTIAL" if validation["status"] != "PASS"
                      or validation["provenance_status"] != "VERIFIED"
                      or manifest.get("input_consistency", {}).get("status") != "STABLE" else "COMPLETE",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": [
                {"label": "图片组数", "value": len(summary)},
                {"label": "输入文件数", "value": len(manifest.get("images", []))},
                {"label": "策略注册数", "value": len(manifest.get("strategy_order", []))},
                {"label": "本次尝试记录数", "value": len(attempts)},
                {"label": "证据结构", "value": validation["structural_status"]},
                {"label": "来源核验", "value": validation["provenance_status"]},
                {"label": "输入一致性", "value": manifest.get("input_consistency", {}).get("status", "NOT_VERIFIED")},
            ],
            "sections": [
                {"type": "paragraph", "text": (
                    "本次扫描严格离线；微信实扫 NOT_TESTED；业务有效性 NOT_VERIFIED。"
                    "来源核验状态与结构校验状态分开显示。"
                )},
                {"type": "table", "title": "各组报告",
                 "headers": ["图片组", "报告目录", "报告数量"],
                 "rows": [[item["group"], item["path"], item["documents"]] for item in summary]},
                {"type": "list", "title": "证据校验问题",
                 "items": validation["errors"] or ["无结构校验错误"]},
            ],
        }],
    }
    overview_file = run_root / "overview-model.json"
    overview_file.write_text(json.dumps(overview, ensure_ascii=False, indent=2), encoding="utf-8")
    render(overview_file, run_root)
    return {"groups": summary, "validation": validation}


def main():
    parser = argparse.ArgumentParser(description="依据 inventory、manifest、attempts 生成每组 3 份 MD + 3 份 HTML。")
    parser.add_argument("--run-root", required=True)
    args = parser.parse_args()
    try:
        result = build(args.run_root)
        print(json.dumps({
            "status": "PASS" if result["validation"]["status"] == "PASS" else "PARTIAL",
            "groups": len(result["groups"]), "reports_per_group": 3,
            "validation": result["validation"],
        }, ensure_ascii=False))
        return 0 if result["validation"]["status"] == "PASS" else 3
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
