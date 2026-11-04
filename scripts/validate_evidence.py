"""CLI wrapper for the shared evidence contract."""
import argparse
import json
import sys
from pathlib import Path

from evidence_contract import validate


def load_jsonl(path):
    rows = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return rows


def main():
    parser = argparse.ArgumentParser(description="校验二维码扫描证据、来源归属和贡献度完整性。")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--attempts", required=True)
    parser.add_argument("--inventory", help="inventory.json；贡献度实验必需")
    parser.add_argument("--inventory-after", help="inventory-after.json；贡献度实验必需")
    parser.add_argument("--registry", help="strategy registry JSON；贡献度实验必需")
    args = parser.parse_args()
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        attempts = load_jsonl(args.attempts)
        inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8")) if args.inventory else None
        inventory_after = json.loads(Path(args.inventory_after).read_text(encoding="utf-8")) if args.inventory_after else None
        registry = json.loads(Path(args.registry).read_text(encoding="utf-8")) if args.registry else None
        result = validate(
            manifest, attempts, registry=registry, inventory=inventory,
            inventory_after=inventory_after,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" and (
            manifest.get("mode") != "contribution" or result["contribution_metrics_valid"]
        ) else 1
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
