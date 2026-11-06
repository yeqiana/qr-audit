"""Optional inverse-resampling of strictly detected nearest-neighbor QR enlargements.

Never reads/guesses payload text. Supported only for near-square QR v2 images
with exactly four-module quiet zone and an integer module pitch. If the image
is not an exact nearest-neighbor enlargement, return None without guessing.
"""
from __future__ import annotations


def _source_samples(image, cv2, np, min_factor=.16, max_factor=.55):
    height, width = image.shape
    if width != height or not 99 <= width <= 600:
        return None
    if width % 33:
        return None
    begin = max(18, int(width * min_factor))
    end = min(120, int(width * max_factor))
    for size in range(begin, end + 1):
        # OpenCV's INTER_NEAREST maps each large pixel back by floor(x*n/N).
        # Choose the middle pixel of each repeated source patch, not cv2's
        # naive reverse nearest resize (which is not the inverse operation).
        indexes = np.floor((np.arange(size) + .5) * width / size).astype(np.int32)
        small = image[np.ix_(indexes, indexes)]
        reprojection = cv2.resize(
            small, (width, height), interpolation=cv2.INTER_NEAREST,
        )
        if np.array_equal(reprojection, image):
            if float(small.std()) < 20.0:
                return None
            return small
    return None


def _area_weights(out_size, module_count, np):
    original_width = module_count
    weights = np.zeros((out_size,module_count), dtype=np.float64)
    for pixel in range(out_size):
        start, end = pixel*original_width/out_size, (pixel+1)*original_width/out_size
        for module in range(module_count):
            overlap = max(0.0, min(end,module+1)-max(start,module))
            weights[pixel,module]=overlap / (end-start)
    return weights


def invert_nearest_modules(image,cv2,np,expected,pattern_score,
                           max_iterations=160):
    """Return (25x25 black=1 grid, diagnostics) or None.

    An independent QR decoder must validate the returned modules. The
    numeric inverse is not treated as an RS-validated QR on its own.
    """
    if expected.shape != (25,25) or pattern_score < .80:
        return None
    if image.ndim == 3:
        image = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    if image.ndim != 2 or image.dtype != np.uint8:
        return None
    small = _source_samples(image,cv2,np)
    if small is None:
        return None
    try:
        from scipy.optimize import minimize
    except ImportError:
        return None
    size=33
    fixed=np.zeros((size,size),dtype=bool)
    fixed[:4,:]=True
    fixed[-4:,:]=True
    fixed[:,:4]=True
    fixed[:,-4:]=True
    functions=expected>=0
    fixed[4:-4,4:-4]=functions
    base=np.zeros((size,size),dtype=np.float64)
    base[4:-4,4:-4][functions]=expected[functions]
    variable=~fixed
    observed=(255.0-small.astype(np.float64))/255.0
    weights=_area_weights(small.shape[0],size,np)
    def objective(x):
        module=base.copy()
        module[variable]=x
        residual=weights@module@weights.T-observed
        loss=0.5*float(np.square(residual).sum())
        gradient=weights.T@residual@weights
        return loss,gradient[variable]
    init=np.full(int(variable.sum()),.5,dtype=np.float64)
    result=minimize(
        objective,init,method="L-BFGS-B",jac=True,
        bounds=[(0.0,1.0)] * len(init),
        options={"maxiter":max_iterations, "ftol":1e-10},
    )
    if not np.isfinite(result.fun) or result.fun > .001*small.size:
        return None
    solution=base.copy()
    solution[variable]=result.x
    grid=(solution[4:-4,4:-4] >= .5).astype(np.uint8)
    return {
        "grid":grid,
        "source_resolution":int(small.shape[0]),
        "reconstruction_loss":float(result.fun),
        "method":"nearest-neighbor-forward-model",
    }
