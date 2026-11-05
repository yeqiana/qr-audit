"""Bounded AI-detector QR recovery primitives; does not synthesize QR payloads.

The detector returns boxes/polygons; actual text comes from independent
barcode decoders. All routines operate in-memory, offline, and with caps.
"""
import math
import time
from collections import Counter

MAX_VARIANT_PIXELS = 8_000_000


def _bounded(image, cv2, max_pixels=MAX_VARIANT_PIXELS):
    height, width = image.shape[:2]
    if not height or not width:
        raise ValueError("EMPTY_QR_IMAGE")
    if height * width <= max_pixels:
        return image
    factor = math.sqrt(max_pixels / (height * width)) * 0.98
    new_size = (max(1, int(width * factor)), max(1, int(height * factor)))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)


def _rectified(image, polygon, cv2, np):
    """Warp a quadrilateral; detector order is normalized using sums/diffs."""
    if polygon is None:
        return None
    points = np.asarray(polygon, dtype=np.float32).reshape(-1, 2)
    if len(points) < 4 or not np.all(np.isfinite(points)):
        return None
    if len(points) > 4:
        hull = cv2.convexHull(points).reshape(-1, 2)
        perimeter = cv2.arcLength(hull, True)
        approx = cv2.approxPolyDP(hull, .03 * perimeter, True).reshape(-1, 2)
        if len(approx) != 4:
            return None
        points = approx
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).reshape(-1)
    ordered = np.array([points[sums.argmin()], points[diffs.argmin()],
                        points[sums.argmax()], points[diffs.argmax()]], dtype=np.float32)
    if len({tuple(p) for p in ordered}) != 4:
        return None
    edge = max(float(np.linalg.norm(ordered[i] - ordered[(i+1) % 4]))
               for i in range(4))
    side = min(2048, max(48, int(math.ceil(edge))))
    dst = np.array([[0, 0], [side-1, 0], [side-1, side-1], [0, side-1]],
                   dtype=np.float32)
    warp = cv2.warpPerspective(
        image, cv2.getPerspectiveTransform(ordered, dst), (side, side),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255),
    )
    return warp


def _crop(image, bbox, cv2, pad_fraction=.12):
    height, width = image.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox]
    if not all(math.isfinite(x) for x in (x1, y1, x2, y2)):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    pad = max(8, int(max(x2-x1, y2-y1) * pad_fraction))
    ix1, iy1 = max(0, int(math.floor(x1))-pad), max(0, int(math.floor(y1))-pad)
    ix2, iy2 = min(width, int(math.ceil(x2))+pad), min(height, int(math.ceil(y2))+pad)
    if ix2-ix1 < 8 or iy2-iy1 < 8:
        return None
    return _bounded(image[iy1:iy2, ix1:ix2].copy(), cv2)


def _quiet(image, cv2, quiet=16):
    # The border itself consumes pixels; bound the complete result.
    height, width = image.shape[:2]
    if (height+2*quiet)*(width+2*quiet) > MAX_VARIANT_PIXELS:
        scale = min(1.0, .97 * math.sqrt(
            MAX_VARIANT_PIXELS / ((height+2*quiet)*(width+2*quiet))
        ))
        scaled = (max(1,int(width*scale)), max(1,int(height*scale)))
        image = cv2.resize(image, scaled, interpolation=cv2.INTER_AREA)
    while (image.shape[0]+2*quiet)*(image.shape[1]+2*quiet) > MAX_VARIANT_PIXELS:
        new_size=(max(1,int(image.shape[1]*.95)),
                  max(1,int(image.shape[0]*.95)))
        if new_size==(image.shape[1],image.shape[0]):
            raise ValueError("AI_QUIET_ZONE_PIXEL_BUDGET")
        image=cv2.resize(image,new_size,interpolation=cv2.INTER_AREA)
    return cv2.copyMakeBorder(image, quiet, quiet, quiet, quiet,
                             borderType=cv2.BORDER_CONSTANT, value=(255,255,255))


def image_variants(image, cv2, np, use_grid=True, grid_versions=7):
    """Named variants, no copies of original images are written to disk."""
    base = _bounded(image, cv2)
    yield "crop", base, False
    yield "quiet_zone", _quiet(base, cv2), False
    gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY) if base.ndim == 3 else base
    if gray.size * 4 <= MAX_VARIANT_PIXELS:
        scaled = cv2.resize(gray, (gray.shape[1]*2, gray.shape[0]*2),
                            interpolation=cv2.INTER_NEAREST)
        yield "nearest2x", _quiet(scaled, cv2), False
    clahe = cv2.createCLAHE(clipLimit=2, tileGridSize=(4,4)).apply(gray)
    yield "clahe", _quiet(clahe, cv2), False
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield "otsu", _quiet(otsu, cv2), True
    if use_grid and 50 <= min(gray.shape[:2]) <= 2048:
        for matrix_name, matrix in module_grids(gray, cv2, np, max_versions=grid_versions):
            yield matrix_name, matrix, True


def module_grids(gray, cv2, np, max_versions=7):
    """Hypothesis search over QR module counts; every hypothesis must decode.

    No content completion/guessing. Sampling an incorrect grid produces a
    checksum failure and must never be accepted as an AI-generated payload.
    """
    for version in range(1, max_versions+1):
        count = 17 + 4*version
        # Resampling across the entire rectified QR patch is a hypothesis,
        # not an attestation of the original QR version.
        samples = cv2.resize(gray, (count, count), interpolation=cv2.INTER_AREA)
        for threshold_name, threshold in (("otsu", cv2.threshold(
                samples, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]),
                ("median", float(np.median(samples)))):
            modules = np.where(samples > threshold, 255, 0).astype(np.uint8)
            padded = cv2.copyMakeBorder(modules, 4,4,4,4,cv2.BORDER_CONSTANT,value=255)
            rendered = cv2.resize(padded,
                                  ((count+8)*8,(count+8)*8),
                                  interpolation=cv2.INTER_NEAREST)
            yield f"grid_v{version}_{threshold_name}", rendered


