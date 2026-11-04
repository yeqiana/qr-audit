"""Small plugin contract for strategy transforms and decoder adapters."""
import importlib
from dataclasses import dataclass, field


@dataclass
class StrategyExecutor:
    strategy_id: str
    transform: object
    version: str = "1"
    parameters: dict = field(default_factory=dict)
    applicability: object = None
    applicability_description: str = "ALWAYS"


@dataclass
class DecoderExecutor:
    decoder_id: str
    decode: object
    version: str = "UNKNOWN"
    options: dict = field(default_factory=dict)
    available: bool = True
    unavailable_reason: str = ""


class StrategyExecutorRegistry:
    def __init__(self):
        self._items = {}

    def register(self, strategy_id, transform, version="1", parameters=None, applicability=None,
                 applicability_description=None, replace=False):
        if not callable(transform):
            raise TypeError("strategy transform must be callable")
        if strategy_id in self._items and not replace:
            raise ValueError(f"strategy executor already registered: {strategy_id}")
        self._items[strategy_id] = StrategyExecutor(
            strategy_id, transform, str(version), dict(parameters or {}), applicability,
            str(applicability_description or (
                getattr(applicability, "__qualname__", "CUSTOM_CONDITION") if applicability else "ALWAYS"
            )),
        )

    def get(self, strategy_id):
        return self._items.get(strategy_id)

    def ids(self):
        return list(self._items)


class DecoderExecutorRegistry:
    def __init__(self):
        self._items = {}

    def register(self, decoder_id, decode, version="UNKNOWN", options=None,
                 available=True, unavailable_reason="", replace=False):
        if decoder_id in self._items and not replace:
            raise ValueError(f"decoder already registered: {decoder_id}")
        if available and not callable(decode):
            raise TypeError("available decoder must provide a callable")
        self._items[decoder_id] = DecoderExecutor(
            decoder_id, decode, str(version), dict(options or {}),
            bool(available), str(unavailable_reason),
        )

    def get(self, decoder_id):
        return self._items.get(decoder_id)

    def ids(self):
        return list(self._items)


def register_builtin_strategies(registry, cv2):
    registry.register("V01", lambda image, context, parameters: image,
                      version="reference-1", parameters={"operation": "identity"})
    registry.register("V02", lambda image, context, parameters: cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
                      version="reference-1", parameters={"operation": "bgr_to_gray"})
    registry.register("V03", lambda image, context, parameters: cv2.normalize(
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX
    ), version="reference-1", parameters={"operation": "gray_minmax_normalize"})


def register_builtin_decoders(registry, cv2, zxingcpp=None):
    def decode_opencv(image, context, options):
        detector = cv2.QRCodeDetector()
        candidates, texts = 0, []
        try:
            ok, decoded, points, _ = detector.detectAndDecodeMulti(image)
            if points is not None:
                candidates = len(points)
            if ok and decoded:
                texts = [str(value) for value in decoded if value]
        except Exception:
            pass
        if not texts:
            text, points, _ = detector.detectAndDecode(image)
            if points is not None:
                candidates = max(candidates, 1)
            if text:
                texts = [str(text)]
        return {"payloads": texts, "candidate_count": candidates}

    registry.register("opencv", decode_opencv, version=str(getattr(cv2, "__version__", "UNKNOWN")))

    if zxingcpp is not None:
        def decode_zxing(image, context, options):
            results = zxingcpp.read_barcodes(image)
            texts = []
            candidates = 0
            for result in results:
                if "qr" in str(getattr(result, "format", "")).lower():
                    candidates += 1
                    value = getattr(result, "text", "")
                    if value:
                        texts.append(str(value))
            return {"payloads": texts, "candidate_count": candidates}
        registry.register("zxingcpp", decode_zxing,
                          version=str(getattr(zxingcpp, "__version__", "VERSION_NOT_EXPOSED")))
    else:
        registry.register("zxingcpp", None, version="UNAVAILABLE", available=False,
                          unavailable_reason="DECODER_UNAVAILABLE: zxingcpp is not installed")


def load_adapter_modules(specs, strategy_registry, decoder_registry, context):
    loaded = []
    for spec in specs or []:
        module = importlib.import_module(spec)
        register = getattr(module, "register_qr_audit", None)
        if not callable(register):
            raise ValueError(f"adapter module {spec} must define register_qr_audit(strategies, decoders, context)")
        register(strategy_registry, decoder_registry, context)
        loaded.append(module)
    return loaded
