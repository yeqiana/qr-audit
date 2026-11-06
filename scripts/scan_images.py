"""Offline scanner with explicit executor registration and before/after input snapshots."""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from evidence_contract import canonical_sha256, file_sha256
from regression_gate import compare_directories
from fallback_pipeline import compose_registry, decoder_filters, summarize
from executor_registry import (
    StrategyExecutorRegistry, DecoderExecutorRegistry,
    register_builtin_strategies, register_builtin_decoders, load_adapter_modules,
)
from inventory_images import build_inventory


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_library(name):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise RuntimeError(f"本地依赖缺失: {name}；qr-audit 不会联网安装") from exc


def git_fingerprint(root):
    try:
        rev = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=5)
        return {
            "git_commit": rev.stdout.strip() if rev.returncode == 0 else "NOT_A_GIT_REPOSITORY",
            "git_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"git_commit": "NOT_VERIFIED", "git_dirty": None}


def load_image(path, cv2, np):
    buffer = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        from PIL import Image
        with Image.open(path) as source:
            rgb = np.asarray(source.convert("RGB"))
        image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return image


def source_fingerprint(workspace_root, registry_path, adapter_modules, extra_sources=None):
    candidates = [
        Path(__file__).resolve(),
        Path(__file__).resolve().parents[1] / "SKILL.md",
        Path(__file__).resolve().parents[1] / "PACKAGE-MANIFEST.json",
        Path(__file__).with_name("inventory_images.py").resolve(),
        Path(__file__).with_name("executor_registry.py").resolve(),
        Path(__file__).with_name("evidence_contract.py").resolve(),
        Path(__file__).with_name("validate_evidence.py").resolve(),
        Path(__file__).with_name("analyze_contributions.py").resolve(),
        Path(__file__).with_name("regression_gate.py").resolve(),
        Path(__file__).with_name("fallback_pipeline.py").resolve(),
        Path(__file__).with_name("ai_recovery_core.py").resolve(),
        Path(__file__).with_name("build_report_models.py").resolve(),
        Path(__file__).with_name("render_reports.py").resolve(),
        Path(__file__).with_name("run.py").resolve(),
        Path(registry_path).resolve(),
    ]
    candidates.extend(Path(module.__file__).resolve() for module in adapter_modules if getattr(module, "__file__", None))
    for source_path in extra_sources or []:
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"adapter-declared source file does not exist: {path}")
        candidates.append(path)
    unique = []
    seen = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        unique.append({"path": str(path), "sha256": file_sha256(path)})
    return {
        **git_fingerprint(workspace_root),
        "fingerprint_scope": "qr-audit-scanner-and-loaded-adapters",
        "files": unique,
    }



def verify_source_snapshot(source):
    """Re-hash the exact source/config files pinned before scanning.

    An imported module may already be in memory: a changed disk file cannot
    silently produce a certified, reproducible run.
    """
    changed, missing = [], []
    checked = 0
    for item in source.get("files", []):
        path = item["path"]
        try:
            current = file_sha256(path)
        except OSError:
            missing.append(path)
            continue
        checked += 1
        if current != item["sha256"]:
            changed.append(path)
    return {
        "status": "STABLE" if not changed and not missing and checked else "CHANGED",
        "checked": checked,
        "changed_paths": changed,
        "missing_paths": missing,
    }


def ordered_image_map(fn, items, workers):
    """Bound pending futures and emit results in frozen inventory order."""
    if workers == 1:
        for item in items:
            yield fn(item)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        source = iter(items)
        pending = deque()
        for _ in range(workers * 2):
            try:
                pending.append(pool.submit(fn, next(source)))
            except StopIteration:
                break
        while pending:
            yield pending.popleft().result()
            try:
                pending.append(pool.submit(fn, next(source)))
            except StopIteration:
                pass


def inventory_snapshot(inventory):
    snapshot = {}
    for group in inventory.get("groups", []):
        for side in group.get("sides", []):
            for item in side.get("files", []):
                key = (group.get("group_id"), side.get("side_id"), item.get("relative_path"))
                snapshot[key] = item.get("sha256")
    return snapshot


