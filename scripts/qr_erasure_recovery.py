"""Offline bounded QR v2-M Reed–Solomon *erasure-only* recovery.

No payload text is produced here. Only bit locations observed outside the image
may be recovered. The reconstructed symbol MUST be decoded by an independent QR
decoder and independently checked against a labeled test truth.
"""
from __future__ import annotations

TOTAL_CODEWORDS = 44
DATA_CODEWORDS = 28
ECC_CODEWORDS = 16
VERSION = 2

_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_value = 1
for _i in range(255):
    _GF_EXP[_i] = _value
    _GF_LOG[_value] = _i
    _value <<= 1
    if _value & 256:
        _value ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(left, right):
    if not left or not right:
        return 0
    return _GF_EXP[(_GF_LOG[left] + _GF_LOG[right]) % 255]


def _gf_inv(value):
    if not value:
        raise ZeroDivisionError("GF_ZERO_INVERSE")
    return _GF_EXP[255 - _GF_LOG[value]]


def _format_value(error_correction, mask):
    data = (error_correction << 3) | mask
    bits = data << 10
    while bits.bit_length() >= 11:
        bits ^= 0x537 << (bits.bit_length() - 11)
    return ((data << 10) | bits) ^ 0x5412


def _format_positions(size):
    vertical = []
    horizontal = []
    for bit in range(15):
        if bit < 6:
            vertical.append((bit, 8))
        elif bit < 8:
            vertical.append((bit + 1, 8))
        else:
            vertical.append((size - 15 + bit, 8))
        if bit < 8:
            horizontal.append((8, size - bit - 1))
        elif bit == 8:
            horizontal.append((8, 7))
        else:
            horizontal.append((8, 15 - bit - 1))
    return vertical, horizontal


def _format_info(observed, valid):
    """Decode QR BCH format from pixels, not from user-supplied content.

    Restrict to level M (QR EC bits 00) and 8 mask patterns in this experiment.
    Reject ambiguity, >3 distinct disagreeing *known* observations, or too few
    visible format modules.
    """
    size = len(observed)
    locations = _format_positions(size)
    candidates = []
    for mask in range(8):
        bits = _format_value(0, mask)
        mismatch = 0
        visible = 0
        for placement in locations:
            for bit, (row, col) in enumerate(placement):
                if valid[row, col]:
                    visible += 1
                    mismatch += int(bool(observed[row, col]) != bool((bits >> bit) & 1))
        candidates.append((mismatch, -visible, mask, bits))
    candidates.sort()
    best = candidates[0]
    if -best[1] < 18 or best[0] > 3 or (len(candidates) > 1 and candidates[1][0] == best[0]):
        return None
    return {"mask": best[2], "bits": best[3],
            "format_errors": best[0], "format_observations": -best[1]}


