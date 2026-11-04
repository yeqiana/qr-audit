import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

SKIP_STATUSES = {"SKIPPED_EARLY_STOP", "SKIPPED_INELIGIBLE", "NOT_RUN"}
EXECUTED_STATUSES = {"DECODED", "DETECTED_ONLY", "NO_DECODE", "ERROR"}

def load_jsonl(path):
    rows = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: JSON 无效: {exc}")
    return rows

def p95_nearest_rank(values):
    values = sorted(float(x) for x in values)
    return values[max(0, math.ceil(0.95 * len(values)) - 1)] if values else None

def strategy_metadata(manifest, registry):
    registry_map = {s["strategy_id"]: s for s in registry.get("strategies", [])}
    source = manifest.get("strategies")
    if source:
        result = {}
        for item in source:
            if isinstance(item, str):
                base = dict(registry_map.get(item, {"strategy_id": item}))
            else:
                sid = item["strategy_id"]
                base = dict(registry_map.get(sid, {}))
                base.update(item)
            result[base["strategy_id"]] = base
        return result, manifest.get("strategy_order") or list(result)
    result = dict(registry_map)
    return result, manifest.get("strategy_order") or list(result)

def analyze(manifest, attempts, registry):
    strategies, order = strategy_metadata(manifest, registry)
    image_meta = {x["image_id"]: x for x in manifest.get("images", [])}
    for a in attempts:
        image_meta.setdefault(a["image_id"], {"image_id": a["image_id"],
                          "group_id": a.get("group_id", "UNKNOWN"), "side_id": a.get("side_id", "UNKNOWN")})
    image_ids = set(image_meta)
    decoders = manifest.get("decoders", [])
    decoder_ids = [x if isinstance(x, str) else x["decoder_id"] for x in decoders]
    if not decoder_ids:
        decoder_ids = sorted({a.get("decoder_id", "UNKNOWN") for a in attempts})
    seen = {(a.get("image_id"), a.get("strategy_id"), a.get("decoder_id")) for a in attempts}
    expected = {(img, sid, dec) for img in image_ids for sid in order for dec in decoder_ids}
    missing = sorted(expected - seen)
    early = [a for a in attempts if a.get("status") == "SKIPPED_EARLY_STOP"]
    execution_incomplete = [a for a in attempts if a.get('status') in ('ERROR', 'NOT_RUN') or (a.get('status')=='SKIPPED_INELIGIBLE' and str(a.get('skip_reason','')).startswith(('NOT_IMPLEMENTED','DECODER_UNAVAILABLE')))]
    complete = manifest.get('mode') == 'contribution' and not missing and not early and not execution_incomplete and bool(expected)

    success_by_strategy = {sid: set() for sid in order}
    attempts_by_strategy = defaultdict(list)
    durations = defaultdict(list)
    payloads_by_image = defaultdict(set)
    for a in attempts:
        sid = a.get("strategy_id")
        success_by_strategy.setdefault(sid, set())
        attempts_by_strategy[sid].append(a)
        if a.get("status") in EXECUTED_STATUSES:
            try:
                durations[sid].append(float(a.get("duration_ms", 0)))
            except (TypeError, ValueError):
                pass
        if a.get("status") == "DECODED":
            success_by_strategy[sid].add(a["image_id"])
            payloads_by_image[a["image_id"]].add(a.get("payload_sha256") or str(a.get("payload", "UNSPECIFIED")))

    all_success = set().union(*success_by_strategy.values()) if success_by_strategy else set()
    cumulative = set()
    strategy_rows = []
    for index, sid in enumerate(order, 1):
        successes = success_by_strategy.get(sid, set())
        new = successes - cumulative
        repeated = successes & cumulative
        others = set().union(*(v for k, v in success_by_strategy.items() if k != sid)) if len(success_by_strategy) > 1 else set()
        exclusive = len(successes - others) if complete else "NA_INCOMPLETE"
        records = attempts_by_strategy.get(sid, [])
        executed = [a for a in records if a.get("status") in EXECUTED_STATUSES]
        skipped = [a for a in records if a.get("status") in SKIP_STATUSES]
        ds = durations.get(sid, [])
        meta = strategies.get(sid, {})
        strategy_rows.append({
            "strategy_id": sid, "strategy_order": index,
            "name_zh": meta.get("name_zh", sid), "family": meta.get("family", "UNCLASSIFIED"),
            "success_images": len(successes), "ordered_new_success": len(new),
            "repeat_success": len(repeated), "exclusive_contribution": exclusive,
            "attempt_count": len(executed), "skipped_count": len(skipped),
            "average_duration_ms": round(sum(ds) / len(ds), 3) if ds else None,
            "p95_duration_ms": p95_nearest_rank(ds), "contribution_metrics_valid": complete
        })
        cumulative |= successes

    groups = defaultdict(set)
    for sid, meta in strategies.items():
        tags = set(meta.get("groups", [])) | set(meta.get("tags", []))
        if meta.get("family"):
            tags.add("family:" + meta["family"])
        for tag in tags:
            groups[tag].add(sid)

    def removal_rows(scope, filter_ids):
        filtered = {sid: success_by_strategy.get(sid, set()) & filter_ids for sid in order}
        baseline = set().union(*filtered.values()) if filtered else set()
        result = []
        for tag, members in sorted(groups.items()):
            remaining = set().union(*(v for sid, v in filtered.items() if sid not in members)) if len(filtered) > len(members) else set()
            result.append({"scope": scope, "strategy_group": tag, "strategy_ids": ";".join(sorted(members)),
                           "baseline_success_images": len(baseline),
                           "success_after_removal": len(remaining) if complete else "NA_INCOMPLETE",
                           "removal_loss": len(baseline - remaining) if complete else "NA_INCOMPLETE",
                           "contribution_metrics_valid": complete})
        return result

    removal = removal_rows("GLOBAL", image_ids)
    for group in sorted({str(x.get("group_id", "UNKNOWN")) for x in image_meta.values()}):
        subset = {i for i, m in image_meta.items() if str(m.get("group_id", "UNKNOWN")) == group}
        removal.extend(removal_rows("GROUP:" + group, subset))
    for side in sorted({str(x.get("side_id", "UNKNOWN")) for x in image_meta.values()}):
        subset = {i for i, m in image_meta.items() if str(m.get("side_id", "UNKNOWN")) == side}
        removal.extend(removal_rows("SIDE:" + side, subset))

    conflicts = sorted(img for img, vals in payloads_by_image.items() if len(vals) > 1 and "UNSPECIFIED" not in vals)
    reasons = []
    if missing: reasons.append("manifest/attempts 预期组合缺失: " + str(len(missing)))
    if early: reasons.append("存在提前停止记录: " + str(len(early)))
    if execution_incomplete: reasons.append('存在未运行/报错/未实现组合: ' + str(len(execution_incomplete)))
    if manifest.get("mode") != "contribution": reasons.append("mode 不是 contribution")
    if not expected: reasons.append("预期组合为空")
    # Each scope needs its own strategy-level incremental counts, not just family removal loss.
    scoped_rows=[]
    scope_sets=[('GLOBAL', image_ids)]
    scope_sets += [('GROUP:'+group, {i for i,m in image_meta.items() if str(m.get('group_id','UNKNOWN'))==group}) for group in sorted({str(m.get('group_id','UNKNOWN')) for m in image_meta.values()})]
    scope_sets += [('SIDE:'+side, {i for i,m in image_meta.items() if str(m.get('side_id','UNKNOWN'))==side}) for side in sorted({str(m.get('side_id','UNKNOWN')) for m in image_meta.values()})]
    scope_sets += [('PAIR:'+pair, {i for i,m in image_meta.items() if str(m.get('pair_key','UNKNOWN'))==pair}) for pair in sorted({str(m.get('pair_key')) for m in image_meta.values() if m.get('pair_key')})]
    for scope, ids in scope_sets:
        prior=set()
        for sid in order:
            successes=success_by_strategy.get(sid,set()) & ids
            others=set().union(*(v & ids for k,v in success_by_strategy.items() if k!=sid)) if len(success_by_strategy)>1 else set()
            scoped_rows.append({'scope':scope,'strategy_id':sid,'success_images':len(successes),
                               'ordered_new_success':len(successes-prior),'repeat_success':len(successes & prior),
                               'exclusive_contribution':len(successes-others) if complete else 'NA_INCOMPLETE'})
            prior|=successes
    return {
        "schema_version": "1.0", "mode": manifest.get("mode", "scan"),
        "contribution_metrics_valid": complete, "incomplete_reasons": reasons,
        "image_count": len(image_ids), "all_success_images": len(all_success),
        "payload_conflict_images": len(conflicts), "payload_conflict_image_ids": conflicts,
        "missing_expected_combinations": [{"image_id": x[0], "strategy_id": x[1], "decoder_id": x[2]} for x in missing],
        "strategy_metrics": strategy_rows, "strategy_metrics_by_scope": scoped_rows, "group_removal_loss": removal
    }

