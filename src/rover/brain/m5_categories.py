"""M5: categories of spectra (SPEC 6.14.5): classification, ARI, warm-start k-means update, power-iteration axes of the
SCAN cloud. No random draw except the starting vector of the very first power iteration; never np.linalg, never `@`."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from rover.config import Params
from rover.core.consts import M5_K_MAX
from rover.core.exact import dot_fixed, fsum, isum_py, sum_axis
from rover.core.rng import derive, gauss_ih4

Arr = np.ndarray


def classify(centroids: Arr, spectra: Arr, new_dist: float) -> tuple[Arr, Arr]:
    """(labels (n,) int64, conf (n,) float64). K = 0: (-1, 0.0)."""
    s = np.asarray(spectra, dtype=np.float64).reshape(-1, 16)
    c = np.asarray(centroids, dtype=np.float64).reshape(-1, 16)
    n, K = s.shape[0], c.shape[0]
    if K == 0:
        return np.full(n, -1, dtype=np.int64), np.zeros(n, dtype=np.float64)
    d = np.sqrt(sum_axis((s[:, None, :] - c[None, :, :]) ** 2, 2))           # (n, K)
    lab = np.argmin(d, axis=1)                                 # ties: smallest index
    d1 = d.min(axis=1)
    if K >= 2:
        masked = np.where(np.arange(K)[None, :] == lab[:, None], 1e300, d)
        d2 = masked.min(axis=1)
        conf = np.where(d2 > 0.0, 1.0 - d1 / np.where(d2 > 0.0, d2, 1.0), 0.0)
    else:
        conf = np.maximum(0.0, 1.0 - d1 / float(new_dist))
    return lab, conf


def _c2(v: int) -> int:
    return v * (v - 1) // 2


def ari(a: Arr, b: Arr) -> float:
    """Adjusted Rand index of two integer labellings (>= 0) of the same length; degenerate cases give 1.0."""
    a = np.asarray(a, dtype=np.int64)
    b = np.asarray(b, dtype=np.int64)
    n = int(a.shape[0])
    if n < 2:
        return 1.0
    kb = int(b.max()) + 1
    ka = int(a.max()) + 1
    nij = np.bincount(a * kb + b, minlength=ka * kb).tolist()
    S = isum_py(_c2(int(v)) for v in nij)
    A = isum_py(_c2(int(v)) for v in np.bincount(a, minlength=ka).tolist())
    B = isum_py(_c2(int(v)) for v in np.bincount(b, minlength=kb).tolist())
    N = _c2(n)
    E = A * B / N
    den = 0.5 * (A + B) - E
    if den == 0.0:
        return 1.0
    return float((S - E) / den)


def _sign_fix(a: Arr) -> Arr:
    """The component of largest absolute value (smallest index on ties) is positive."""
    k = int(np.argmax(np.abs(a)))
    return -a if a[k] < 0.0 else a


def power_axes(Cv: Arr, start: Arr, iters: int) -> tuple[Arr, float]:
    """Two principal axes of the 16x16 covariance by power iteration with a fixed operation order.
    Returns (axes (2, 16), explained in [0, 1]); a zero norm during the iteration gives (zeros (2, 16), 0.0)."""
    Cv = np.asarray(Cv, dtype=np.float64)
    st = np.asarray(start, dtype=np.float64).reshape(2, 16)
    zero = (np.zeros((2, 16), dtype=np.float64), 0.0)
    a = st[0].copy()
    for _ in range(int(iters)):
        a = dot_fixed(Cv, a[:, None])[:, 0]
        nrm = math.sqrt(fsum(a * a))
        if not nrm > 0.0:
            return zero
        a = a / nrm
    c = st[1].copy()
    for _ in range(int(iters)):
        c = dot_fixed(Cv, c[:, None])[:, 0]
        c = c - fsum(c * a) * a
        nrm = math.sqrt(fsum(c * c))
        if not nrm > 0.0:
            return zero
        c = c / nrm
    a, c = _sign_fix(a), _sign_fix(c)
    tr = fsum(Cv[np.arange(16), np.arange(16)])
    if not tr > 0.0:
        return zero
    ex = (fsum(a * dot_fixed(Cv, a[:, None])[:, 0]) + fsum(c * dot_fixed(Cv, c[:, None])[:, 0])) / tr
    return np.stack([a, c]), float(min(1.0, max(0.0, ex)))


def project(X: Arr, mean: Arr, axes: Arr) -> Arr:
    """(n, 2) = dot_fixed(X - mean, axes.T)."""
    return dot_fixed(np.asarray(X, dtype=np.float64) - np.asarray(mean, dtype=np.float64),
                     np.asarray(axes, dtype=np.float64).T)


def empty_m5() -> dict:
    """K = 0: exactly the dict written by `state.migrations.migrate_1_to_2` (test of equality)."""
    return {"centroids": np.zeros((0, 16), dtype=np.float32), "counts": [], "created_sol": [], "named_sol": [],
            "conf": np.zeros((0,), dtype=np.float32), "places": [], "mean": np.zeros(16, dtype=np.float32),
            "axes": np.zeros((2, 16), dtype=np.float32), "explained": 0.0, "n_updates": 0}


@dataclass(frozen=True)
class M5Report:
    k: int
    n_named: int
    new_named: list
    ari: float | None
    common: int
    explained: float
    valid: bool


def _dist(X: Arr, c: Arr) -> Arr:
    return np.sqrt(sum_axis((X[:, None, :] - c[None, :, :]) ** 2, 2))


def update_m5(m5: dict, rows: Arr, first_new_id: int, sol: int, seed: int, params: Params) -> M5Report:
    """SPEC 6.14.5 steps 1-8, `m5` modified in place. `rows` = analysed rows of the memory plus those of the sol, by
    increasing id (rows whose `analysed` column is 0 are ignored)."""
    if params is None:                                   # J8.5-0 skeleton tests call without parameters
        from rover import config
        params = config.load()
    P = params.get
    new_dist, iters, name_min = float(P("brain.m5.new_dist")), int(P("brain.m5.lloyd_iters")), int(P("brain.m5.name_min"))
    rows = np.asarray(rows, dtype=np.float64).reshape(-1, 32)
    rows = rows[rows[:, 15] > 0.5]
    rows = rows[np.argsort(rows[:, 0], kind="stable")]
    X = rows[:, 16:32]
    n = int(X.shape[0])
    C = np.asarray(m5["centroids"], dtype=np.float64).reshape(-1, 16)
    C0 = C.copy()
    created = [int(v) for v in m5["created_sol"]]
    named = [int(v) for v in m5["named_sol"]]
    # 2. creation by threshold, by increasing id (nearest-centroid distance kept up to date, one pass per creation)
    if n > 0:
        dmin = _dist(X, C).min(axis=1) if C.shape[0] else np.full(n, 1e300)
        while C.shape[0] < M5_K_MAX:
            far = np.flatnonzero(dmin > new_dist)
            if far.shape[0] == 0:
                break
            j = int(far[0])
            C = np.concatenate([C, X[j:j + 1]], axis=0)
            created.append(int(sol))
            named.append(-1)
            dmin = np.minimum(dmin, _dist(X, X[j:j + 1])[:, 0])
    K = int(C.shape[0])
    # 3. Lloyd from the previous centroids (warm start); an empty centroid is kept
    if n > 0 and K > 0:
        for _ in range(iters):
            lab, _ = classify(C, X, new_dist)
            for k in range(K):
                mem = X[lab == k]
                if mem.shape[0]:
                    C[k] = sum_axis(mem, 0) / float(mem.shape[0])
        C = C.astype(np.float32).astype(np.float64)                  # what the state stores: labels follow the stored bytes
    # 4. final labels, counts, naming
    if n > 0 and K > 0:
        L1, conf = classify(C, X, new_dist)
    else:
        L1, conf = np.full(n, -1, dtype=np.int64), np.zeros(n, dtype=np.float64)
    counts = np.bincount(L1[L1 >= 0], minlength=K).tolist() if K > 0 else []
    new_named = []
    for k in range(K):
        if counts[k] >= name_min and named[k] == -1:
            named[k] = int(sol)
            new_named.append(k)
    n_named = isum_py(1 for v in named if v >= 0)
    # 5. ARI against the labels of the centroids as they were before the sol, on the common points
    common = np.flatnonzero(rows[:, 0] < float(first_new_id))
    k0 = int(C0.shape[0])
    valid = bool(common.shape[0] >= int(P("stages.ari_min_points")) and k0 >= 1 and n_named >= int(P("stages.ari_min_named")))
    ari_v = None
    if valid:
        L0 = classify(C0, X[common], new_dist)[0]
        ari_v = ari(L0, L1[common])
    # 6. atlas data: mean confidence, first three places by id
    cf = np.zeros(K, dtype=np.float32)
    places = []
    for k in range(K):
        idx = np.flatnonzero(L1 == k)
        cf[k] = fsum(conf[idx]) / float(idx.shape[0]) if idx.shape[0] else 0.0
        places.append([[int(rows[i, 2]), int(rows[i, 3])] for i in idx[:3]])
    # 7. axes of the SCAN cloud
    explained = 0.0
    if n >= 1:
        mean = sum_axis(X, 0) / float(n)
        m5["mean"] = mean.astype(np.float32)
    if n >= 2:
        Xc = X - mean
        Cv = dot_fixed(Xc.T, Xc) / float(n)
        tr = fsum(Cv[np.arange(16), np.arange(16)])
        old = np.asarray(m5["axes"], dtype=np.float64).reshape(2, 16)
        start = old if bool(np.any(old != 0.0)) else gauss_ih4(derive(seed, "m5", 0), np.arange(32)).reshape(2, 16)
        axes, ex = power_axes(Cv, start, int(P("brain.m5.power_iters"))) if tr >= 1e-12 else (np.zeros((2, 16)), 0.0)
        if bool(np.any(axes != 0.0)):
            m5["axes"] = axes.astype(np.float32)
            explained = ex
    m5["centroids"] = C.astype(np.float32)
    m5["counts"], m5["created_sol"], m5["named_sol"] = [int(v) for v in counts], created, named
    m5["conf"], m5["places"], m5["explained"] = cf, places, float(explained)
    m5["n_updates"] = int(m5["n_updates"]) + 1
    return M5Report(k=K, n_named=n_named, new_named=new_named, ari=ari_v, common=int(common.shape[0]),
                    explained=float(explained), valid=valid)
