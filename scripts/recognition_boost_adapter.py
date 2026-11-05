"""Opt-in QR recognition experiments, separate from original V01-V28.

This module provides reference OpenCV preprocessing only. It does not
claim equivalent implementation of any native scanner Vxx strategy.
"""

import math

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
    """Use the largest safe 4/3/2/1 enlargement; cap full-frame memory.

    For a frame already over the 8M budget, conservatively downsample with
    INTER_AREA instead of failing every brightness strategy. ROI extraction
    remains the preferred path for tiny QR modules in large photographs.
    """
    height, width = gray.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("empty image")
    scale = next((factor for factor in (4, 3, 2, 1)
                  if (height * factor + 2 * BORDER_PIXELS) *
                     (width * factor + 2 * BORDER_PIXELS) <= MAX_OUTPUT_PIXELS), None)
    if scale is None:
        # Preserve aspect ratio; max-edge bound is deliberately conservative.
        factor = min(1.0, (math.sqrt(MAX_OUTPUT_PIXELS) - 2 * BORDER_PIXELS) /
                     max(height, width))
        new_width = max(1, int(width * factor))
        new_height = max(1, int(height * factor))
        if ((new_height + 2 * BORDER_PIXELS) *
                (new_width + 2 * BORDER_PIXELS) > MAX_OUTPUT_PIXELS):
            raise ValueError("BOOST_OUTPUT_EXCEEDS_PIXEL_LIMIT")
        gray = cv2.resize(gray, (new_width, new_height), interpolation=cv2.INTER_AREA)
        height, width, scale = new_height, new_width, 1
    enlarged = (gray if scale == 1 else cv2.resize(
        gray, (width * scale, height * scale), interpolation=cv2.INTER_NEAREST,
    ))
    return cv2.copyMakeBorder(
        enlarged, BORDER_PIXELS, BORDER_PIXELS,
        BORDER_PIXELS, BORDER_PIXELS,
        borderType=cv2.BORDER_CONSTANT, value=255,
    )


def _rectify_roi(gray, cv2, np):
    """Locate QR quadrilateral, warp largest candidate and restore quiet zone.

    Detector failure falls back to bounded full-frame processing rather than
    producing an unbounded allocation or claiming a successful QR detection.
    """
    detector = cv2.QRCodeDetector()
    candidates = []
    try:
        found, points = detector.detectMulti(gray)
        if found and points is not None:
            candidates.extend(points)
    except (cv2.error, AttributeError):
        pass
    if not candidates:
        try:
            found, points = detector.detect(gray)
            if found and points is not None:
                candidates.extend(points)
        except (cv2.error, AttributeError):
            pass
    selected, greatest = None, 0.0
    for candidate in candidates:
        quad = np.asarray(candidate, dtype=np.float32).reshape(-1, 2)
        if quad.shape != (4, 2) or not np.all(np.isfinite(quad)):
            continue
        area = abs(float(cv2.contourArea(quad)))
        if area > greatest:
            selected, greatest = quad, area
    if selected is None or greatest < 16:
        return _pad_upscale(gray, cv2)
    a, b, c, d = selected
    edge = max(float(np.linalg.norm(a - b)), float(np.linalg.norm(b - c)),
               float(np.linalg.norm(c - d)), float(np.linalg.norm(d - a)))
    if not math.isfinite(edge) or edge < 4:
        return _pad_upscale(gray, cv2)
    side = max(16, min(2048, int(math.ceil(edge))))
    destination = np.array(
        [[0, 0], [side - 1, 0], [side - 1, side - 1], [0, side - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(selected, destination)
    warped = cv2.warpPerspective(
        gray, matrix, (side, side), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=255,
    )
    # 1/6-side quiet zone is intentionally applied after rectification;
    # upscaling interpolated QR modules again can destroy a readable code.
    quiet = max(16, side // 6)
    return cv2.copyMakeBorder(
        warped, quiet, quiet, quiet, quiet,
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
    elif variant == "rectify_roi":
        return _rectify_roi(gray, cv2, context["numpy"])
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
        ("B09", "rectify_roi"),
    ):
        strategies.register(
            strategy_id,
            lambda image, ctx, params, selected=variant: _enhance(
                image, ctx, selected
            ),
            version="reference-boost-3",
            parameters={
                "operation": variant, "preferred_scale": UPSCALE,
                "adaptive_scale": True, "white_border_pixels": BORDER_PIXELS,
                "max_output_pixels": MAX_OUTPUT_PIXELS,
            },
        )
