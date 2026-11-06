"""Experimental QR module-grid recovery with decoder-verified payloads only.

This module estimates QR version, module pitch and grid phase from visible
function patterns. Missing modules remain erasures until render time; function
patterns may be restored from the QR specification. A barcode decoder, not
this module, is the only source of payload text.
"""
from __future__ import annotations

ALIGNMENT_CENTERS = {
    1: (),
    2: (6, 18),
    3: (6, 22),
    4: (6, 26),
    5: (6, 30),
    6: (6, 34),
    7: (6, 22, 38),
    8: (6, 24, 42),
    9: (6, 26, 46),
    10: (6, 28, 50),
}


def function_pattern(version, np):
    """Return expected function modules; -1 denotes data/format cells."""
    if not isinstance(version, int) or not 1 <= version <= 10:
        raise ValueError("QR_VERSION_OUT_OF_EXPERIMENTAL_RANGE")
    size = 17 + 4 * version
    expected = np.full((size, size), -1, dtype=np.int8)

    def put(row, col, value):
        if 0 <= row < size and 0 <= col < size:
            expected[row, col] = value

    # Finder patterns and their one-module white separators.
    for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
        for dy in range(-1, 8):
            for dx in range(-1, 8):
                row, col = top + dy, left + dx
                if not (0 <= row < size and 0 <= col < size):
                    continue
                if 0 <= dy <= 6 and 0 <= dx <= 6:
                    black = (
                        dy in (0, 6) or dx in (0, 6)
                        or (2 <= dy <= 4 and 2 <= dx <= 4)
                    )
                    put(row, col, 1 if black else 0)
                else:
                    put(row, col, 0)

    # Timing patterns, alternating black/white from module 8.
    for pos in range(8, size - 8):
        value = 1 if pos % 2 == 0 else 0
        put(6, pos, value)
        put(pos, 6, value)

    # Alignment patterns (skip the three finder-pattern corners).
    centers = ALIGNMENT_CENTERS[version]
    for cy in centers:
        for cx in centers:
            if ((cy <= 8 and cx <= 8)
                or (cy <= 8 and cx >= size - 9)
                or (cy >= size - 9 and cx <= 8)):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    ring = max(abs(dx), abs(dy))
                    put(cy + dy, cx + dx, 1 if ring in (0, 2) else 0)

    # Fixed dark module.
    put(size - 8, 8, 1)
    return expected


def _gray(image, cv2):
    if image is None:
        raise ValueError("EMPTY_QR_IMAGE")
    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if image.ndim != 2:
        raise ValueError("QR_IMAGE_CHANNELS_UNSUPPORTED")
    return image


def _candidate(gray, expected, version, pitch, dx, dy, rotation, threshold, cv2, np):
    size = expected.shape[0]
    height, width = gray.shape
    xs = ((width - size * pitch) / 2.0 + pitch / 2.0
          + dx + np.arange(size, dtype=np.float32) * pitch)
    ys = ((height - size * pitch) / 2.0 + pitch / 2.0
          + dy + np.arange(size, dtype=np.float32) * pitch)
    map_x = np.broadcast_to(xs[None, :], (size, size)).astype(np.float32)
    map_y = np.broadcast_to(ys[:, None], (size, size)).astype(np.float32)
    values = cv2.remap(
        gray, map_x, map_y, interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=255,
    )
    valid_x = (xs >= 0) & (xs <= width - 1)
    valid_y = (ys >= 0) & (ys <= height - 1)
    valid = valid_y[:, None] & valid_x[None, :]
    known = expected >= 0
    scored = known & valid
    count = int(scored.sum())
    total = int(known.sum())
    if count < max(24, int(total * .28)):
        return None
    observed = values <= threshold
    accuracy = float((observed[scored] == (expected[scored] == 1)).mean())
    coverage = count / max(1, total)
    midpoint = (float(threshold) + 255.0) / 2.0
    contrast = float(np.abs(values[scored].astype(np.float32) - midpoint).mean() / 127.5)
    score = accuracy * (0.85 + 0.15 * min(1.0, contrast)) * min(1.0, coverage / .62)
    return {
        "version": version, "modules": size, "pitch": float(pitch),
        "dx": float(dx), "dy": float(dy), "rotation": rotation,
        "threshold": float(threshold), "score": float(score),
        "pattern_accuracy": accuracy, "coverage": float(coverage),
        "values": values, "valid": valid, "expected": expected,
    }


