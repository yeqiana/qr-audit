"""Deterministic image inventory with recursive mixed-layout discovery and group-scoped pair IDs."""
import argparse
import hashlib
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
DEFAULT_EXCLUDES = {"report", "qr-tools", ".git", ".idea", "__pycache__", ".venv", "venv"}


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_direct_images(folder, excludes):
    try:
        return any(
            p.is_file() and not p.is_symlink() and p.suffix.lower() in IMAGE_EXTENSIONS
            for p in folder.iterdir()
        )
    except OSError:
        return False


def norm_pair_key(relative_path, mode):
    value = relative_path.replace("\\", "/")
    if mode == "basename":
        value = value.rsplit("/", 1)[-1]
    return unicodedata.normalize("NFC", value).casefold()


def discover_groups(root, left_name, right_name, excludes):
    """Discover every pair group and standalone image folder, including mixed trees."""
    discovered = []

    def side_paths(folder):
        return {
            left_name: folder / left_name if (folder / left_name).is_dir() and not (folder / left_name).is_symlink() else None,
            right_name: folder / right_name if (folder / right_name).is_dir() and not (folder / right_name).is_symlink() else None,
        }

    def walk(folder, is_root=False):
        if folder.is_symlink():
            return
        sides = side_paths(folder)
        has_pair_dirs = sides[left_name] is not None or sides[right_name] is not None
        direct_images = has_direct_images(folder, excludes)
        rel = "." if folder == root else folder.relative_to(root).as_posix()

        if has_pair_dirs:
            discovered.append((folder.name or "root", folder, sides, rel))
            if direct_images:
                discovered.append((f"{folder.name or 'root'} [direct images]", folder, {"SINGLE": folder}, rel + "#direct-images"))
        elif direct_images:
            discovered.append((folder.name or "root", folder, {"SINGLE": folder}, rel))

        excluded_side_paths = {p.resolve() for p in sides.values() if p is not None}
        try:
            children = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.is_symlink() or child.name.casefold() in excludes:
                continue
            if child.resolve() in excluded_side_paths:
                continue
            walk(child)

    walk(root, True)
    if not discovered:
        discovered.append((root.name or "root", root, {"SINGLE": root}, "."))
    return discovered


def collect_side(group_id, side_id, folder, excludes, recursive=True):
    if folder is None:
        return {"side_id": side_id, "directory_present": False, "directory": None, "image_count": 0, "files": []}
    files = []
    candidates = folder.rglob("*") if recursive else folder.iterdir()
    for path in sorted(candidates, key=lambda p: str(p).casefold()):
        try:
            rel_parts = path.relative_to(folder).parts
        except ValueError:
            continue
        if any(part.casefold() in excludes for part in rel_parts[:-1]):
            continue
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            rel = path.relative_to(folder).as_posix()
            digest = sha256_file(path)
            stat = path.stat()
            file_id = hashlib.sha256(
                f"{group_id}\0{side_id}\0{rel}\0{digest}".encode("utf-8")
            ).hexdigest()[:24]
            files.append({
                "file_id": file_id, "relative_path": rel, "name": path.name,
                "absolute_path": str(path.resolve()), "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "sha256": digest,
            })
        except OSError as exc:
            files.append({
                "file_id": hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:24],
                "relative_path": str(path), "name": path.name,
                "sha256": None, "read_error": str(exc),
            })
    return {
        "side_id": side_id, "directory_present": True, "directory": str(folder.resolve()),
        "image_count": len(files), "files": files,
    }


