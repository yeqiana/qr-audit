"""Read-only QR coverage regression gate for two independently recorded runs.

Compares file identity by group-relative path, side and relative image path;
never trusts root-dependent image_id or a grand-total success counter.
"""
import argparse
import hashlib
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from evidence_contract import payload_identities


def _norm(value):
    return unicodedata.normalize("NFC", str(value).replace("\\", "/")).casefold()


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_attempts(path):
    records = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} line {number}: invalid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"{path.name} line {number}: expected object")
        records.append(record)
    return records


def _identities(row):
    """Strict canonical evidence first; support legacy plain-text payload only."""
    try:
        identities = set(payload_identities(row))
        if identities:
            return identities
    except (ValueError, TypeError, KeyError):
        pass
    # The pre-v2 local scanner stored an explicit "UTF8_TEXT:<sha256>"
    # string identity, rather than the v2 structured identity object.
    payload_items = row.get("payloads")
    if isinstance(payload_items, list) and any(isinstance(x, dict) for x in payload_items):
        parsed = set()
        if not payload_items or not all(isinstance(x, dict) for x in payload_items):
            raise ValueError("legacy mixed/empty payload identities cannot be verified")
        for item in payload_items:
            token = item.get("identity")
            if not isinstance(token, str) or ":" not in token:
                raise ValueError("legacy payload identity missing explicit scope")
            scope, digest = token.split(":", 1)
            if scope not in ("UTF8_TEXT", "decoded_text_utf8"):
                raise ValueError("unsupported legacy payload hash scope")
            if len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
                raise ValueError("legacy payload SHA-256 has invalid format")
            digest = digest.lower()
            value = item.get("text", item.get("payload"))
            if value not in (None, ""):
                if not isinstance(value, str) or hashlib.sha256(value.encode("utf-8")).hexdigest() != digest:
                    raise ValueError("legacy payload identity contradicts its plaintext")
            parsed.add(("sha256", "decoded_text_utf8", digest))
        return parsed
    value = row.get("payload")
    if not isinstance(value, str) or not value:
        raise ValueError("DECODED lacks verifiable payload identity")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    claimed = row.get("payload_sha256")
    if claimed is not None and str(claimed).lower() != digest:
        raise ValueError("legacy plaintext payload SHA-256 does not match")
    scope = row.get("payload_hash_scope")
    if scope not in (None, "", "decoded_text_utf8", "UTF8_TEXT"):
        raise ValueError("legacy payload scope is not explicitly comparable")
    return {("sha256", "decoded_text_utf8", digest)}


def load_evidence(root):
    evidence = Path(root).expanduser().resolve()
    if not evidence.is_dir():
        raise ValueError(f"evidence directory not found: {evidence}")
    manifest = _read_json(evidence / "run-manifest.json")
    inventory = _read_json(evidence / "inventory.json")
    attempts = _read_attempts(evidence / "attempts.jsonl")
    run_id = manifest.get("run_id")
    if not run_id:
        raise ValueError("manifest missing run_id")
    image_ids, images, pair_keys, pairs = {}, {}, {}, {}
    for group in inventory.get("groups", []):
        group_key = _norm(group.get("group_relative_path", group.get("group_name", "")))
        for side in group.get("sides", []):
            side_name = _norm(side["side_id"])
            for item in side.get("files", []):
                key = (group_key, side_name, _norm(item["relative_path"]))
                if key in images or item["file_id"] in image_ids:
                    raise ValueError("duplicate group-scoped image identity or file_id")
                if not item.get("sha256"):
                    raise ValueError("image lacks original input SHA-256")
                images[key] = {"sha256": item["sha256"], "file_id": item["file_id"]}
                image_ids[item["file_id"]] = key
        for pair in group.get("pairs", []):
            if pair.get("pair_status") != "PAIRED":
                continue
            key = (group_key, _norm(pair["pair_key"]))
            if key in pairs:
                raise ValueError("duplicate group-scoped pair key")
            members = pair.get("left_file_ids", []) + pair.get("right_file_ids", [])
            if len(members) != 2 or any(x not in image_ids for x in members):
                raise ValueError("PAIRED must refer to exactly two declared images")
            pairs[key] = {image_ids[x] for x in members}
            pair_keys[key] = pair["pair_id"]
    decoded = defaultdict(set)
    seen_ids = set()
    seen_images = set()
    for row in attempts:
        rid = row.get("run_id")
        if rid != run_id:
            raise ValueError("attempt run_id does not match manifest")
        attempt_id = row.get("attempt_id")
        if not attempt_id or attempt_id in seen_ids:
            raise ValueError("missing or duplicate attempt_id")
        seen_ids.add(attempt_id)
        key = image_ids.get(row.get("image_id"))
        if key is None:
            raise ValueError("attempt references unknown image_id")
        seen_images.add(key)
        if row.get("input_sha256") != images[key]["sha256"]:
            raise ValueError("attempt input hash does not match image inventory")
        if row.get("status") == "DECODED":
            try:
                decoded[key].update(_identities(row))
            except ValueError as exc:
                raise ValueError(f"unverifiable DECODED attempt: {exc}") from exc
    if seen_images != set(images):
        raise ValueError("some declared images have no attempt records")
    return {
        "run_id": run_id,
        "images": images,
        "pairs": pairs,
        "decoded": dict(decoded),
        "attempts": len(attempts),
        "executed_attempts": sum(1 for r in attempts if r.get("status") in
                                 ("DECODED", "DETECTED_ONLY", "NO_DECODE", "ERROR")),
        "not_run_attempts": sum(1 for r in attempts if r.get("status") == "NOT_RUN"),
        "registered_strategies": list(manifest.get("strategy_order", [])),
        "connected_strategies": [
            x.get("strategy_id") for x in manifest.get("strategies", [])
            if isinstance(x, dict) and x.get("executor_status") == "REGISTERED"
        ],
    }