def sample_candidates(image, cv2, np, max_version=10, top_k=32):
    """Bounded centered-grid search ranked by QR function-pattern evidence."""
    gray = _gray(image, cv2)
    if gray.dtype != np.uint8 or gray.shape[0] * gray.shape[1] > 8_000_000:
        raise ValueError("MODULE_GRID_INPUT_OUT_OF_BOUNDS")
    if min(gray.shape) < 24:
        return []
    threshold = float(cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[0])
    candidates = []
    shifts = (-1.5, 0.0, 1.5)
    for rotation in range(4):
        view = np.ascontiguousarray(np.rot90(gray, rotation))
        height, width = view.shape
        for version in range(1, max_version + 1):
            size = 17 + 4 * version
            ratio = min(height, width) / size
            low = max(.65, ratio * .70)
            high = min(20.0, ratio * 1.32)
            step = max(.12, ratio * .04)
            pitch_values = np.arange(low, high + step * .25, step)
            expected = function_pattern(version, np)
            for pitch in pitch_values:
                for dx in shifts:
                    for dy in shifts:
                        item = _candidate(
                            view, expected, version, float(pitch), dx, dy,
                            rotation, threshold, cv2, np,
                        )
                        if item is not None:
                            candidates.append(item)
    candidates.sort(key=lambda x: (x["score"], x["coverage"]), reverse=True)
    # Keep diverse hypotheses: nearby pitch/phase variants are redundant.
    selected = []
    seen = set()
    for item in candidates:
        key = (item["version"], item["rotation"], round(item["pitch"], 1),
               round(item["dx"]), round(item["dy"]))
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= top_k:
            break
    return selected


def render_candidate(candidate, cv2, np, fill=255, scale=8, quiet=4):
    """Render one sampled grid; never fills data from a text/payload guess."""
    values = candidate["values"]
    valid = candidate["valid"]
    threshold = candidate["threshold"]
    expected = candidate["expected"]
    grid = np.where(values <= threshold, 0, 255).astype(np.uint8)
    grid[~valid] = 0 if fill == 0 else 255
    known = expected >= 0
    grid[known] = np.where(expected[known] == 1, 0, 255).astype(np.uint8)
    grid = cv2.copyMakeBorder(
        grid, quiet, quiet, quiet, quiet,
        cv2.BORDER_CONSTANT, value=255,
    )
    return cv2.resize(
        grid, ((grid.shape[1]) * scale, (grid.shape[0]) * scale),
        interpolation=cv2.INTER_NEAREST,
    )


def _decode(image, cv2, zxing):
    hits = []
    if zxing is not None:
        try:
            options = {}
            if hasattr(zxing, "BarcodeFormat"):
                options["formats"] = zxing.BarcodeFormat.QRCode
            if hasattr(zxing, "TextMode"):
                options["text_mode"] = zxing.TextMode.Plain
            results = zxing.read_barcodes(image, **options)
            hits.extend(str(x.text) for x in results if getattr(x, "text", None))
        except (RuntimeError, ValueError, TypeError, AttributeError):
            pass
    try:
        text, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
        if text:
            hits.append(str(text))
    except cv2.error:
        pass
    return list(dict.fromkeys(hits))


def decode_candidates(candidates, cv2, np, zxing=None, max_decode=48):
    """Try ranked grids; only independent decoder outputs count as hits."""
    attempts = 0
    for item in candidates:
        for fill in (255, 0):
            if attempts >= max_decode:
                return [], attempts
            rendered = render_candidate(item, cv2, np, fill=fill)
            attempts += 1
            hits = _decode(rendered, cv2, zxing)
            if hits:
                return [{
                    "payload": value,
                    "version": item["version"],
                    "pitch": item["pitch"],
                    "rotation": item["rotation"],
                    "score": item["score"],
                    "fill": fill,
                    "pattern_accuracy": item["pattern_accuracy"],
                    "coverage": item["coverage"],
                } for value in hits], attempts
    return [], attempts


def fuse_candidates(left, right, cv2, np, max_pairs=576):
    """Fuse pixel-derived module confidence, never payload strings."""
    fused = []
    checked = 0
    for a in left:
        for b in right:
            if a["version"] != b["version"] or a["rotation"] != b["rotation"]:
                continue
            checked += 1
            if checked > max_pairs:
                return fused
            common = a["valid"] & b["valid"]
            union = a["valid"] | b["valid"]
            if int(common.sum()) < max(32, int(common.size * .20)):
                continue
            midpoint_a = (a["threshold"] + 255.0) / 2.0
            midpoint_b = (b["threshold"] + 255.0) / 2.0
            pa = np.clip(0.5 + (midpoint_a - a["values"].astype(np.float32)) / 255.0,
                         0.0, 1.0)
            pb = np.clip(0.5 + (midpoint_b - b["values"].astype(np.float32)) / 255.0,
                         0.0, 1.0)
            ba = pa[common] >= .5
            bb = pb[common] >= .5
            agreement = float((ba == bb).mean())
            if agreement < .72:
                continue
            wa = np.abs(a["values"].astype(np.float32) - midpoint_a) + 8.0
            wb = np.abs(b["values"].astype(np.float32) - midpoint_b) + 8.0
            prob = np.full(a["values"].shape, np.nan, dtype=np.float32)
            only_a = a["valid"] & ~b["valid"]
            only_b = b["valid"] & ~a["valid"]
            prob[only_a] = pa[only_a]
            prob[only_b] = pb[only_b]
            both = a["valid"] & b["valid"]
            prob[both] = ((pa[both] * wa[both] + pb[both] * wb[both])
                          / (wa[both] + wb[both]))
            values = np.where(np.isfinite(prob), 255.0 * (1.0 - prob), 255.0)
            candidate = {
                "version": a["version"], "modules": a["modules"],
                "pitch": (a["pitch"] + b["pitch"]) / 2.0,
                "dx": 0.0, "dy": 0.0, "rotation": a["rotation"],
                "threshold": 127.5, "score": min(a["score"], b["score"]),
                "pattern_accuracy": min(a["pattern_accuracy"], b["pattern_accuracy"]),
                "coverage": float(union.sum() / union.size),
                "values": values.astype(np.uint8), "valid": union,
                "expected": a["expected"], "pair_agreement": agreement,
            }
            fused.append(candidate)
    fused.sort(key=lambda x: (x["pair_agreement"], x["score"]), reverse=True)
    return fused