def _mask_bit(mask, row, col):
    x = row * col
    if mask == 0: return (row + col) % 2 == 0
    if mask == 1: return row % 2 == 0
    if mask == 2: return col % 3 == 0
    if mask == 3: return (row + col) % 3 == 0
    if mask == 4: return (row // 2 + col // 3) % 2 == 0
    if mask == 5: return (x % 2 + x % 3) == 0
    if mask == 6: return ((x % 2 + x % 3) % 2) == 0
    if mask == 7: return (((row + col) % 2 + x % 3) % 2) == 0
    raise ValueError("QR_MASK_OUT_OF_RANGE")


def _data_locations(size, reserved):
    """ISO/IEC 18004 zigzag, skipping reserved QR function and format cells."""
    results = []
    col = size - 1
    ascend = True
    while col > 0:
        if col == 6:
            col -= 1
        for step in range(size):
            row = size - 1 - step if ascend else step
            for offset in (0, -1):
                c = col + offset
                if not reserved[row, c]:
                    results.append((row, c))
        ascend = not ascend
        col -= 2
    return results


def _syndrome(codewords, exponent):
    total = 0
    for index, value in enumerate(codewords):
        if value:
            total ^= _gf_mul(value, _GF_EXP[(exponent * (len(codewords) - 1 - index)) % 255])
    return total


def correct_erasures(codewords, erased, max_erasures=ECC_CODEWORDS):
    """Recover known *byte erasures* with GF(256) parity equations.

    Fails closed on over-budget erasures, singular equations or nonzero full
    syndromes. Does NOT repair an unknown non-erasure byte error.
    """
    if len(codewords) != TOTAL_CODEWORDS:
        return None
    positions = sorted(set(erased))
    if len(positions) > max_erasures or any(p < 0 or p >= TOTAL_CODEWORDS for p in positions):
        return None
    values = list(codewords)
    for p in positions:
        values[p] = 0
    if not positions:
        return values if all(_syndrome(values, j) == 0 for j in range(ECC_CODEWORDS)) else None
    unknown_count = len(positions)
    augmented = []
    for j in range(unknown_count):
        coefficients = [
            _GF_EXP[(j * (TOTAL_CODEWORDS - 1 - p)) % 255]
            for p in positions
        ]
        coefficients.append(_syndrome(values, j))
        augmented.append(coefficients)
    for c in range(unknown_count):
        pivot = next((r for r in range(c, unknown_count) if augmented[r][c]), None)
        if pivot is None:
            return None
        augmented[c], augmented[pivot] = augmented[pivot], augmented[c]
        inverse = _gf_inv(augmented[c][c])
        augmented[c] = [_gf_mul(item, inverse) for item in augmented[c]]
        for r in range(unknown_count):
            if r != c and augmented[r][c]:
                factor = augmented[r][c]
                augmented[r] = [
                    old ^ _gf_mul(factor, known)
                    for old, known in zip(augmented[r], augmented[c])
                ]
    for p, row in zip(positions, augmented):
        values[p] = row[-1]
    return values if all(_syndrome(values, j) == 0 for j in range(ECC_CODEWORDS)) else None


def recover_erasure_grid(candidate, np):
    """Return verified-RS repaired QR *module grid* and non-payload diagnostics.

    Only QR v2-M single RS block is implemented. No QR text is decoded here.
    """
    if candidate.get("version") != VERSION:
        return None
    expected = candidate["expected"]
    size = 25
    values = candidate["values"]
    valid = candidate["valid"]
    if expected.shape != (size, size) or values.shape != (size, size) or valid.shape != (size, size):
        return None
    observed = values <= float(candidate["threshold"])
    fmt = _format_info(observed, valid)
    if fmt is None:
        return None
    p1, p2 = _format_positions(size)
    reserved = (expected >= 0).copy()
    for row, col in p1 + p2:
        reserved[row, col] = True
    locations = _data_locations(size, reserved)
    if len(locations) < TOTAL_CODEWORDS * 8:
        return None
    erased = set()
    codewords = [0] * TOTAL_CODEWORDS
    for bit_index, (row, col) in enumerate(locations[:TOTAL_CODEWORDS*8]):
        index = bit_index // 8
        if not valid[row, col]:
            erased.add(index)
            continue
        raw = int(bool(observed[row, col]))
        bit = raw ^ int(_mask_bit(fmt["mask"], row, col))
        codewords[index] |= bit << (7 - bit_index % 8)
    recovered = correct_erasures(codewords, erased)
    if recovered is None:
        return None
    grid = np.zeros((size,size),dtype=np.uint8)
    functions = expected >= 0
    grid[functions] = expected[functions]
    for places in (p1,p2):
        for bit, (row,col) in enumerate(places):
            grid[row,col] = (fmt["bits"]>>bit)&1
    grid[size-8,8] = 1
    for bit_index,(row,col) in enumerate(locations):
        value = 0
        if bit_index < TOTAL_CODEWORDS*8:
            value = (recovered[bit_index // 8] >> (7 - bit_index%8)) & 1
        grid[row,col] = value ^ int(_mask_bit(fmt["mask"],row,col))
    return {
        "grid":grid,
        "erased_codewords":len(erased),
        "format_errors":fmt["format_errors"],
        "format_observations":fmt["format_observations"],
        "mask":fmt["mask"],
        "syndromes_verified":True,
    }


def render_grid(grid,cv2,np,scale=8,quiet=4):
    if grid.shape!=(25,25):
        raise ValueError("QR_V2_MODULE_COUNT_REQUIRED")
    if scale<2 or scale>16 or quiet<4 or quiet>8:
        raise ValueError("QR_RENDER_BUDGET")
    gray=np.where(grid.astype(bool),0,255).astype(np.uint8)
    gray=cv2.copyMakeBorder(gray,quiet,quiet,quiet,quiet,
                              cv2.BORDER_CONSTANT,value=255)
    return cv2.resize(gray,(gray.shape[1]*scale,gray.shape[0]*scale),
                      interpolation=cv2.INTER_NEAREST)
