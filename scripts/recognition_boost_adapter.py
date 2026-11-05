"""Opt-in QR recognition experiments, separate from original V01-V28.

This module provides reference OpenCV preprocessing only. It does not
claim equivalent implementation of any native scanner Vxx strategy.
"""

MAX_OUTPUT_PIXELS = 8_000_000
UPSCALE = 4
BORDER_PIXELS = 16


def _gray(image, cv2):
    if image.ndim == 2:
        return image
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    raise ValueError("unsupported image shape for QR recognition boost")


def _pad_upscale(gray, cv2):
    height, width = gray.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("empty image")
    out_height = height * UPSCALE + BORDER_PIXELS * 2
    out_width = width * UPSCALE + BORDER_PIXELS * 2
    if out_height * out_width > MAX_OUTPUT_PIXELS:
        raise ValueError("BOOST_OUTPUT_EXCEEDS_PIXEL_LIMIT")
    enlarged = cv2.resize(
        gray, (width * UPSCALE, height * UPSCALE),
        interpolation=cv2.INTER_NEAREST,
    )
    return cv2.copyMakeBorder(
        enlarged, BORDER_PIXELS, BORDER_PIXELS,
        BORDER_PIXELS, BORDER_PIXELS,
        borderType=cv2.BORDER_CONSTANT, value=255,
    )


def _enhance(image, context, variant):
    cv2 = context["cv2"]
    gray = _gray(image, cv2)
    if variant == "quiet_zone":
        processed = gray
    elif variant == "otsu":
        _, processed = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
    elif variant == "clahe_otsu":
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        contrast = clahe.apply(gray)
        _, processed = cv2.threshold(
            contrast, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
    elif variant == "adaptive":
        processed = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2,
        )
    elif variant == "gamma":
        # Deterministic exposure branch; preserve the original image in B01.
        np = context["numpy"]
        median = float(np.median(gray))
        gamma = 0.65 if median < 95 else 1.6 if median > 180 else 0.9
        lut = np.array([
            round(255.0 * ((i / 255.0) ** gamma)) for i in range(256)
        ], dtype=np.uint8)
        processed = cv2.LUT(gray, lut)
    elif variant == "sauvola":
        # Use bounded local statistics rather than requiring opencv-contrib.
        np = context["numpy"]
        source = gray.astype(np.float32)
        mean = cv2.boxFilter(source, -1, (15, 15))
        squared = cv2.boxFilter(source * source, -1, (15, 15))
        deviation = np.sqrt(np.maximum(squared - mean * mean, 0))
        threshold = mean * (1 + 0.34 * (deviation / 128 - 1))
        processed = np.where(source > threshold, 255, 0).astype(np.uint8)
    elif variant == "flatfield":
        # Normalize slow brightness gradients before binary conversion.
        np = context["numpy"]
        background = cv2.GaussianBlur(gray, (31, 31), 0)
        normalized = cv2.divide(gray, np.maximum(background, 1), scale=128)
        _, processed = cv2.threshold(
            normalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
    else:
        raise ValueError("unknown recognition boost variant")
    return _pad_upscale(processed, cv2)


def register_qr_audit(strategies, decoders, context):
    """Only Bxx experiment IDs; no native Vxx registration or replacement."""
    if context.get("cv2") is None or context.get("numpy") is None:
        raise RuntimeError(
            "BOOST_REQUIRES_CV2_NUMPY: use existing local OpenCV and NumPy"
        )
    strategies.register(
        "B01", lambda image, ctx, params: image,
        version="reference-boost-1", parameters={"operation": "identity"},
    )
    for strategy_id, variant in (
        ("B02", "quiet_zone"), ("B03", "otsu"),
        ("B04", "clahe_otsu"), ("B05", "adaptive"),
        ("B06", "gamma"), ("B07", "sauvola"), ("B08", "flatfield"),
    ):
        strategies.register(
            strategy_id,
            lambda image, ctx, params, selected=variant: _enhance(
                image, ctx, selected
            ),
            version="reference-boost-2",
            parameters={
                "operation": variant, "scale": UPSCALE,
                "white_border_pixels": BORDER_PIXELS,
                "max_output_pixels": MAX_OUTPUT_PIXELS,
            },
        )
