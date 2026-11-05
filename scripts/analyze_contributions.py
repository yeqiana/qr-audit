"""Evidence-gated file and pair contribution analysis."""
import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from evidence_contract import (
    EXECUTED_STATUSES, SKIP_STATUSES, payload_identities, validate,
)

def load_jsonl(path):
    rows = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def p95_nearest_rank(values):
    values = sorted(float(x) for x in values)
    return values[max(0, math.ceil(0.95 * len(values)) - 1)] if values else None


def strategy_metadata(manifest, registry):
    registry_map = {item["strategy_id"]: item for item in registry.get("strategies", [])}
    result = {}
    for item in manifest.get("strategies", []):
        if isinstance(item, str):
            base = dict(registry_map.get(item, {"strategy_id": item}))
        else:
            base = dict(registry_map.get(item["strategy_id"], {}))
            base.update(item)
        result[base["strategy_id"]] = base
    order = manifest.get("strategy_order") or list(result)
    return result, order


def aggregate_cells(attempts):
    cells = defaultdict(list)
    for row in attempts:
        cells[(row.get("image_id"), row.get("strategy_id"), row.get("decoder_id"))].append(row)
    outcomes = {}
    retry_conflicts = []
    for key, rows in cells.items():
        rows = sorted(rows, key=lambda item: int(item.get("attempt_index", 1)))
        decoded = [row for row in rows if row.get("status") == "DECODED"]
        identities = []
        for row in decoded:
            try:
                identities.append(tuple(payload_identities(row)))
            except ValueError:
                identities.append(tuple())
        distinct = set(identities)
        if len(distinct) > 1:
            retry_conflicts.append(key)
        outcomes[key] = {
            "status": "DECODED" if decoded else rows[-1].get("status", "NOT_RUN"),
            "payload_identities": set().union(*(set(x) for x in identities)) if identities else set(),
            "attempts": rows,
            "retry_conflict": len(distinct) > 1,
        }
    return outcomes, retry_conflicts


def _family_groups(strategies):
    groups = defaultdict(set)
    for strategy_id, meta in strategies.items():
        tags = set(meta.get("groups", [])) | set(meta.get("tags", []))
        if meta.get("family"):
            tags.add("family:" + meta["family"])
        for tag in tags:
            groups[tag].add(strategy_id)
    return groups


def _metrics_for_units(unit_type, success_by_strategy, unit_meta, order, strategies, complete):
    unit_ids = set(unit_meta)
    cumulative = set()
    rows = []
    for index, strategy_id in enumerate(order, 1):
        successes = success_by_strategy.get(strategy_id, set()) & unit_ids
        others = set().union(*(
            values & unit_ids for key, values in success_by_strategy.items() if key != strategy_id
        )) if len(success_by_strategy) > 1 else set()
        new = successes - cumulative
        repeated = successes & cumulative
        meta = strategies.get(strategy_id, {})
        rows.append({
            "unit_type": unit_type, "strategy_id": strategy_id, "strategy_order": index,
            "name_zh": meta.get("name_zh", strategy_id), "family": meta.get("family", "UNCLASSIFIED"),
            "success_units": len(successes),
            "success_images": len(successes) if unit_type == "FILE" else None,
            "success_pairs": len(successes) if unit_type == "PAIR" else None,
            "ordered_new_success": len(new),
            "repeat_success": len(repeated),
            "exclusive_contribution": len(successes - others) if complete else "NA_INCOMPLETE",
            "contribution_metrics_valid": complete,
        })
        cumulative |= successes
    return rows


def _removal_rows(unit_type, scopes, success_by_strategy, order, strategies, complete):
    groups = _family_groups(strategies)
    rows = []
    for scope_name, scope_ids in scopes:
        filtered = {
            strategy_id: success_by_strategy.get(strategy_id, set()) & scope_ids
            for strategy_id in order
        }
        baseline = set().union(*filtered.values()) if filtered else set()
        for tag, members in sorted(groups.items()):
            remaining = set().union(*(
                values for strategy_id, values in filtered.items() if strategy_id not in members
            )) if len(filtered) > len(members) else set()
            rows.append({
                "unit_type": unit_type, "scope": scope_name, "strategy_group": tag,
                "strategy_ids": ";".join(sorted(members)),
                "baseline_success_units": len(baseline),
                "success_after_removal": len(remaining) if complete else "NA_INCOMPLETE",
                "removal_loss": len(baseline - remaining) if complete else "NA_INCOMPLETE",
                "contribution_metrics_valid": complete,
            })
    return rows