def recover_image(image, cv2, np, zxing=None, max_version=10,
                  top_k=32, max_decode=48,
                  enable_rs_erasures=False, enable_inverse_resample=False,
                  max_extra_decode=12):
    """Single-image QR recovery; strictly decoder-verified, with bounded extras.

    No text is supplied or inferred from another image. The optional erasure
    path repairs missing QR v2-M codewords with RS parity, then a real barcode
    decoder must decode the reconstituted QR image. Inverse resampling is a
    separate, strict opt-in for exact NN enlargements.
    """
    candidates = sample_candidates(image, cv2, np, max_version, top_k)
    hits, attempts = decode_candidates(candidates, cv2, np, zxing, max_decode)
    method = "grid" if hits else None
    extra_calls=0
    details={}
    if not hits and enable_rs_erasures:
        from qr_erasure_recovery import recover_erasure_grid, render_grid
        for item in candidates:
            if extra_calls >= max_extra_decode:
                break
            if item["version"] != 2:
                continue
            repaired = recover_erasure_grid(item, np)
            if repaired is None:
                continue
            rendered = render_grid(repaired["grid"], cv2, np)
            extra_calls += 1
            payloads = _decode(rendered, cv2, zxing)
            if payloads:
                hits = [{ "payload": value, "version": 2,
                          "method": "rs_erasure_v2m",
                          "erased_codewords": repaired["erased_codewords"],
                          "format_errors": repaired["format_errors"] }
                        for value in payloads]
                method = "rs_erasure_v2m"
                details["rs_erasure_codewords"] = repaired["erased_codewords"]
                break
    if not hits and enable_inverse_resample and extra_calls < max_extra_decode:
        # A solver hit is not a QR hit. Only accept real decoded payloads.
        from qr_inverse_resample import invert_nearest_modules
        from qr_erasure_recovery import render_grid
        best = next((x for x in candidates
                     if x["version"] == 2 and x["score"] >= .80), None)
        if best is not None:
            reconstructed = invert_nearest_modules(
                image,cv2,np,best["expected"],best["score"],
            )
            if reconstructed is not None:
                extra_calls += 1
                rendered = render_grid(reconstructed["grid"], cv2, np)
                payloads = _decode(rendered, cv2, zxing)
                if payloads:
                    hits = [{ "payload": value, "version": 2,
                              "method": "inverse_nearest_v2",
                              "source_resolution":reconstructed["source_resolution"] }
                            for value in payloads]
                    method = "inverse_nearest_v2"
                    details["inverse_source_resolution"] = reconstructed["source_resolution"]
    attempts += extra_calls
    return {
        "hits": hits, "attempts": attempts,
        "extra_decode_calls": extra_calls,
        "recovery_method":method,
        **details,
        "candidate_count": len(candidates),
        "top_candidates": [{
            k: item[k] for k in (
                "version", "pitch", "rotation", "score",
                "pattern_accuracy", "coverage",
            )
        } for item in candidates[:8]],
        "candidates": candidates,
    }


def recover_pair(left_image, right_image, cv2, np, zxing=None,
                 max_version=10, top_k=32, max_decode=48):
    left = sample_candidates(left_image, cv2, np, max_version, top_k)
    right = sample_candidates(right_image, cv2, np, max_version, top_k)
    fused = fuse_candidates(left, right, cv2, np)
    hits, attempts = decode_candidates(fused, cv2, np, zxing, max_decode)
    return {
        "hits": hits, "attempts": attempts,
        "left_candidate_count": len(left), "right_candidate_count": len(right),
        "fused_candidate_count": len(fused),
        "top_fused": [{
            k: item[k] for k in (
                "version", "pitch", "rotation", "score",
                "pattern_accuracy", "coverage", "pair_agreement",
            )
        } for item in fused[:8]],
    }