def compare_inventory_snapshots(before, after):
    left, right = inventory_snapshot(before), inventory_snapshot(after)
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


def pair_lookup(inventory):
    result = {}
    for group in inventory.get("groups", []):
        for pair in group.get("pairs", []):
            for image_id in pair.get("left_file_ids", []) + pair.get("right_file_ids", []):
                result[image_id] = pair
    return result


def make_manifest(run_id, inventory, workspace_root, registry, registry_path,
                  strategy_executors, decoder_executors, adapter_modules, mode, decoder_ids, context):
    pair_map = pair_lookup(inventory)
    images = []
    for group in inventory["groups"]:
        for side in group["sides"]:
            for item in side["files"]:
                pair = pair_map.get(item["file_id"], {})
                images.append({
                    "image_id": item["file_id"], "group_id": group["group_id"],
                    "side_id": side["side_id"], "path": item.get("absolute_path"),
                    "relative_path": item["relative_path"], "sha256": item.get("sha256"),
                    "pair_id": pair.get("pair_id"), "pair_key": pair.get("pair_key"),
                    "pair_status": pair.get("pair_status"),
                })
    strategies = []
    for item in registry.get("strategies", []):
        strategy = dict(item)
        executor = strategy_executors.get(item["strategy_id"])
        strategy["executor_status"] = "REGISTERED" if executor else "NOT_CONNECTED"
        strategy["executor_version"] = executor.version if executor else None
        strategy["applicability"] = executor.applicability_description if executor else "NOT_CONNECTED"
        if executor:
            strategy["runtime_parameters"] = executor.parameters
        strategies.append(strategy)
    decoders = []
    for decoder_id in decoder_ids:
        decoder = decoder_executors.get(decoder_id)
        decoders.append({
            "decoder_id": decoder_id, "version": decoder.version,
            "available": decoder.available, "options": decoder.options,
            "unavailable_reason": decoder.unavailable_reason or None,
        })
    return {
        "schema_version": "2.0", "run_id": run_id, "mode": mode,
        "started_at": utc_now(), "input_root": inventory["input_root"],
        "inventory_sha256": canonical_sha256(inventory),
        "strategy_registry_sha256": canonical_sha256(registry),
        "source_fingerprint": source_fingerprint(
            workspace_root, registry_path, adapter_modules, context.get("source_files", [])
        ),
        "dependencies": [],
        "strategy_order": [x["strategy_id"] for x in strategies],
        "strategies": strategies, "decoders": decoders, "images": images,
        "input_consistency": {"status": "PENDING"},
        "wechat_scan_status": "NOT_TESTED", "business_validity": "NOT_VERIFIED",
    }


def normalize_decode_result(result):
    if isinstance(result, dict):
        payloads = result.get("payloads", result.get("texts", []))
        candidates = result.get("candidate_count", result.get("candidates", len(payloads or [])))
    elif isinstance(result, tuple) and len(result) == 2:
        payloads, candidates = result
    else:
        payloads, candidates = result, len(result or [])
    if isinstance(payloads, (str, dict)):
        payloads = [payloads]
    normalized = []
    for value in payloads or []:
        if isinstance(value, str) and value:
            normalized.append(value)
        elif isinstance(value, dict) and (value.get("identity") or value.get("text") or value.get("payload")):
            normalized.append(value)
        elif value not in (None, ""):
            normalized.append(str(value))
    return normalized, int(candidates or 0)


