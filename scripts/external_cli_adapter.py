"""Opt-in, offline-by-design subprocess bridge for an existing QR scanner.

The bridge does not implement any of the 28 preprocessing strategies. It binds
registered IDs to the native scanner's own strategy IDs and preserves evidence.
The user-selected subprocess is trusted code: this module cannot sandbox it.
"""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

CONFIG_ENV = "QR_AUDIT_BRIDGE_CONFIG"
TOKEN_RE = re.compile(r"\{([a-z0-9_]+)\}")
ALLOWED_TOKENS = {
    "image_path", "image_id", "input_sha256", "run_id", "strategy_id",
    "native_strategy", "decoder_id", "native_decoder",
}
ALLOWED_STATUSES = {
    "DECODED", "DETECTED_ONLY", "NO_DECODE", "ERROR",
    "NOT_RUN", "SKIPPED_INELIGIBLE",
}


def read_bridge_config(path):
    path = Path(path).expanduser().resolve(strict=True)
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != "1.0":
        raise ValueError("bridge schema_version must be 1.0")
    command = config.get("command")
    if not isinstance(command, dict):
        raise ValueError("bridge command must be an object")
    executable = Path(str(command.get("executable", ""))).expanduser()
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("bridge command.executable must be an existing absolute file")
    args = command.get("args")
    if not isinstance(args, list) or not args or not all(isinstance(arg, str) for arg in args):
        raise ValueError("bridge command.args must be a nonempty list of string argv")
    for arg in args:
        tokens = TOKEN_RE.findall(arg)
        if set(tokens) - ALLOWED_TOKENS or arg.count("{") != len(tokens) or arg.count("}") != len(tokens):
            raise ValueError(f"bridge command.args contains invalid placeholder: {arg}")
    timeout = command.get("timeout_seconds", 30)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not (0 < timeout <= 600):
        raise ValueError("bridge timeout_seconds must be in (0, 600]")
    decoder = config.get("decoder")
    if not isinstance(decoder, dict) or not decoder.get("decoder_id") or not decoder.get("native_decoder"):
        raise ValueError("bridge decoder requires decoder_id and native_decoder")
    if not config.get("scanner_version"):
        raise ValueError("bridge scanner_version is required")
    strategies = config.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        raise ValueError("bridge strategies must be a nonempty list")
    seen = set()
    for item in strategies:
        if not isinstance(item, dict) or not item.get("strategy_id") or not item.get("native_strategy"):
            raise ValueError("each bridge strategy requires strategy_id and native_strategy")
        if item["strategy_id"] in seen:
            raise ValueError(f"duplicate bridge strategy_id: {item['strategy_id']}")
        seen.add(item["strategy_id"])
        if item.get("source_size_min_bytes") is not None and (
            not isinstance(item["source_size_min_bytes"], int) or item["source_size_min_bytes"] < 0
        ):
            raise ValueError("source_size_min_bytes must be nonnegative integer")
    for value in config.get("source_files", []):
        if not Path(value).is_absolute() or not Path(value).is_file():
            raise ValueError(f"bridge declared source file is not accessible: {value}")
    config["_config_path"] = str(path)
    config["_executable_path"] = str(executable.resolve())
    config["_args"] = args
    config["_timeout"] = float(timeout)
    config["_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return config


def _applicability(image_meta, context, parameters):
    threshold = parameters.get("source_size_min_bytes")
    if threshold is None:
        return True
    try:
        size = Path(image_meta["path"]).stat().st_size
    except (KeyError, OSError) as exc:
        raise RuntimeError(f"cannot inspect source for applicability: {exc}") from exc
    return (size >= threshold, "SOURCE_FILE_TOO_SMALL")


def _decode_from_cli(config, variant, context, options):
    image_meta = context.get("image_meta")
    if not isinstance(image_meta, dict):
        raise ValueError("bridge requires image_meta from scan runtime")
    strategy_id = context.get("strategy_id")
    mapping = {s["strategy_id"]: s for s in config["strategies"]}
    if strategy_id not in mapping:
        raise ValueError(f"unregistered bridge strategy: {strategy_id}")
    native = mapping[strategy_id]["native_strategy"]
    run_id = context.get("run_id")
    decoder_id = context.get("decoder_id")
    path = Path(image_meta.get("path", "")).resolve(strict=True)
    if not path.is_file():
        raise ValueError("image path is not a file")
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != image_meta.get("sha256"):
        raise ValueError(f"source image hash changed before native attempt: {path}")
    values = {
        "image_path": str(path), "image_id": str(image_meta["image_id"]),
        "input_sha256": actual_sha, "run_id": str(run_id),
        "strategy_id": str(strategy_id), "native_strategy": str(native),
        "decoder_id": str(decoder_id), "native_decoder": str(config["decoder"]["native_decoder"]),
    }
    argv = [config["_executable_path"]] + [arg.format_map(values) for arg in config["_args"]]
    working_dir = config["command"].get("cwd")
    if working_dir and (not Path(working_dir).is_absolute() or not Path(working_dir).is_dir()):
        raise ValueError("bridge cwd must be an existing absolute directory")
    try:
        completed = subprocess.run(
            argv, cwd=working_dir or None, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=config["_timeout"], shell=False, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"native scanner timed out after {config['_timeout']} seconds") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"native scanner exit_code={completed.returncode}; output omitted for payload safety")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("native scanner stdout is not one JSON object") from exc
    if not isinstance(response, dict):
        raise ValueError("native scanner response must be an object")
    for key, expected in (
        ("run_id", run_id), ("image_id", image_meta["image_id"]),
        ("input_sha256", actual_sha), ("strategy_id", strategy_id),
        ("native_strategy", native), ("decoder_id", decoder_id),
    ):
        if response.get(key) != expected:
            raise ValueError(f"native scanner response {key} does not match requested attempt")
    status = response.get("status")
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"native scanner returned unsupported status: {status}")
    if status == "DECODED" and not response.get("payloads"):
        raise ValueError("native DECODED response has no payloads")
    if status != "DECODED" and response.get("payloads"):
        raise ValueError("native non-DECODED response must not contain payloads")
    if status in ("NOT_RUN", "SKIPPED_INELIGIBLE") and not response.get("skip_reason"):
        raise ValueError(f"native {status} requires skip_reason")
    if status == "ERROR" and not response.get("error"):
        raise ValueError("native ERROR requires error")
    candidate_count = response.get("candidate_count", 0)
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int) or candidate_count < 0:
        raise ValueError("native candidate_count must be a nonnegative integer")
    if status == "DETECTED_ONLY" and candidate_count == 0:
        raise ValueError("native DETECTED_ONLY requires candidate_count > 0")
    # A verified attempt belongs to this run; the actual native algorithms
    # and decoder are identified by the subprocess's attested response.
    return {
        "status": status, "payloads": response.get("payloads", []),
        "candidate_count": candidate_count,
        "skip_reason": response.get("skip_reason"),
        "error": response.get("error"),
        "native_strategy_id": native,
        "native_decoder_id": config["decoder"]["native_decoder"],
        "native_scanner_version": str(config["scanner_version"]),
        "bridge_config_sha256": config["_sha256"],
    }


