"""Optional offline WeChatQRCode decoder; never downloads weights or changes Vxx.

OpenCV 4.x uses four Caffe model files, while OpenCV 5.x uses two ONNX
models. A detector instance is kept per worker thread for native safety.
"""
import json
import os
import threading
from pathlib import Path

CONFIG_ENV = "QR_AUDIT_WECHAT_MODEL_CONFIG"


def _factory(cv2):
    direct = getattr(cv2, "wechat_qrcode_WeChatQRCode", None)
    if callable(direct):
        return direct
    wrapped = getattr(getattr(cv2, "wechat_qrcode", None), "WeChatQRCode", None)
    return wrapped if callable(wrapped) else None


def _models(cv2, config_path):
    config = Path(config_path).expanduser().resolve(strict=True)
    body = json.loads(config.read_text(encoding="utf-8"))
    if not isinstance(body, dict) or not isinstance(body.get("models"), list):
        raise ValueError("wechat config must contain a models list")
    version = str(getattr(cv2, "__version__", "0"))
    major = int(version.split(".", 1)[0])
    expected = 2 if major >= 5 else 4
    names = body["models"]
    if len(names) != expected or not all(isinstance(x, str) and x for x in names):
        raise ValueError(f"OpenCV {major} requires exactly {expected} WeChatQRCode model paths")
    paths = []
    for name in names:
        path = Path(name).expanduser()
        if not path.is_absolute():
            path = config.parent / path
        path = path.resolve(strict=True)
        if not path.is_file():
            raise ValueError("WeChatQRCode model is not a regular file")
        paths.append(str(path))
    return str(config), paths


def register_qr_audit(strategies, decoders, context):
    config_path = os.environ.get(CONFIG_ENV)
    cv2 = context.get("cv2")
    factory = _factory(cv2) if cv2 is not None else None
    if not config_path or factory is None:
        reasons = []
        if not config_path:
            reasons.append(f"set {CONFIG_ENV} to local model config")
        if factory is None:
            reasons.append("OpenCV build has no WeChatQRCode module")
        decoders.register(
            "wechat", None, version=str(getattr(cv2, "__version__", "UNAVAILABLE")),
            available=False, unavailable_reason="WECHAT_DECODER_UNAVAILABLE: " + "; ".join(reasons),
        )
        return

    config_file, models = _models(cv2, config_path)
    context.setdefault("source_files", []).extend([config_file] + models)
    context.setdefault("dependencies", []).append({
        "name": "wechat-qrcode-opencv", "version": str(getattr(cv2, "__version__", "UNKNOWN")),
        "model_count": len(models), "source": "local-files-only",
    })
    thread_state = threading.local()

    def decode(image, decoder_context, options):
        if not hasattr(thread_state, "engine"):
            thread_state.engine = factory(*models)
        values = thread_state.engine.detectAndDecode(image)
        decoded, points = values if isinstance(values, tuple) and len(values) == 2 else (values, None)
        if isinstance(decoded, str):
            decoded = [decoded]
        payloads = [str(x) for x in decoded or [] if x]
        try:
            candidates = len(points) if points is not None else len(payloads)
        except TypeError:
            candidates = len(payloads)
        return {"payloads": payloads, "candidate_count": max(candidates, len(payloads))}

    decoders.register(
        "wechat", decode,
        version=f"opencv-{getattr(cv2, '__version__', 'UNKNOWN')}-local-models",
        options={"model_count": len(models), "thread_local": True},
    )