def analyze(manifest, attempts, registry, inventory=None, inventory_after=None, validation=None):
    # A caller-supplied result is not proof that THESE inputs passed verification.
    # Recheck before ever emitting certified exclusive/removal-loss metrics.
    # This intentionally re-hashes sources and input files even if a CLI
    # validated earlier: safety of the direct Python API takes precedence.
    validation = validate(
        manifest, attempts, registry=registry, inventory=inventory,
        inventory_after=inventory_after,
    )
    strategies, order = strategy_metadata(manifest, registry)
    image_meta = {item["image_id"]: item for item in manifest.get("images", [])}
    outcomes, retry_conflicts = aggregate_cells(attempts)
    complete = bool(validation.get("contribution_metrics_valid"))

    file_success = {strategy_id: set() for strategy_id in order}
    file_durations = defaultdict(list)
    image_payload_sets = defaultdict(set)
    for (image_id, strategy_id, decoder_id), outcome in outcomes.items():
        if outcome["status"] == "DECODED":
            file_success.setdefault(strategy_id, set()).add(image_id)
            image_payload_sets[image_id].add(tuple(sorted(outcome["payload_identities"])))
        for attempt in outcome["attempts"]:
            if attempt.get("status") in EXECUTED_STATUSES:
                try:
                    duration = float(attempt.get("duration_ms", 0))
                    if math.isfinite(duration) and duration >= 0:
                        file_durations[strategy_id].append(duration)
                except (TypeError, ValueError):
                    pass

    pair_meta = {}
    image_to_pair = {}
    for image_id, meta in image_meta.items():
        pair_id = meta.get("pair_id")
        if pair_id:
            image_to_pair[image_id] = pair_id
            pair_meta[pair_id] = {
                "group_id": meta.get("group_id"),
                "pair_status": meta.get("pair_status"),
                "pair_key": meta.get("pair_key"),
            }
    eligible_pair_ids = {
        pair_id for pair_id, meta in pair_meta.items() if meta.get("pair_status") == "PAIRED"
    }
    pair_success = {strategy_id: set() for strategy_id in order}
    for strategy_id, image_ids in file_success.items():
        for image_id in image_ids:
            pair_id = image_to_pair.get(image_id)
            if pair_id in eligible_pair_ids:
                pair_success.setdefault(strategy_id, set()).add(pair_id)

    strategy_rows = _metrics_for_units(
        "FILE", file_success, image_meta, order, strategies, complete
    )
    pair_rows = _metrics_for_units(
        "PAIR", pair_success,
        {pair_id: meta for pair_id, meta in pair_meta.items() if pair_id in eligible_pair_ids},
        order, strategies, complete,
    )
    for row in strategy_rows:
        records = [
            attempt for attempt in attempts
            if attempt.get("strategy_id") == row["strategy_id"]
        ]
        executed = [x for x in records if x.get("status") in EXECUTED_STATUSES]
        skipped = [x for x in records if x.get("status") in SKIP_STATUSES]
        durations = file_durations.get(row["strategy_id"], [])
        row.update({
            "attempt_count": len(executed), "skipped_count": len(skipped),
            "average_duration_ms": round(sum(durations) / len(durations), 3) if durations else None,
            "p95_duration_ms": p95_nearest_rank(durations),
        })

    file_scopes = [("GLOBAL", set(image_meta))]
    group_ids = sorted({str(meta.get("group_id", "UNKNOWN")) for meta in image_meta.values()})
    side_ids = sorted({str(meta.get("side_id", "UNKNOWN")) for meta in image_meta.values()})
    file_scopes.extend(
        ("GROUP:" + group_id, {image_id for image_id, meta in image_meta.items()
                               if str(meta.get("group_id", "UNKNOWN")) == group_id})
        for group_id in group_ids
    )
    file_scopes.extend(
        ("SIDE:" + side_id, {image_id for image_id, meta in image_meta.items()
                             if str(meta.get("side_id", "UNKNOWN")) == side_id})
        for side_id in side_ids
    )
    pair_unit_meta = {pair_id: pair_meta[pair_id] for pair_id in eligible_pair_ids}
    pair_scopes = [("GLOBAL", set(pair_unit_meta))]
    pair_scopes.extend(
        ("GROUP:" + group_id, {pair_id for pair_id, meta in pair_unit_meta.items()
                               if str(meta.get("group_id", "UNKNOWN")) == group_id})
        for group_id in sorted({str(meta.get("group_id", "UNKNOWN")) for meta in pair_unit_meta.values()})
    )

    file_removal = _removal_rows("FILE", file_scopes, file_success, order, strategies, complete)
    pair_removal = _removal_rows("PAIR", pair_scopes, pair_success, order, strategies, complete)
    file_scope_metrics = []
    for scope, unit_ids in file_scopes:
        file_scope_metrics.extend(
            {"scope": scope, **row}
            for row in _metrics_for_units("FILE", file_success, {x: image_meta[x] for x in unit_ids},
                                          order, strategies, complete)
        )
    pair_scope_metrics = []
    for scope, unit_ids in pair_scopes:
        pair_scope_metrics.extend(
            {"scope": scope, **row}
            for row in _metrics_for_units("PAIR", pair_success, {x: pair_unit_meta[x] for x in unit_ids},
                                          order, strategies, complete)
        )

    conflicts = []
    not_comparable = []
    for image_id, identity_sets in image_payload_sets.items():
        if len(identity_sets) <= 1:
            continue
        all_identities = set().union(*(set(identity_set) for identity_set in identity_sets))
        scopes = {(identity[0], identity[1]) for identity in all_identities}
        if len(scopes) > 1:
            not_comparable.append(image_id)
        else:
            conflicts.append(image_id)
    conflicts.sort()
    not_comparable.sort()
    all_success_files = set().union(*file_success.values()) if file_success else set()
    all_success_pairs = set().union(*pair_success.values()) if pair_success else set()
    reasons = list(validation.get("errors", []))
    if manifest.get("mode") != "contribution":
        reasons.append("mode is not contribution")
    if retry_conflicts:
        reasons.append(f"conflicting payload identities across retries: {len(retry_conflicts)}")

    return {
        "schema_version": "2.0", "mode": manifest.get("mode", "scan"),
        "validation": validation, "contribution_metrics_valid": complete,
        "incomplete_reasons": reasons,
        "image_count": len(image_meta), "all_success_images": len(all_success_files),
        "eligible_pair_count": len(eligible_pair_ids), "all_success_pairs": len(all_success_pairs),
        "excluded_pair_count": len(pair_meta) - len(eligible_pair_ids),
        "payload_conflict_images": len(conflicts), "payload_conflict_image_ids": conflicts,
        "payload_not_comparable_images": len(not_comparable),
        "payload_not_comparable_image_ids": not_comparable,
        "retry_payload_conflict_count": len(retry_conflicts),
        "strategy_metrics": strategy_rows, "pair_strategy_metrics": pair_rows,
        "strategy_metrics_by_scope": file_scope_metrics + pair_scope_metrics,
        "file_group_removal_loss": file_removal, "pair_group_removal_loss": pair_removal,
        "group_removal_loss": file_removal + pair_removal,
    }


