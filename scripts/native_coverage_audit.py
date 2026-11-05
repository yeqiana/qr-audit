"""Fail-closed report of historical native QR strategy execution evidence.

Definitions and a successful reference R strategy do not certify Vxx migration.
No native source code is copied or recreated by this checker.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_REQUIRED = ("V04", "V10", "V11", "V12")
EXECUTED = {"DECODED", "NO_DECODE", "DETECTED_ONLY", "ERROR"}


def audit(manifest, attempts, required=DEFAULT_REQUIRED):
    registered = {
        item.get("strategy_id"): item for item in manifest.get("strategies", [])
        if isinstance(item, dict)
    }
    declared = set(manifest.get("strategy_order", []))
    counters = defaultdict(lambda: {
        "executed": 0, "native_attested": 0, "not_run": 0,
        "skipped_early": 0, "decoded": 0, "errors": 0,
        "native_ids": set(), "native_decoder_ids": set(),
    })
    for record in attempts:
        strategy = record.get("strategy_id")
        if strategy not in declared:
            raise ValueError("attempt references a strategy outside frozen registry")
        status = record.get("status")
        c = counters[strategy]
        if status in EXECUTED:
            c["executed"] += 1
            if status == "DECODED":
                c["decoded"] += 1
            if status == "ERROR":
                c["errors"] += 1
            if (record.get("native_strategy_id")
                    and record.get("native_decoder_id")
                    and record.get("bridge_config_sha256")):
                c["native_attested"] += 1
                c["native_ids"].add(record["native_strategy_id"])
                c["native_decoder_ids"].add(record["native_decoder_id"])
        elif status == "NOT_RUN":
            c["not_run"] += 1
        elif status == "SKIPPED_EARLY_STOP":
            c["skipped_early"] += 1
    checks = []
    for sid in required:
        row = registered.get(sid)
        c = counters[sid]
        if sid not in declared or not row or row.get("executor_status") != "REGISTERED":
            status = "NOT_CONNECTED"
        elif not c["executed"]:
            status = "NOT_OBSERVED"
        elif c["native_attested"] != c["executed"] or len(c["native_ids"]) != 1:
            status = "NATIVE_PROVENANCE_INCOMPLETE"
        else:
            status = "NATIVE_ATTEMPT_OBSERVED"
        checks.append({
            "strategy_id": sid, "status": status,
            "executed": c["executed"], "native_attested": c["native_attested"],
            "decoded_attempts": c["decoded"], "errors": c["errors"],
            "not_run": c["not_run"], "skipped_early": c["skipped_early"],
            "native_strategy_ids": sorted(c["native_ids"]),
            "native_decoder_ids": sorted(c["native_decoder_ids"]),
        })
    observed = all(x["status"] == "NATIVE_ATTEMPT_OBSERVED" for x in checks)
    return {
        "status": "PASS_NATIVE_EXECUTION_EVIDENCE" if observed else "BLOCKED_NATIVE_WIRING",
        "run_id": manifest.get("run_id"), "required": checks,
        "warning": ("A native bridge response corroborates invocation identity, "
                    "not algorithm equivalence. Verify source implementation, "
                    "actual options and old-success coverage separately."),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Audit native QR strategies without scanning")
    p.add_argument("--manifest", required=True)
    p.add_argument("--attempts", required=True)
    p.add_argument("--require-strategy", action="append")
    p.add_argument("--out")
    args = p.parse_args(argv)
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        attempts = [json.loads(line) for line in Path(args.attempts).read_text(
            encoding="utf-8"
        ).splitlines() if line.strip()]
        required = args.require_strategy or DEFAULT_REQUIRED
        result = audit(manifest, attempts, required)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            with Path(args.out).open("x", encoding="utf-8") as stream:
                stream.write(output + "\n")
        print(output)
        return 0 if result["status"] == "PASS_NATIVE_EXECUTION_EVIDENCE" else 3
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "BLOCKED_UNVERIFIABLE", "error": str(exc)}, ensure_ascii=False))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