def write_csv(path, rows):
    if not rows:
        return
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

def main():
    p = argparse.ArgumentParser(description="计算二维码策略顺序新增、重复、独占贡献和整类移除损失。")
    p.add_argument("--manifest", required=True)
    p.add_argument("--attempts", required=True)
    p.add_argument("--registry", default=str(Path(__file__).resolve().parents[1] / "assets" / "strategy-registry.initial.json"))
    p.add_argument("--out-dir", required=True)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        attempts = load_jsonl(args.attempts)
        registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
        result = analyze(manifest, attempts, registry)
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        targets = [out / "contribution-summary.json", out / "strategy-contribution.csv", out / "strategy-group-removal-loss.csv", out / "strategy-contribution-by-scope.csv"]
        if not args.overwrite:
            existing = [str(x) for x in targets if x.exists()]
            if existing:
                raise FileExistsError("拒绝覆盖已有文件: " + ", ".join(existing))
        targets[0].write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_csv(targets[1], result["strategy_metrics"])
        write_csv(targets[2], result["group_removal_loss"])
        write_csv(targets[3], result["strategy_metrics_by_scope"])
        print(json.dumps({"status": "PASS" if result["contribution_metrics_valid"] else "INCOMPLETE",
                          "image_count": result["image_count"], "all_success_images": result["all_success_images"],
                          "incomplete_reasons": result["incomplete_reasons"], "output": str(out.resolve())}, ensure_ascii=False))
        return 0 if result["contribution_metrics_valid"] else 3
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