def write_csv(path, rows):
    if not rows:
        return
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="分别计算文件级与配对级二维码策略贡献。")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--attempts", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--inventory-after", required=True)
    parser.add_argument("--registry", default=str(Path(__file__).resolve().parents[1] / "assets" / "strategy-registry.initial.json"))
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        attempts = load_jsonl(args.attempts)
        inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
        inventory_after = json.loads(Path(args.inventory_after).read_text(encoding="utf-8"))
        registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
        result = analyze(manifest, attempts, registry, inventory, inventory_after)
        if not result["contribution_metrics_valid"]:
            print(json.dumps({
                "status": "BLOCKED_INCOMPLETE_EXPERIMENT",
                "errors": result["incomplete_reasons"],
            }, ensure_ascii=False))
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
        targets[0].write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_csv(targets[1], result["strategy_metrics"])
        write_csv(targets[2], result["pair_strategy_metrics"])
        write_csv(targets[3], result["file_group_removal_loss"])
        write_csv(targets[4], result["pair_group_removal_loss"])
        write_csv(targets[5], result["strategy_metrics_by_scope"])
        print(json.dumps({
            "status": "PASS", "images": result["image_count"],
            "success_images": result["all_success_images"],
            "eligible_pairs": result["eligible_pair_count"],
            "success_pairs": result["all_success_pairs"],
            "out_dir": str(out.resolve()),
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
