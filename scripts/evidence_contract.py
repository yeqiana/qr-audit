"""Shared evidence contract for QR Audit schema v2.

Structural validation and provenance verification are reported separately.
Payload hashes are comparable only when algorithm and byte/text scope match.
"""
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

VALID_STATUSES = {
    "DECODED", "DETECTED_ONLY", "NO_DECODE", "ERROR",
    "SKIPPED_EARLY_STOP", "SKIPPED_INELIGIBLE", "NOT_RUN",
}
EXECUTED_STATUSES = {"DECODED", "DETECTED_ONLY", "NO_DECODE", "ERROR"}
SKIP_STATUSES = {"SKIPPED_EARLY_STOP", "SKIPPED_INELIGIBLE", "NOT_RUN"}


def canonical_sha256(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_identity(text):
    return {
        "algorithm": "sha256",
        "scope": "decoded_text_utf8",
        "value": hashlib.sha256(str(text).encode("utf-8")).hexdigest(),
    }


def _validate_identity(identity):
    if not isinstance(identity, dict):
        raise ValueError("payload identity must be an object")
    algorithm = str(identity.get("algorithm", "")).lower()
    scope = str(identity.get("scope", ""))
    value = str(identity.get("value", "")).lower()
    if not algorithm or not scope or not value:
        raise ValueError("payload identity requires algorithm, scope and value")
    if algorithm == "sha256" and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("sha256 payload identity must be 64 lowercase hex characters")
    return (algorithm, scope, value)


def payload_identities(record):
    """Return sorted comparable identity tuples; never infer scope for hash-only legacy data."""
    values = []
    items = record.get("payloads")
    if items is None:
        if isinstance(record.get("all_payloads"), list):
            items = record["all_payloads"]
        elif record.get("payload") not in (None, ""):
            items = [record["payload"]]
        else:
            items = []

    for item in items:
        if isinstance(item, str):
            values.append(text_identity(item))
            continue
        if not isinstance(item, dict):
            raise ValueError("each payload must be text or an object")
        text_value = item.get("text", item.get("payload"))
        identity = item.get("identity")
        if identity is None and item.get("payload_sha256"):
            identity = {
                "algorithm": item.get("payload_hash_algorithm", ""),
                "scope": item.get("payload_hash_scope", ""),
                "value": item["payload_sha256"],
            }
        if text_value not in (None, ""):
            if identity is None:
                values.append(text_identity(text_value))
            else:
                normalized = _validate_identity(identity)
                if normalized[1] == "decoded_text_utf8":
                    computed = text_identity(text_value)
                    if normalized != (computed["algorithm"], computed["scope"], computed["value"]):
                        raise ValueError("payload text and identity hash disagree")
                values.append({"algorithm": normalized[0], "scope": normalized[1], "value": normalized[2]})
        elif identity is not None:
            normalized = _validate_identity(identity)
            values.append({"algorithm": normalized[0], "scope": normalized[1], "value": normalized[2]})
        else:
            raise ValueError("payload item has neither text nor identity")

    primary_text = record.get("payload")
    if primary_text in (None, "") and items:
        first = items[0]
        primary_text = first if isinstance(first, str) else (
            first.get("text", first.get("payload")) if isinstance(first, dict) else None
        )
    primary_hash = record.get("payload_sha256")
    if primary_hash:
        scope = record.get("payload_hash_scope") or "decoded_text_utf8"
        algorithm = record.get("payload_hash_algorithm") or "sha256"
        if primary_text not in (None, "") and scope == "decoded_text_utf8":
            if algorithm != "sha256":
                raise ValueError("payload_sha256 requires sha256 algorithm")
            expected = text_identity(primary_text)["value"]
            if str(primary_hash).lower() != expected:
                raise ValueError("payload_sha256 does not match payload UTF-8 bytes")
        elif any(identity[2] == str(primary_hash).lower() for identity in values):
            pass
        else:
            if not record.get("payload_hash_algorithm") or not record.get("payload_hash_scope"):
                raise ValueError("hash-only payload requires explicit payload_hash_algorithm and payload_hash_scope")
            identity = _validate_identity({"algorithm": algorithm, "scope": scope, "value": primary_hash})
            if not values:
                values.append({"algorithm": identity[0], "scope": identity[1], "value": identity[2]})

    unique = {
        (x["algorithm"], x["scope"], x["value"])
        for x in values
    }
    return sorted(unique)


def payload_identity_label(identity):
    algorithm, scope, value = identity
    return f"{algorithm}:{scope}:{value}"


def compare_identity_sets(left, right):
    """Return SAME/DIFFERENT only when every identity uses a common algorithm and scope."""
    left = set(left or [])
    right = set(right or [])
    if not left or not right:
        return "NOT_COMPARABLE"
    scopes = {(x[0], x[1]) for x in left | right}
    if len(scopes) != 1:
        return "NOT_COMPARABLE"
    return "SAME" if left == right else "DIFFERENT"


def _image_identity_map(inventory):
    result = {}
    for group in inventory.get("groups", []):
        group_id = group.get("group_id")
        pair_by_file = {}
        for pair in group.get("pairs", []):
            for file_id in pair.get("left_file_ids", []) + pair.get("right_file_ids", []):
                pair_by_file[file_id] = pair
        for side in group.get("sides", []):
            for item in side.get("files", []):
                key = (group_id, side.get("side_id"), item.get("relative_path"))
                result[key] = {
                    "image_id": item.get("file_id"),
                    "sha256": item.get("sha256"),
                    "pair_id": pair_by_file.get(item.get("file_id"), {}).get("pair_id"),
                    "pair_status": pair_by_file.get(item.get("file_id"), {}).get("pair_status"),
                }
    return result


def _inventory_snapshot(inventory):
    result = {}
    for group in inventory.get("groups", []):
        for side in group.get("sides", []):
            for item in side.get("files", []):
                key = (group.get("group_id"), side.get("side_id"), item.get("relative_path"))
                result[key] = item.get("sha256")
    return result


def _compare_inventory_snapshots(before, after):
    left, right = _inventory_snapshot(before), _inventory_snapshot(after)
    changed = [
        {"identity": list(key), "before_sha256": left[key], "after_sha256": right[key]}
        for key in sorted(set(left) & set(right)) if left[key] != right[key]
    ]
    added = [{"identity": list(key), "sha256": right[key]} for key in sorted(set(right) - set(left))]
    deleted = [{"identity": list(key), "sha256": left[key]} for key in sorted(set(left) - set(right))]
    return {
        "status": "STABLE" if not changed and not added and not deleted else "CHANGED",
        "before_file_count": len(left), "after_file_count": len(right),
        "changed": changed, "added": added, "deleted": deleted,
    }


def _source_verification(source_fingerprint):
    files = source_fingerprint.get("files", []) if isinstance(source_fingerprint, dict) else []
    if not files:
        return {"status": "NOT_VERIFIED", "checked": 0, "errors": []}
    errors = []
    for item in files:
        path = item.get("path")
        expected = item.get("sha256")
        if not path or not expected:
            errors.append("source fingerprint file entry missing path/sha256")
            continue
        try:
            actual = file_sha256(path)
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        if actual != expected:
            errors.append(f"{path}: SHA-256 mismatch")
    return {
        "status": "VERIFIED" if not errors and len(files) > 0 else "NOT_VERIFIED",
        "checked": len(files),
        "errors": errors,
    }


def validate(manifest, attempts, registry=None, inventory=None, inventory_after=None):
    errors = []
    warnings = []
    schema = str(manifest.get("schema_version", "1.0"))
    if schema != "2.0":
        warnings.append(f"legacy evidence schema {schema}; strict contribution verification requires 2.0")

    run_id = manifest.get("run_id")
    if not run_id:
        errors.append("manifest.run_id missing")

    images_list = manifest.get("images", [])
    image_map = {}
    for index, item in enumerate(images_list, 1):
        image_id = item.get("image_id")
        if not image_id:
            errors.append(f"manifest.images[{index}] missing image_id")
            continue
        if image_id in image_map:
            errors.append(f"manifest duplicate image_id: {image_id}")
        image_map[image_id] = item

    strategy_order = manifest.get("strategy_order", [])
    decoder_items = manifest.get("decoders", [])
    decoder_ids = [
        x if isinstance(x, str) else x.get("decoder_id")
        for x in decoder_items
    ]
    if not strategy_order or len(set(strategy_order)) != len(strategy_order):
        errors.append("manifest.strategy_order must be non-empty and unique")
    if not decoder_ids or None in decoder_ids or len(set(decoder_ids)) != len(decoder_ids):
        errors.append("manifest.decoders must contain unique decoder_id values")

    inventory_verification = {"status": "NOT_VERIFIED", "errors": []}
    if inventory is not None:
        actual_hash = canonical_sha256(inventory)
        expected_hash = manifest.get("inventory_sha256")
        if not expected_hash or actual_hash != expected_hash:
            inventory_verification = {"status": "NOT_VERIFIED", "errors": ["inventory_sha256 mismatch"]}
            errors.append("inventory_sha256 mismatch")
        else:
            expected_map = _image_identity_map(inventory)
            manifest_map = {}
            for item in images_list:
                key = (item.get("group_id"), item.get("side_id"), item.get("relative_path"))
                manifest_map[key] = item
            if set(expected_map) != set(manifest_map):
                errors.append("manifest image identity set differs from inventory")
                inventory_verification = {"status": "NOT_VERIFIED", "errors": ["image identity set mismatch"]}
            else:
                for key, expected in expected_map.items():
                    actual = manifest_map[key]
                    if actual.get("image_id") != expected["image_id"] or actual.get("sha256") != expected["sha256"]:
                        errors.append(f"manifest image identity/hash mismatch: {key}")
                    if actual.get("pair_id") != expected["pair_id"]:
                        errors.append(f"manifest pair_id mismatch: {key}")
                if not any("inventory" in e or "manifest image" in e or "manifest pair_id" in e for e in errors):
                    inventory_verification = {"status": "VERIFIED", "errors": []}
    else:
        warnings.append("inventory not supplied; input provenance is NOT_VERIFIED")

    registry_verification = {"status": "NOT_VERIFIED", "errors": []}
    if registry is not None:
        registry_ids = [x.get("strategy_id") for x in registry.get("strategies", [])]
        actual_hash = canonical_sha256(registry)
        if actual_hash != manifest.get("strategy_registry_sha256"):
            registry_verification = {"status": "NOT_VERIFIED", "errors": ["strategy_registry_sha256 mismatch"]}
            errors.append("strategy_registry_sha256 mismatch")
        elif registry_ids != strategy_order:
            registry_verification = {"status": "NOT_VERIFIED", "errors": ["strategy_order differs from frozen registry"]}
            errors.append("strategy_order differs from frozen registry")
        else:
            registry_verification = {"status": "VERIFIED", "errors": []}
    else:
        warnings.append("strategy registry not supplied; declared strategy scope is NOT_VERIFIED")

    source_verification = _source_verification(manifest.get("source_fingerprint", {}))
    if source_verification["status"] != "VERIFIED":
        warnings.append("source files are not independently fingerprint-verified")

    input_file_verification = {"status": "NOT_REQUIRED", "checked": 0, "errors": []}
    if manifest.get("mode") == "contribution":
        file_errors = []
        checked = 0
        for image in images_list:
            path = image.get("path")
            expected_hash = image.get("sha256")
            if not path or not expected_hash:
                file_errors.append(f"{image.get('image_id')}: missing local path or SHA-256")
                continue
            try:
                actual_hash = file_sha256(path)
                checked += 1
            except OSError as exc:
                file_errors.append(f"{image.get('image_id')}: cannot read input file: {exc}")
                continue
            if actual_hash != expected_hash:
                file_errors.append(f"{image.get('image_id')}: input file SHA-256 changed after scan")
        input_file_verification = {
            "status": "VERIFIED" if not file_errors and checked == len(images_list) else "NOT_VERIFIED",
            "checked": checked, "errors": file_errors,
        }
        if file_errors:
            errors.extend(input_file_verification["errors"])

    input_snapshot_verification = {"status": "NOT_REQUIRED", "errors": []}
    input_consistency = manifest.get("input_consistency", {})
    if manifest.get("mode") == "contribution":
        if inventory_after is None:
            input_snapshot_verification = {"status": "NOT_VERIFIED", "errors": ["inventory-after.json not supplied"]}
            errors.append("contribution validation requires inventory-after.json")
        else:
            after_hash = canonical_sha256({
                key: value for key, value in inventory_after.items() if key != "generated_at"
            })
            if after_hash != manifest.get("input_inventory_after_sha256"):
                errors.append("input_inventory_after_sha256 mismatch")
            computed_consistency = _compare_inventory_snapshots(inventory, inventory_after) if inventory is not None else None
            if computed_consistency != input_consistency:
                errors.append("manifest input_consistency does not match before/after inventories")
            if not computed_consistency or computed_consistency.get("status") != "STABLE":
                errors.append("contribution experiment input files changed during scan")
            if after_hash == manifest.get("input_inventory_after_sha256") and computed_consistency == input_consistency and computed_consistency.get("status") == "STABLE":
                input_snapshot_verification = {"status": "VERIFIED", "errors": []}
            else:
                input_snapshot_verification = {"status": "NOT_VERIFIED", "errors": ["input snapshot mismatch or drift"]}

    cells = defaultdict(list)
    attempt_ids = set()
    attempt_indexes = defaultdict(set)
    for row_number, attempt in enumerate(attempts, 1):
        prefix = f"attempts.jsonl:{row_number}"
        required = (
            "attempt_id", "run_id", "image_id", "group_id", "side_id",
            "relative_path", "input_sha256", "pair_id", "strategy_id", "decoder_id",
            "status", "attempt_index", "duration_ms",
        )
        for field in required:
            if field not in attempt or attempt.get(field) is None:
                errors.append(f"{prefix} missing {field}")

        if attempt.get("run_id") != run_id:
            errors.append(f"{prefix} run_id does not match manifest.run_id")
        image = image_map.get(attempt.get("image_id"))
        if image is None:
            errors.append(f"{prefix} image_id is not declared by manifest")
        else:
            for field in ("group_id", "side_id", "relative_path"):
                if attempt.get(field) != image.get(field):
                    errors.append(f"{prefix} {field} does not match manifest image")
            if attempt.get("input_sha256") != image.get("sha256"):
                errors.append(f"{prefix} input_sha256 does not match manifest image hash")
            if attempt.get("pair_id") != image.get("pair_id"):
                errors.append(f"{prefix} pair_id does not match manifest image")

        if attempt.get("strategy_id") not in strategy_order:
            errors.append(f"{prefix} strategy_id is not declared")
        if attempt.get("decoder_id") not in decoder_ids:
            errors.append(f"{prefix} decoder_id is not declared")
        status = attempt.get("status")
        if status not in VALID_STATUSES:
            errors.append(f"{prefix} invalid status: {status}")
        if status in SKIP_STATUSES and not attempt.get("skip_reason"):
            errors.append(f"{prefix} skipped status requires skip_reason")
        if status == "ERROR" and not attempt.get("error"):
            errors.append(f"{prefix} ERROR status requires error")
        try:
            duration = float(attempt.get("duration_ms"))
            if not math.isfinite(duration) or duration < 0:
                raise ValueError()
        except (TypeError, ValueError):
            errors.append(f"{prefix} duration_ms must be finite and non-negative")

        attempt_id = attempt.get("attempt_id")
        if attempt_id:
            if attempt_id in attempt_ids:
                errors.append(f"{prefix} duplicate attempt_id: {attempt_id}")
            attempt_ids.add(attempt_id)
        try:
            raw_attempt_index = attempt.get("attempt_index")
            if isinstance(raw_attempt_index, bool) or not isinstance(raw_attempt_index, int):
                raise ValueError()
            attempt_index = raw_attempt_index
            if attempt_index < 1:
                raise ValueError()
            cell = (attempt.get("image_id"), attempt.get("strategy_id"), attempt.get("decoder_id"))
            if attempt_index in attempt_indexes[cell]:
                errors.append(f"{prefix} duplicate attempt_index for logical combination")
            attempt_indexes[cell].add(attempt_index)
            cells[cell].append(attempt)
        except (TypeError, ValueError):
            errors.append(f"{prefix} attempt_index must be a positive integer")

        if status == "DECODED":
            try:
                identities = payload_identities(attempt)
                if not identities:
                    errors.append(f"{prefix} DECODED requires at least one payload identity")
            except ValueError as exc:
                errors.append(f"{prefix} payload identity invalid: {exc}")

    for cell, indexes in attempt_indexes.items():
        if indexes and indexes != set(range(1, max(indexes) + 1)):
            errors.append(f"logical combination {cell} has non-contiguous retry indexes")

    expected = {
        (image_id, strategy_id, decoder_id)
        for image_id in image_map
        for strategy_id in strategy_order
        for decoder_id in decoder_ids
    }
    seen = set(cells)
    missing = expected - seen
    if manifest.get("mode") == "contribution":
        if not expected:
            errors.append("contribution expected matrix is empty")
        if missing:
            errors.append(f"contribution matrix missing {len(missing)} logical combinations")
        for cell, rows in cells.items():
            statuses = [x.get("status") for x in rows]
            if "SKIPPED_EARLY_STOP" in statuses:
                errors.append(f"contribution matrix contains early stop: {cell}")
            if "NOT_RUN" in statuses:
                errors.append(f"contribution matrix contains NOT_RUN: {cell}")
            decoded = [x for x in rows if x.get("status") == "DECODED"]
            if "ERROR" in statuses and not decoded:
                errors.append(f"contribution logical combination failed without successful retry: {cell}")
            if "SKIPPED_INELIGIBLE" in statuses:
                reasons = [str(x.get("skip_reason", "")) for x in rows if x.get("status") == "SKIPPED_INELIGIBLE"]
                if any(reason.startswith(("NOT_IMPLEMENTED", "DECODER_UNAVAILABLE", "DEPENDENCY_MISSING")) for reason in reasons):
                    errors.append(f"unavailable implementation/dependency cannot be counted as ineligible: {cell}")
                if decoded or any(s in EXECUTED_STATUSES for s in statuses):
                    errors.append(f"contradictory ineligible and executed attempts: {cell}")
            decoded_sets = []
            for row in decoded:
                try:
                    decoded_sets.append(tuple(payload_identities(row)))
                except ValueError:
                    pass
            if len(set(decoded_sets)) > 1:
                errors.append(f"retry payload identities conflict for logical combination: {cell}")

    if manifest.get("mode") == "contribution":
        if schema != "2.0":
            errors.append("legacy schema cannot certify complete contribution metrics")
        if inventory_verification["status"] != "VERIFIED":
            errors.append("input inventory provenance is not verified")
        if registry_verification["status"] != "VERIFIED":
            errors.append("strategy registry provenance is not verified")
        if source_verification["status"] != "VERIFIED":
            errors.append("source fingerprint is not verified")
        if input_file_verification["status"] != "VERIFIED":
            errors.append("current input files do not match frozen image hashes")

    structural_status = "PASS" if not errors else "FAIL"
    provenance_status = (
        "VERIFIED"
        if inventory_verification["status"] == "VERIFIED"
        and registry_verification["status"] == "VERIFIED"
        and source_verification["status"] == "VERIFIED"
        and (manifest.get("mode") != "contribution" or input_file_verification["status"] == "VERIFIED")
        and (manifest.get("mode") != "contribution" or input_snapshot_verification["status"] == "VERIFIED")
        else "NOT_VERIFIED"
    )
    contribution_valid = (
        manifest.get("mode") == "contribution"
        and structural_status == "PASS"
        and provenance_status == "VERIFIED"
        and not missing
    )
    return {
        "status": structural_status,
        "structural_status": structural_status,
        "provenance_status": provenance_status,
        "contribution_metrics_valid": contribution_valid,
        "errors": errors,
        "warnings": warnings,
        "attempt_count": len(attempts),
        "logical_combination_count": len(seen),
        "missing_expected_combinations": len(missing),
        "inventory_verification": inventory_verification,
        "registry_verification": registry_verification,
        "source_verification": source_verification,
        "input_file_verification": input_file_verification,
        "input_snapshot_verification": input_snapshot_verification,
    }