def build_inventory(input_root, left_name="WAVES_QR", right_name="WAVES_QR_RAW",
                    pair_key_mode="relative_path", exclude_names=None):
    root = Path(input_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"input_root 不存在或不是目录: {root}")
    excludes = {x.casefold() for x in (exclude_names or DEFAULT_EXCLUDES)}
    groups = []
    for group_name, group_path, side_paths, group_rel in discover_groups(root, left_name, right_name, excludes):
        group_id = hashlib.sha256(f"{root}|{group_rel}".encode("utf-8")).hexdigest()[:16]
        sides = [
            collect_side(group_id, side_id, folder, excludes, recursive=(side_id != "SINGLE"))
            for side_id, folder in side_paths.items()
        ]
        pairs = []
        if len(sides) == 1 and sides[0]["side_id"] == "SINGLE":
            for item in sides[0]["files"]:
                pair_key = norm_pair_key(item["relative_path"], pair_key_mode)
                pair_id = hashlib.sha256(f"{group_id}\0{pair_key}".encode("utf-8")).hexdigest()[:24]
                pairs.append({
                    "pair_id": pair_id, "group_id": group_id, "pair_key": pair_key,
                    "pair_status": "SINGLE", "left_file_ids": [item["file_id"]], "right_file_ids": [],
                })
        else:
            left = next((s for s in sides if s["side_id"] == left_name), {"files": [], "directory_present": False})
            right = next((s for s in sides if s["side_id"] == right_name), {"files": [], "directory_present": False})
            left_map, right_map = {}, {}
            for item in left["files"]:
                left_map.setdefault(norm_pair_key(item["relative_path"], pair_key_mode), []).append(item)
            for item in right["files"]:
                right_map.setdefault(norm_pair_key(item["relative_path"], pair_key_mode), []).append(item)
            for key in sorted(set(left_map) | set(right_map)):
                left_items, right_items = left_map.get(key, []), right_map.get(key, [])
                status = "AMBIGUOUS_PAIR" if len(left_items) > 1 or len(right_items) > 1 else (
                    "PAIRED" if left_items and right_items else "LEFT_ONLY" if left_items else "RIGHT_ONLY"
                )
                pair_id = hashlib.sha256(f"{group_id}\0{key}".encode("utf-8")).hexdigest()[:24]
                pairs.append({
                    "pair_id": pair_id, "group_id": group_id, "pair_key": key, "pair_status": status,
                    "left_file_ids": [x["file_id"] for x in left_items],
                    "right_file_ids": [x["file_id"] for x in right_items],
                })

        stats = {
            "image_file_count": sum(s["image_count"] for s in sides),
            "pair_count": sum(p["pair_status"] == "PAIRED" for p in pairs),
            "left_only_count": sum(p["pair_status"] == "LEFT_ONLY" for p in pairs),
            "right_only_count": sum(p["pair_status"] == "RIGHT_ONLY" for p in pairs),
            "ambiguous_pair_count": sum(p["pair_status"] == "AMBIGUOUS_PAIR" for p in pairs),
            "single_count": sum(p["pair_status"] == "SINGLE" for p in pairs),
            "missing_side_count": sum(not s["directory_present"] for s in sides),
        }
        groups.append({
            "group_id": group_id, "group_name": group_name, "group_relative_path": group_rel,
            "pair_key_mode": pair_key_mode, "sides": sides, "pairs": pairs, "stats": stats,
        })

    return {
        "schema_version": "2.0", "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(root), "left_directory": left_name, "right_directory": right_name,
        "pair_key_mode": pair_key_mode, "groups": groups,
        "image_file_count": sum(g["stats"]["image_file_count"] for g in groups),
        "group_count": len(groups),
    }


def write_json(path, data, overwrite=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"拒绝覆盖已有文件: {path}")
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main():
    parser = argparse.ArgumentParser(description="递归清点二维码图片、计算 SHA-256 并发现组内配对。")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--left-name", default="WAVES_QR")
    parser.add_argument("--right-name", default="WAVES_QR_RAW")
    parser.add_argument("--pair-key-mode", choices=["relative_path", "basename"], default="relative_path")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        data = build_inventory(
            args.input_root, args.left_name, args.right_name, args.pair_key_mode,
            set(DEFAULT_EXCLUDES) | set(args.exclude),
        )
        write_json(args.output, data, args.overwrite)
        print(json.dumps({
            "status": "PASS", "output": str(Path(args.output).resolve()),
            "groups": data["group_count"], "image_files": data["image_file_count"],
            "pairs": sum(g["stats"]["pair_count"] for g in data["groups"]),
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
