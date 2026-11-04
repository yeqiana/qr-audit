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
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def has_direct_images(folder):
    try:
        return any(p.is_file() and not p.is_symlink() and p.suffix.lower() in IMAGE_EXTENSIONS for p in folder.iterdir())
    except OSError:
        return False

def has_recursive_images(folder):
    try:
        return any(p.is_file() and not p.is_symlink() and p.suffix.lower() in IMAGE_EXTENSIONS for p in folder.rglob("*"))
    except OSError:
        return False

def discover_groups(root, left_name, right_name, excludes):
    def sides_for(folder):
        return {
            left_name: folder / left_name if (folder / left_name).is_dir() and not (folder / left_name).is_symlink() else None,
            right_name: folder / right_name if (folder / right_name).is_dir() and not (folder / right_name).is_symlink() else None
        }
    if (root / left_name).is_dir() or (root / right_name).is_dir():
        return [(root.name or "root", root, sides_for(root))]
    paired, standalone = [], []
    for child in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if not child.is_dir() or child.is_symlink() or child.name.casefold() in excludes:
            continue
        sides = sides_for(child)
        if sides[left_name] is not None or sides[right_name] is not None:
            paired.append((child.name, child, sides))
        elif has_recursive_images(child):
            standalone.append((child.name, child, {"SINGLE": child}))
    if paired:
        return paired
    if has_direct_images(root):
        return [(root.name or "root", root, {"SINGLE": root})]
    if standalone:
        return standalone
    return [(root.name or "root", root, {"SINGLE": root})]

def norm_pair_key(relative_path, mode):
    value = relative_path.replace("\\", "/")
    if mode == "basename":
        value = value.rsplit("/", 1)[-1]
    return unicodedata.normalize("NFC", value).casefold()

def collect_side(group_id, side_id, folder):
    if folder is None:
        return {"side_id": side_id, "directory_present": False, "directory": None, "image_count": 0, "files": []}
    files = []
    for path in sorted(folder.rglob("*"), key=lambda p: str(p).casefold()):
        if any(part.casefold() in DEFAULT_EXCLUDES for part in path.relative_to(folder).parts[:-1]):
            continue
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            rel = path.relative_to(folder).as_posix()
            digest = sha256_file(path)
            stat = path.stat()
            file_id = hashlib.sha256(f"{group_id}\0{side_id}\0{rel}\0{digest}".encode("utf-8")).hexdigest()[:24]
            files.append({
                "file_id": file_id, "relative_path": rel, "name": path.name,
                "absolute_path": str(path.resolve()), "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns, "sha256": digest
            })
        except OSError as exc:
            files.append({"file_id": hashlib.sha256(str(path).encode()).hexdigest()[:24],
                          "relative_path": str(path), "name": path.name,
                          "sha256": None, "read_error": str(exc)})
    return {"side_id": side_id, "directory_present": True, "directory": str(folder.resolve()),
            "image_count": len(files), "files": files}

def build_inventory(input_root, left_name="WAVES_QR", right_name="WAVES_QR_RAW",
                    pair_key_mode="relative_path", exclude_names=None):
    root = Path(input_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"input_root 不存在或不是目录: {root}")
    excludes = {x.casefold() for x in (exclude_names or DEFAULT_EXCLUDES)}
    groups = []
    for group_name, group_path, side_paths in discover_groups(root, left_name, right_name, excludes):
        group_rel = "." if group_path == root else group_path.relative_to(root).as_posix()
        group_id = hashlib.sha256(f"{root}|{group_rel}".encode("utf-8")).hexdigest()[:16]
        sides = [collect_side(group_id, side_id, folder) for side_id, folder in side_paths.items()]
        pairs = []
        if len(sides) == 1 and sides[0]["side_id"] == "SINGLE":
            for item in sides[0]["files"]:
                pairs.append({"pair_key": item["relative_path"], "pair_status": "SINGLE",
                              "left_file_ids": [item["file_id"]], "right_file_ids": []})
        else:
            left = next((s for s in sides if s["side_id"] == left_name), {"files": [], "directory_present": False})
            right = next((s for s in sides if s["side_id"] == right_name), {"files": [], "directory_present": False})
            lmap, rmap = {}, {}
            for item in left["files"]:
                lmap.setdefault(norm_pair_key(item["relative_path"], pair_key_mode), []).append(item)
            for item in right["files"]:
                rmap.setdefault(norm_pair_key(item["relative_path"], pair_key_mode), []).append(item)
            for key in sorted(set(lmap) | set(rmap)):
                li, ri = lmap.get(key, []), rmap.get(key, [])
                status = "AMBIGUOUS_PAIR" if len(li) > 1 or len(ri) > 1 else (
                    "PAIRED" if li and ri else "LEFT_ONLY" if li else "RIGHT_ONLY")
                pairs.append({"pair_key": key, "pair_status": status,
                              "left_file_ids": [x["file_id"] for x in li],
                              "right_file_ids": [x["file_id"] for x in ri]})
        stats = {
            "image_file_count": sum(s["image_count"] for s in sides),
            "pair_count": sum(p["pair_status"] == "PAIRED" for p in pairs),
            "left_only_count": sum(p["pair_status"] == "LEFT_ONLY" for p in pairs),
            "right_only_count": sum(p["pair_status"] == "RIGHT_ONLY" for p in pairs),
            "ambiguous_pair_count": sum(p["pair_status"] == "AMBIGUOUS_PAIR" for p in pairs),
            "missing_side_count": sum(not s["directory_present"] for s in sides)
        }
        groups.append({"group_id": group_id, "group_name": group_name, "group_relative_path": group_rel,
                       "pair_key_mode": pair_key_mode, "sides": sides, "pairs": pairs, "stats": stats})
    return {"schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(),
            "input_root": str(root), "left_directory": left_name, "right_directory": right_name,
            "pair_key_mode": pair_key_mode, "groups": groups}

def write_json(path, data, overwrite=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"拒绝覆盖已有文件: {path}")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)

def main():
    p = argparse.ArgumentParser(description="离线清点二维码图片、计算 SHA-256 并发现左右目录配对。")
    p.add_argument("--input-root", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--left-name", default="WAVES_QR")
    p.add_argument("--right-name", default="WAVES_QR_RAW")
    p.add_argument("--pair-key-mode", choices=["relative_path", "basename"], default="relative_path")
    p.add_argument("--exclude", action="append", default=[])
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    try:
        data = build_inventory(args.input_root, args.left_name, args.right_name, args.pair_key_mode,
                               set(DEFAULT_EXCLUDES) | set(args.exclude))
        write_json(args.output, data, args.overwrite)
        print(json.dumps({"status": "PASS", "output": str(Path(args.output).resolve()),
                          "groups": len(data["groups"]),
                          "image_files": sum(g["stats"]["image_file_count"] for g in data["groups"]),
                          "pairs": sum(g["stats"]["pair_count"] for g in data["groups"])}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())