def compare(baseline, candidate):
    first, second = baseline["images"], candidate["images"]
    if set(first) != set(second) or any(first[k]["sha256"] != second[k]["sha256"] for k in first):
        return {
            "status": "BLOCKED_INPUT_CHANGED",
            "baseline_run_id": baseline["run_id"], "candidate_run_id": candidate["run_id"],
            "baseline_images": len(first), "candidate_images": len(second),
            "image_ids_only_baseline": len(set(first) - set(second)),
            "image_ids_only_candidate": len(set(second) - set(first)),
            "hash_mismatches": sum(first[k]["sha256"] != second[k]["sha256"] for k in set(first) & set(second)),
        }
    if baseline["pairs"] != candidate["pairs"]:
        return {"status": "BLOCKED_PAIR_STRUCTURE_CHANGED",
                "baseline_run_id": baseline["run_id"], "candidate_run_id": candidate["run_id"],
                "reason": "eligible pair identities or members differ"}
    before = baseline["decoded"]
    after = candidate["decoded"]
    before_ok = {k for k in first if before.get(k)}
    after_ok = {k for k in second if after.get(k)}
    lost = before_ok - after_ok
    gained = after_ok - before_ok
    payload_missing = {
        k for k in before_ok & after_ok if not before[k].issubset(after[k])
    }

    def paired_success(snapshot):
        return {pair for pair, members in baseline["pairs"].items()
                if any(snapshot.get(member) for member in members)}
    before_pairs = paired_success(before)
    after_pairs = paired_success(after)
    lost_pairs = before_pairs - after_pairs
    gained_pairs = after_pairs - before_pairs
    status = ("BLOCKED_RECOGNITION_REGRESSION"
              if lost or lost_pairs or payload_missing else "PASS_NON_REGRESSION")
    return {
        "status": status, "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
        "input_images": len(first), "eligible_pairs": len(baseline["pairs"]),
        "baseline_success_images": len(before_ok),
        "candidate_success_images": len(after_ok),
        "baseline_success_pairs": len(before_pairs),
        "candidate_success_pairs": len(after_pairs),
        "lost_success_images": len(lost),
        "gained_success_images": len(gained),
        "lost_success_pairs": len(lost_pairs),
        "gained_success_pairs": len(gained_pairs),
        "payload_changed_images": len(payload_missing),
        "lost_images_sample": ["/".join(k) for k in sorted(lost)[:30]],
        "changed_payload_images_sample": ["/".join(k) for k in sorted(payload_missing)[:30]],
        "baseline_executed_attempts": baseline["executed_attempts"],
        "candidate_executed_attempts": candidate["executed_attempts"],
        "baseline_not_run_attempts": baseline["not_run_attempts"],
        "candidate_not_run_attempts": candidate["not_run_attempts"],
        "baseline_connected_strategies": baseline["connected_strategies"],
        "candidate_connected_strategies": candidate["connected_strategies"],
        "baseline_strategy_ids": baseline["registered_strategies"],
        "candidate_strategy_ids": candidate["registered_strategies"],
        "note": ("This checks observed offline payload preservation; without independently "
                 "labelled truth it cannot certify QR content correctness or business validity."),
    }


def compare_directories(baseline_dir, candidate_dir):
    return compare(load_evidence(baseline_dir), load_evidence(candidate_dir))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fail closed when a candidate loses any historical decoded file, pair or payload"
    )
    parser.add_argument("--baseline-evidence", required=True)
    parser.add_argument("--candidate-evidence", required=True)
    parser.add_argument("--out", help="new optional JSON report; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        result = compare_directories(args.baseline_evidence, args.candidate_evidence)
        serialized = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            out = Path(args.out).expanduser().resolve()
            with out.open("x", encoding="utf-8") as stream:
                stream.write(serialized + "\n")
        print(serialized)
        return 0 if result["status"] == "PASS_NON_REGRESSION" else 3
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED_UNVERIFIABLE",
                          "error": str(exc)}, ensure_ascii=False))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