def register_qr_audit(strategies, decoders, context):
    value = os.environ.get(CONFIG_ENV)
    if not value:
        raise ValueError(f"set {CONFIG_ENV} to an absolute bridge config JSON path")
    config = read_bridge_config(value)
    declared = context.setdefault("source_files", [])
    declared.extend([
        config["_config_path"], config["_executable_path"],
        *config.get("source_files", []),
    ])
    context.setdefault("dependencies", []).append({
        "name": "existing-native-scanner", "version": str(config["scanner_version"]),
        "executable": config["_executable_path"], "bridge_config_sha256": config["_sha256"],
    })
    for item in config["strategies"]:
        strategies.register(
            item["strategy_id"],
            lambda path, ctx, params: path,
            version=str(item.get("version") or config["scanner_version"]),
            parameters={
                "native_strategy": item["native_strategy"],
                "source_size_min_bytes": item.get("source_size_min_bytes"),
            },
            applicability=_applicability,
            applicability_description="SOURCE_SIZE_RULE" if item.get("source_size_min_bytes") is not None else "ALWAYS",
            input_mode="source_file",
            replace=True,
        )
    decoder = config["decoder"]
    decoders.register(
        decoder["decoder_id"],
        lambda variant, ctx, opts: _decode_from_cli(config, variant, ctx, opts),
        version=str(decoder.get("version") or config["scanner_version"]),
        options={
            "bridge_config_sha256": config["_sha256"],
            "native_decoder_id": decoder["native_decoder"],
        },
        replace=True,
    )