def attempt_record(run_id, image_meta, strategy_id, decoder, status, started,
                   attempt_index=1, **extra):
    record = {
        "attempt_id": f"{run_id}-{image_meta['image_id']}-{strategy_id}-{decoder.decoder_id}-{attempt_index}",
        "attempt_index": attempt_index, "run_id": run_id,
        "image_id": image_meta["image_id"], "group_id": image_meta["group_id"],
        "side_id": image_meta["side_id"], "relative_path": image_meta["relative_path"],
        "input_sha256": image_meta.get("sha256"), "pair_id": image_meta.get("pair_id"),
        "strategy_id": strategy_id, "strategy_order": None,
        "decoder_id": decoder.decoder_id, "decoder_version": decoder.version,
        "decoder_options": decoder.options, "status": status,
        "payload": None, "payload_sha256": None, "payload_hash_algorithm": None,
        "payload_hash_scope": None, "payloads": [],
        "candidate_count": 0, "duration_ms": 0.0, "transform_duration_ms": 0.0,
        "error": None, "skip_reason": None, "executed_at": utc_now(),
    }
    record.update(extra)
    return record


def execute_image_matrix(run_id, image_meta, strategy_order, strategy_executors,
                         decoder_executors, decoder_ids, mode, image_loader, context,
                         max_pixels=50000000, decoder_strategy_filters=None):
    """One declared record per logical image×strategy×decoder combination.

    Source-file adapters can delegate to existing native scanners without
    OpenCV/NumPy and without claiming Python performed image preprocessing.
    """
    from evidence_contract import text_identity, payload_identities

    records = []
    image_success = False
    for order, strategy_id in enumerate(strategy_order, 1):
        strategy = strategy_executors.get(strategy_id)
        stopped = mode == "scan" and image_success
        transform_error = None
        ineligible_reason = None
        transform_ms = 0.0
        transformed = None
        strategy_context = dict(
            context, image_meta=image_meta, strategy_id=strategy_id, run_id=run_id
        )

        if not stopped and strategy is None:
            transform_error = "NOT_IMPLEMENTED: no strategy executor registered"
        elif not stopped and strategy is not None:
            if not image_meta.get("sha256"):
                transform_error = "INPUT_HASH_UNAVAILABLE: original file hash is missing"
            elif strategy.input_mode == "pixels" and (
                context.get("cv2") is None or context.get("numpy") is None
            ):
                # Legacy synthetic tests supply their own loader and no cv2.
                if context.get("require_image_dependencies", False):
                    transform_error = "DEPENDENCY_MISSING: OpenCV / NumPy are unavailable"
            if not transform_error and strategy.applicability is not None:
                try:
                    applicable = strategy.applicability(
                        image_meta, strategy_context, strategy.parameters
                    )
                    if isinstance(applicable, tuple):
                        applicable, ineligible_reason = applicable
                    if not applicable:
                        ineligible_reason = ineligible_reason or "STRATEGY_NOT_APPLICABLE"
                except Exception as exc:
                    transform_error = f"APPLICABILITY_ERROR: {type(exc).__name__}: {exc}"
            if not ineligible_reason and not transform_error:
                try:
                    started = time.perf_counter()
                    if strategy.input_mode == "source_file":
                        original = image_meta["path"]
                    else:
                        original = image_loader(image_meta)
                        if original.shape[0] * original.shape[1] > max_pixels:
                            raise ValueError("MAX_PIXELS_EXCEEDED")
                    transformed = strategy.transform(
                        original, strategy_context, strategy.parameters
                    )
                    if transformed is None:
                        raise ValueError("strategy transform returned None")
                    if strategy.input_mode == "source_file":
                        variant_path = Path(transformed).resolve(strict=True)
                        if not variant_path.is_file():
                            raise ValueError("source_file transform must return a file path")
                        transformed = str(variant_path)
                    transform_ms = (time.perf_counter() - started) * 1000
                except Exception as exc:
                    transform_error = f"{type(exc).__name__}: {exc}"

        for decoder_id in decoder_ids:
            decoder = decoder_executors.get(decoder_id)
            if decoder is None:
                raise ValueError(f"decoder registry missing declared decoder: {decoder_id}")
            record = attempt_record(
                run_id, image_meta, strategy_id, decoder, "NOT_RUN", time.perf_counter()
            )
            record["strategy_order"] = order
            record["input_mode"] = strategy.input_mode if strategy else "NOT_CONNECTED"
            record["transform_duration_ms"] = round(transform_ms, 3)
            if stopped:
                record["status"] = "SKIPPED_EARLY_STOP"
                record["skip_reason"] = "EARLIER_STRATEGY_DECODED"
            elif decoder_strategy_filters is not None and strategy_id not in decoder_strategy_filters.get(decoder_id, (strategy_id,)):
                record["status"] = "SKIPPED_INELIGIBLE"
                record["skip_reason"] = "DECODER_STRATEGY_FILTER"
            elif strategy is None:
                record["status"] = "NOT_RUN"
                record["skip_reason"] = transform_error
            elif ineligible_reason:
                record["status"] = "SKIPPED_INELIGIBLE"
                record["skip_reason"] = ineligible_reason
            elif not decoder.available:
                record["status"] = "NOT_RUN"
                record["skip_reason"] = decoder.unavailable_reason or "DECODER_UNAVAILABLE"
            elif transform_error:
                if transform_error.startswith(("DEPENDENCY_MISSING", "INPUT_HASH_UNAVAILABLE")):
                    record["status"] = "NOT_RUN"
                    record["skip_reason"] = transform_error
                else:
                    record["status"] = "ERROR"
                    record["error"] = transform_error
            else:
                started = time.perf_counter()
                try:
                    decoder_context = dict(strategy_context, decoder_id=decoder_id)
                    raw_result = decoder.decode(transformed, decoder_context, decoder.options)
                    payloads, candidate_count = normalize_decode_result(raw_result)
                    native_status = raw_result.get("status") if isinstance(raw_result, dict) else None
                    if native_status is not None and native_status not in (
                        "DECODED", "DETECTED_ONLY", "NO_DECODE", "ERROR",
                        "NOT_RUN", "SKIPPED_INELIGIBLE"
                    ):
                        raise ValueError(f"unsupported decoder status: {native_status}")
                    record["candidate_count"] = candidate_count
                    record["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
                    if strategy.input_mode == "source_file":
                        record["variant_width"] = None
                        record["variant_height"] = None
                        record["variant_sha256"] = file_sha256(transformed)
                    else:
                        record["variant_width"] = int(transformed.shape[1])
                        record["variant_height"] = int(transformed.shape[0])
                        record["variant_sha256"] = hashlib.sha256(transformed.tobytes()).hexdigest()
                    if isinstance(raw_result, dict):
                        for field in (
                            "native_strategy_id", "native_decoder_id",
                            "native_scanner_version", "bridge_config_sha256",
                            "ai_detector_candidates", "ai_decode_calls", "ai_engine_hits", "module_recovery_method", "module_extra_decode_calls",
                        ):
                            if field in raw_result:
                                record[field] = raw_result[field]
                    if native_status in ("SKIPPED_INELIGIBLE", "NOT_RUN", "ERROR"):
                        if payloads:
                            raise ValueError("native non-DECODED result returned payloads")
                        record["status"] = native_status
                        if native_status == "ERROR":
                            record["error"] = raw_result.get("error") or "NATIVE_SCANNER_ERROR"
                        else:
                            record["skip_reason"] = raw_result.get("skip_reason") or "NATIVE_NOT_EXECUTED"
                    elif payloads:
                        if native_status in ("NO_DECODE", "DETECTED_ONLY"):
                            raise ValueError("native status contradicts returned payloads")
                        entries = []
                        for value in payloads:
                            if isinstance(value, str):
                                text_value = value
                                identity = text_identity(value)
                            else:
                                text_value = value.get("text", value.get("payload"))
                                identity = value.get("identity")
                                if identity is None and value.get("payload_sha256"):
                                    identity = {
                                        "algorithm": value.get("payload_hash_algorithm", ""),
                                        "scope": value.get("payload_hash_scope", ""),
                                        "value": value["payload_sha256"],
                                    }
                                if identity is None:
                                    if text_value in (None, ""):
                                        raise ValueError("decoder payload requires text or explicit identity")
                                    identity = text_identity(text_value)
                            entries.append({"text": text_value, "identity": identity})
                        record["status"] = "DECODED"
                        record["payloads"] = entries
                        first_text = next(
                            (item["text"] for item in entries if item["text"] not in (None, "")),
                            None,
                        )
                        record["payload"] = first_text
                        first_identity = entries[0]["identity"]
                        if first_identity.get("algorithm") == "sha256":
                            record["payload_sha256"] = first_identity["value"]
                            record["payload_hash_algorithm"] = first_identity["algorithm"]
                            record["payload_hash_scope"] = first_identity["scope"]
                        record["all_payloads"] = [
                            item["text"] for item in entries if item["text"] not in (None, "")
                        ]
                        # Reject inconsistent text/hash from the native decoder.
                        payload_identities(record)
                        image_success = True
                    else:
                        if native_status == "DECODED":
                            raise ValueError("native DECODED result has no payload")
                        if native_status == "DETECTED_ONLY" and candidate_count == 0:
                            raise ValueError("native DETECTED_ONLY has no candidates")
                        record["status"] = native_status or (
                            "DETECTED_ONLY" if candidate_count else "NO_DECODE"
                        )
                except Exception as exc:
                    record["status"] = "ERROR"
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    record["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            records.append(record)
    return records, image_success



def run_scan(input_root, report_root, workspace_root=None, decoders=None,
             max_pixels=50000000, left_name="WAVES_QR", right_name="WAVES_QR_RAW",
             mode="scan", adapter_modules=None, workers=1, registry_path=None,
             required_strategies=None, baseline_evidence=None,
             require_upgrade_gate=False, boost_fallback=False,
             wechat_fallback=False, ai_fallback=False, ai_model_config=None):
    input_root = Path(input_root).expanduser().resolve()
    report_root = Path(report_root).expanduser().resolve()
    workspace_root = Path(workspace_root).expanduser().resolve() if workspace_root else input_root.parent
    if not input_root.is_dir():
        raise ValueError("input_root 不存在")
    if mode not in ("scan", "contribution"):
        raise ValueError("mode must be scan or contribution")
    if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= 8:
        raise ValueError("workers must be an integer between 1 and 8")
    # Lower-level entry points (including custom scan_all.py) must use this
    # same gate. The environment option supports existing local runners
    # without requiring code changes or modifying the old evidence.
    baseline_evidence = baseline_evidence or os.environ.get("QR_AUDIT_BASELINE_EVIDENCE")
    if os.environ.get("QR_AUDIT_REQUIRE_BASELINE") not in (None, "", "0", "1"):
        raise ValueError("QR_AUDIT_REQUIRE_BASELINE must be 0 or 1")
    require_upgrade_gate = require_upgrade_gate or (
        os.environ.get("QR_AUDIT_REQUIRE_BASELINE") == "1"
    )
    if require_upgrade_gate and not baseline_evidence:
        raise ValueError("BASELINE_EVIDENCE_REQUIRED: no verified historical run was supplied")
    if wechat_fallback and not boost_fallback:
        raise ValueError("WECHAT_FALLBACK_REQUIRES_BOOST_FALLBACK")

    # External source-file adapters need no image-decoding dependencies.
    try:
        cv2 = get_library("cv2")
        np = get_library("numpy")
    except RuntimeError:
        cv2, np = None, None
    strategy_executors = StrategyExecutorRegistry()
    decoder_executors = DecoderExecutorRegistry()
    zxing = None
    if cv2 is not None and np is not None:
        register_builtin_strategies(strategy_executors, cv2)
        try:
            zxing = get_library("zxingcpp")
        except RuntimeError:
            pass
        register_builtin_decoders(decoder_executors, cv2, zxing)
    else:
        decoder_executors.register(
            "opencv", None, version="UNAVAILABLE", available=False,
            unavailable_reason="DECODER_UNAVAILABLE: OpenCV and NumPy are not installed",
        )
        decoder_executors.register(
            "zxingcpp", None, version="UNAVAILABLE", available=False,
            unavailable_reason="DECODER_UNAVAILABLE: OpenCV and NumPy are not installed",
        )
    context = {
        "cv2": cv2, "numpy": np, "input_root": str(input_root), "mode": mode,
        "ai_config_path": ai_model_config,
        "source_files": [], "dependencies": [],
        "require_image_dependencies": True,
    }
    selected_adapters = list(adapter_modules or [])
    if boost_fallback:
        if cv2 is None or np is None:
            raise ValueError("FALLBACK_REQUIRES_OPENCV_AND_NUMPY")
        if "recognition_boost_adapter" not in selected_adapters:
            selected_adapters.append("recognition_boost_adapter")
    if wechat_fallback and "wechat_decoder_adapter" not in selected_adapters:
        selected_adapters.append("wechat_decoder_adapter")
    if ai_fallback and "ai_qr_adapter" not in selected_adapters:
        selected_adapters.append("ai_qr_adapter")
    loaded_adapters = load_adapter_modules(
        selected_adapters, strategy_executors, decoder_executors, context
    )

    original_decoders = list(dict.fromkeys(decoders or ["opencv"]))
    requested_decoders = list(original_decoders)
    if boost_fallback:
        for decoder_id in ("opencv", "zxingcpp"):
            registered = decoder_executors.get(decoder_id)
            if registered is not None and registered.available and decoder_id not in requested_decoders:
                requested_decoders.append(decoder_id)
    if ai_fallback:
        ai_decoder = decoder_executors.get("ai")
        if ai_decoder is None or not ai_decoder.available:
            raise ValueError("AI_FALLBACK_UNAVAILABLE")
        if "ai" not in requested_decoders:
            requested_decoders.append("ai")
    if wechat_fallback:
        wechat = decoder_executors.get("wechat")
        if wechat is None or not wechat.available:
            raise ValueError("WECHAT_FALLBACK_UNAVAILABLE: configure existing local models")
        if "wechat" not in requested_decoders:
            requested_decoders.append("wechat")
    for decoder_id in requested_decoders:
        if decoder_executors.get(decoder_id) is None:
            decoder_executors.register(
                decoder_id, None, version="UNAVAILABLE", available=False,
                unavailable_reason=f"DECODER_UNAVAILABLE: no adapter registered for {decoder_id}",
            )

    inventory = build_inventory(input_root, left_name, right_name)
    registry_path = Path(registry_path).expanduser().resolve() if registry_path else (
        Path(__file__).resolve().parents[1] / "assets" / "strategy-registry.initial.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    base_strategy_ids = [row["strategy_id"] for row in registry.get("strategies", [])]
    filters = None
    if boost_fallback or ai_fallback:
        boost_registry_path = Path(__file__).resolve().parents[1] / "assets" / "strategy-registry.boost.json"
        if boost_fallback and not boost_registry_path.is_file():
            raise ValueError("FALLBACK_REGISTRY_NOT_FOUND")
        boost_registry = (
            json.loads(boost_registry_path.read_text(encoding="utf-8"))
            if boost_fallback else {"strategies": []}
        )
        if boost_fallback:
            context["source_files"].append(str(boost_registry_path))
        registry = compose_registry(registry, boost_registry, wechat_fallback, ai_fallback)
        boost_ids = [row["strategy_id"] for row in boost_registry["strategies"]]
        if wechat_fallback:
            strategy_executors.register(
                "W01", lambda image, ctx, params: image,
                version="wechat-fallback-1",
                parameters={"operation": "identity", "last_resort": True},
            )
        filters = decoder_filters(
            base_strategy_ids, boost_ids, original_decoders,
            requested_decoders, wechat_fallback, ai_fallback,
        )
    strategy_ids = [row["strategy_id"] for row in registry.get("strategies", [])]
    if not strategy_ids or len(strategy_ids) != len(set(strategy_ids)):
        raise ValueError("selected strategy registry must declare unique non-empty strategy IDs")
    required_strategies = list(dict.fromkeys(required_strategies or []))
    not_connected = [
        strategy_id for strategy_id in required_strategies
        if strategy_id not in strategy_ids or strategy_executors.get(strategy_id) is None
    ]
    if not_connected:
        raise ValueError("REQUIRED_STRATEGY_NOT_CONNECTED: " + ",".join(not_connected))
    registered_count = sum(strategy_executors.get(x) is not None for x in strategy_ids)
    capability_status = (
        "FULLY_CONNECTED" if registered_count == len(strategy_ids)
        else "PARTIALLY_CONNECTED" if registered_count else "NOT_CONNECTED"
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + os.urandom(3).hex()
    run_root = report_root / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    evidence = run_root / "evidence"
    evidence.mkdir()
    inv_path = evidence / "inventory.json"
    inv_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    # Frozen composed registry must be available to the reporting/validation
    # path; the base registry file is never modified.
    (evidence / "strategy-registry.effective.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = make_manifest(
        run_id, inventory, workspace_root, registry, registry_path,
        strategy_executors, decoder_executors, loaded_adapters, mode, requested_decoders, context,
    )
    manifest["dependencies"] = [{"name": "python", "version": sys.version.split()[0]}]
    if cv2 is not None and np is not None:
        manifest["dependencies"].extend([
            {"name": "opencv-python", "version": str(getattr(cv2, "__version__", "UNKNOWN"))},
            {"name": "numpy", "version": str(getattr(np, "__version__", "UNKNOWN"))},
        ])
    manifest["dependencies"].extend(context.get("dependencies", []))
    if zxing is not None and any(x == "zxingcpp" for x in requested_decoders):
        manifest["dependencies"].append({
            "name": "zxing-cpp", "version": str(getattr(zxing, "__version__", "VERSION_NOT_EXPOSED")),
        })

    # Record the pinned code scope before the first image is processed.
    # A partial/failed run retains its initial manifest for diagnosis.
    manifest["execution"] = {
        "workers": workers, "backend": "threads", "ordered_output": True,
        "pending_limit": workers * 2 if workers > 1 else 1,
    }
    manifest["run_status"] = "RUNNING"
    manifest["capability_status"] = capability_status
    manifest["connected_strategy_count"] = registered_count
    manifest["declared_strategy_count"] = len(strategy_ids)
    manifest["required_strategies"] = required_strategies
    manifest["fallback_composition"] = registry.get("fallback_composition")
    manifest["fallback_decoder_filters"] = (
        {key: sorted(ids) for key, ids in filters.items()} if filters is not None else None
    )
    manifest["recognition_regression_status"] = "NOT_RUN"
    manifest["upgrade_gate_required"] = bool(require_upgrade_gate)
    manifest_path = evidence / "run-manifest.json"
    with manifest_path.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)

    def process_image(image_meta):
        return execute_image_matrix(
            run_id, image_meta, manifest["strategy_order"],
            strategy_executors, decoder_executors, requested_decoders,
            mode, lambda item: load_image(item["path"], cv2, np),
            context, max_pixels, decoder_strategy_filters=filters,
        )

    total, decoded_images = 0, 0
    attempts_path = evidence / "attempts.jsonl"
    with attempts_path.open("x", encoding="utf-8") as output:
        for records, image_success in ordered_image_map(process_image, manifest["images"], workers):
            for record in records:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
            total += len(records)
            if image_success:
                decoded_images += 1

    inventory_after = build_inventory(input_root, left_name, right_name)
    inventory_after_path = evidence / "inventory-after.json"
    inventory_after_path.write_text(
        json.dumps(inventory_after, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest["input_consistency"] = compare_inventory_snapshots(inventory, inventory_after)
    manifest["input_inventory_after_sha256"] = canonical_sha256({
        k: v for k, v in inventory_after.items() if k != "generated_at"
    })
    manifest["source_consistency"] = verify_source_snapshot(manifest["source_fingerprint"])
    fallback_summary = None
    if boost_fallback or ai_fallback:
        with attempts_path.open("r", encoding="utf-8") as source:
            recorded = (json.loads(row) for row in source if row.strip())
            fallback_summary = summarize(recorded, manifest)
        (evidence / "fallback-summary.json").write_text(
            json.dumps(fallback_summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    manifest["finished_at"] = utc_now()
    manifest["attempt_count"] = total
    manifest["run_status"] = "COMPLETE"
    # The gate lives in run_scan, not just in the high-level run.py CLI;
    # any scanner invoking this function gets identical enforcement.
    regression = None
    if baseline_evidence:
        try:
            regression = compare_directories(baseline_evidence, evidence)
        except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            regression = {"status": "BLOCKED_UNVERIFIABLE", "error": str(exc)}
        (evidence / "recognition-regression.json").write_text(
            json.dumps(regression, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest["recognition_regression_status"] = regression["status"]
    if manifest["source_consistency"]["status"] != "STABLE":
        status = "BLOCKED_SOURCE_CHANGED"
    elif manifest["input_consistency"]["status"] != "STABLE":
        status = "BLOCKED_INPUT_CHANGED"
    elif regression and regression["status"] != "PASS_NON_REGRESSION":
        status = regression["status"]
    else:
        status = "PASS_NON_REGRESSION" if regression else "PASS_BASELINE_ONLY"
    manifest["acceptance_status"] = status
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": status, "run_root": str(run_root), "evidence": str(evidence),
        "image_count": len(manifest["images"]), "decoded_images": decoded_images,
        "attempts": total, "run_id": run_id, "workers": workers,
        "capability_status": capability_status, "regression": regression,
        "fallback": fallback_summary,
        "input_consistency": manifest["input_consistency"],
        "source_consistency": manifest["source_consistency"],
    }


def main():
    parser = argparse.ArgumentParser(description="二维码离线扫描；贡献度模式关闭提前停止。")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--report-root", required=True)
    parser.add_argument("--workspace-root")
    parser.add_argument("--decoder", action="append")
    parser.add_argument("--adapter-module", action="append", default=[],
                        help="可导入模块名；模块必须提供 register_qr_audit(strategies, decoders, context)")
    parser.add_argument("--mode", choices=["scan", "contribution"], default="scan")
    parser.add_argument("--workers", type=int, default=1,
                        help="1-8 independent image threads; default 1 for safest compatibility")
    parser.add_argument("--registry-path",
                        help="explicit frozen strategy registry; default original V01-V28")
    parser.add_argument("--require-strategy", action="append", default=[],
                        help="fail before run if a required legacy strategy is unconnected")
    parser.add_argument("--baseline-evidence",
                        help="required historical evidence for upgrade acceptance")
    parser.add_argument("--require-upgrade-gate", action="store_true",
                        help="reject scan without historical evidence")
    parser.add_argument("--boost-fallback", action="store_true",
                        help="append B01-B08 only after original strategies fail")
    parser.add_argument("--wechat-fallback", action="store_true",
                        help="append final W01 WeChatQRCode (requires boost and local models)")
    parser.add_argument("--ai-fallback", action="store_true",
                        help="experimental local YOLO detector + multi-decoder fallback")
    parser.add_argument("--ai-model-config",
                        help="existing local AI model/config JSON; no network fetch")
    parser.add_argument("--max-pixels", type=int, default=50000000)
    parser.add_argument("--left-name", default="WAVES_QR")
    parser.add_argument("--right-name", default="WAVES_QR_RAW")
    args = parser.parse_args()
    try:
        result = run_scan(
            args.input_root, args.report_root, args.workspace_root, args.decoder,
            args.max_pixels, args.left_name, args.right_name, args.mode, args.adapter_module,
            workers=args.workers, registry_path=args.registry_path,
            required_strategies=args.require_strategy,
            baseline_evidence=args.baseline_evidence,
            require_upgrade_gate=args.require_upgrade_gate,
            boost_fallback=args.boost_fallback,
            wechat_fallback=args.wechat_fallback,
            ai_fallback=args.ai_fallback,
            ai_model_config=args.ai_model_config,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] in ("PASS_BASELINE_ONLY", "PASS_NON_REGRESSION") else 3
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