def normalize_boxes(result, height, width, max_candidates):
    """Accept a deterministic small detection contract from injected backend."""
    boxes = []
    for item in result or []:
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox")
        if bbox is None or len(bbox) != 4:
            continue
        try:
            x1,y1,x2,y2 = [float(x) for x in bbox]
            confidence = float(item.get("confidence",1.))
        except (TypeError,ValueError):
            continue
        if not all(math.isfinite(x) for x in (x1,y1,x2,y2,confidence)):
            continue
        bbox = [max(0,min(width,x1)), max(0,min(height,y1)),
                max(0,min(width,x2)), max(0,min(height,y2))]
        if bbox[2]-bbox[0]<8 or bbox[3]-bbox[1]<8:
            continue
        boxes.append({"bbox":bbox,"confidence":confidence,
                      "polygon":item.get("polygon")})
    boxes.sort(key=lambda x:-x["confidence"])
    dedup=[]
    for item in boxes:
        x1,y1,x2,y2=item["bbox"]
        area=(x2-x1)*(y2-y1)
        repeated=False
        for earlier in dedup:
            a,b,c,d=earlier["bbox"]
            inter=max(0,min(c,x2)-max(a,x1))*max(0,min(d,y2)-max(b,y1))
            union=area+(c-a)*(d-b)-inter
            if union>0 and inter/union>.85:
                repeated=True
                break
        if not repeated:
            dedup.append(item)
        if len(dedup)>=max_candidates:
            break
    return dedup


def _decode_cv(image, cv2):
    detector=cv2.QRCodeDetector()
    values=[]
    try:
        ok,texts,_,_=detector.detectAndDecodeMulti(image)
        if ok:
            values.extend(x for x in texts if x)
    except cv2.error:
        pass
    if not values:
        try:
            text,_,_=detector.detectAndDecode(image)
            if text:
                values.append(text)
        except cv2.error:
            pass
    return values


def _decode_zxing(image, zxing, pure=False):
    if zxing is None:
        return []
    try:
        kwargs={"is_pure":bool(pure)}
        if hasattr(zxing,"BarcodeFormat"):
            kwargs["formats"]=zxing.BarcodeFormat.QRCode
        if hasattr(zxing,"TextMode"):
            kwargs["text_mode"]=zxing.TextMode.Plain
        results=zxing.read_barcodes(image,**kwargs)
        return [value.text for value in results
                if getattr(value,"text",None) and "qr" in str(
                    getattr(value,"format","")).lower()]
    except (TypeError,ValueError,RuntimeError,AttributeError):
        return []


def _decode_zbar(image, decode_zbar):
    if decode_zbar is None:
        return []
    try:
        values=[]
        for item in decode_zbar(image):
            if "QR" not in str(getattr(item,"type","")).upper():
                continue
            payload=getattr(item,"data",b"")
            if payload:
                try:
                    values.append(payload.decode("utf-8"))
                except UnicodeDecodeError:
                    # Do not accept lossy replacements as truth.
                    continue
        return values
    except (RuntimeError,ValueError,TypeError):
        return []


def recover(image, detections, cv2, np, zxing=None, zbar=None,
            super_resolve=None, max_candidates=8, max_attempts=180,
            grid_versions=7, budget_seconds=30):
    """Recover using detected candidates, never a generative text output."""
    start=time.monotonic()
    boxes=normalize_boxes(detections,*image.shape[:2],max_candidates)
    payloads=[]
    counts=Counter()
    attempts=0
    for detection in boxes:
        crop=_crop(image,detection["bbox"],cv2)
        if crop is None:
            continue
        candidates=[("roi",crop)]
        warp=_rectified(image,detection.get("polygon"),cv2,np)
        if warp is not None:
            candidates.insert(0,("warped",warp))
        if super_resolve is not None:
            # SR is a plugin whose output is an image, never QR text.
            try:
                improved=super_resolve(crop)
                if improved is not None:
                    candidates.append(("ai_sr",_bounded(improved,cv2)))
            except (RuntimeError,ValueError,TypeError):
                counts["sr_error"]+=1
        for origin, source in candidates:
            grid_ok = (origin=="warped" or
                       abs(source.shape[0]-source.shape[1]) <
                       .20*max(source.shape[:2]))
            for variant,processed,pure in image_variants(
                    source,cv2,np,use_grid=grid_ok,grid_versions=grid_versions):
                if attempts>=max_attempts or time.monotonic()-start>budget_seconds:
                    counts["budget_exhausted"]+=1
                    break
                attempts+=1
                # OpenCV / ZXing / ZBar have independent implementations.
                for engine, values in (
                    ("opencv",_decode_cv(processed,cv2)),
                    ("zxing",_decode_zxing(processed,zxing,pure=pure)),
                    ("zbar",_decode_zbar(processed,zbar)),
                ):
                    for text in values:
                        if text and text not in payloads:
                            payloads.append(text)
                        if text:
                            counts[engine]+=1
                if payloads:
                    # An image may contain several QR symbols; we keep scanning
                    # other *detections*, but stop transform variants for this one.
                    break
            if payloads:
                break
    return {"payloads":payloads,"candidate_count":len(boxes),
            "ai_detector_candidates":len(boxes),"ai_decode_calls":attempts,
            "ai_engine_hits":dict(counts)}
