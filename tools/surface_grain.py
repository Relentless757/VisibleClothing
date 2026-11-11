"""Surface grain for textures that came out smooth (Tripo sometimes bakes flat colour with an almost empty normal map,
which the game lights as plastic): fine fabric grain added to the normal map, a little to the albedo, and a
fabric roughness floor.

The grain is computed on the garment's 3D surface (every texel -> its point on the fitted mesh -> 3D noise there), so
it is the same size everywhere and continuous across UV seams, however Tripo cut and scaled the islands.

Used by tools/prep_textures.py for items with a `grain` setting, e.g. {"mm": 1.2, "strength": 1.0}:
    mm        grain size in millimetres
    strength  1 = subtle fabric; 1.7 is already coarse
"""
import json
import numpy as np
from PIL import Image
from scipy import ndimage


def _rasterize(V, UV, T, N):
    """Per texel: the 3D surface point and a coverage mask."""
    P = np.zeros((N, N, 3), np.float32)
    M = np.zeros((N, N), bool)
    uv = UV[T] * N
    uv[:, :, 1] = N - uv[:, :, 1]           # image rows run down
    for t in range(len(T)):
        a, b, c = uv[t]
        x0, x1 = int(max(0, np.floor(min(a[0], b[0], c[0])))), int(min(N - 1, np.ceil(max(a[0], b[0], c[0]))))
        y0, y1 = int(max(0, np.floor(min(a[1], b[1], c[1])))), int(min(N - 1, np.ceil(max(a[1], b[1], c[1]))))
        if x1 < x0 or y1 < y0:
            continue
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        l1 = ((b[1] - c[1]) * (xs - c[0]) + (c[0] - b[0]) * (ys - c[1])) / d
        l2 = ((c[1] - a[1]) * (xs - c[0]) + (a[0] - c[0]) * (ys - c[1])) / d
        l3 = 1 - l1 - l2
        inside = (l1 >= -0.02) & (l2 >= -0.02) & (l3 >= -0.02)
        if not inside.any():
            continue
        pa, pb, pc = V[T[t]]
        pos = l1[..., None] * pa + l2[..., None] * pb + l3[..., None] * pc
        yy, xx = ys[inside].astype(int), xs[inside].astype(int)
        P[yy, xx] = pos[inside]
        M[yy, xx] = True
    return P, M


def _value_noise3(P, seed):
    """Smooth 3D value noise in [-1, 1] at points P (n, 3); fixed seed, so builds are reproducible."""
    rng = np.random.default_rng(seed)
    perm = rng.permutation(256)
    vals = rng.uniform(-1, 1, 256).astype(np.float32)
    i = np.floor(P).astype(np.int64)
    f = P - i
    f = f * f * (3 - 2 * f)
    out = 0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) * (f[:, 2] if dz else 1 - f[:, 2])
                h = vals[perm[(perm[(perm[(i[:, 0] + dx) & 255] + i[:, 1] + dy) & 255] + i[:, 2] + dz) & 255]]
                out = out + w * h
    return out


def apply(fitted_json, albedo_png, normal_png, rmoe_png, mm=1.2, strength=1.0, one_hand=False):
    """Rewrite the three maps in place. fitted_json: the item's fitted garment (_work/out/<Item>_male.json)."""
    part = json.load(open(fitted_json))["parts"][0]
    V, UV, T = np.array(part["verts"]), np.array(part["uv"]), np.array(part["tris"])
    if one_hand:   # both gloves share the UVs: one hand, so every texel belongs to one surface
        T = T[(V[T][:, :, 0] < 0).all(1)]
    alb = Image.open(albedo_png).convert("RGB")
    N = alb.size[0]
    P, M = _rasterize(V, UV, T, N)
    pts = P[M].astype(np.float64) / (mm / 1000.0)
    height = np.zeros(len(pts), np.float32)
    amp, freq = 1.0, 1.0
    for o in range(4):                           # fine fabric grain
        height += amp * _value_noise3(pts * freq, seed=o)
        amp, freq = amp * 0.5, freq * 2.0
    height += 0.6 * _value_noise3(pts * 0.25, seed=9)   # a slightly coarser undulation
    H = np.zeros((N, N), np.float32)
    H[M] = height
    idx = ndimage.distance_transform_edt(~M, return_distances=False, return_indices=True)
    H = ndimage.gaussian_filter(H[idx[0], idx[1]], 0.6)   # islands padded so their borders have no cliffs

    gy, gx = np.gradient(H)
    k = 0.35 * strength
    dn = np.dstack([-gx * k, gy * k, np.ones_like(H)])
    dn /= np.linalg.norm(dn, axis=2, keepdims=True)
    try:
        base = np.asarray(Image.open(normal_png).convert("RGB").resize((N, N), Image.LANCZOS), np.float32) / 127.5 - 1
    except FileNotFoundError:
        base = np.dstack([np.zeros((N, N)), np.zeros((N, N)), np.ones((N, N))])
    bl = np.dstack([base[..., 0] + dn[..., 0], base[..., 1] + dn[..., 1], base[..., 2] * dn[..., 2]])   # whiteout blend
    bl /= np.linalg.norm(bl, axis=2, keepdims=True)
    Image.fromarray(((bl + 1) * 127.5).clip(0, 255).astype(np.uint8)).save(normal_png)

    Hn = (H - H[M].mean()) / (H[M].std() + 1e-6)
    A = np.asarray(alb, np.float32) * (1 + 0.06 * strength * np.clip(Hn, -2.5, 2.5))[..., None]
    Image.fromarray(A.clip(0, 255).astype(np.uint8)).save(albedo_png)

    rm = Image.open(rmoe_png).convert("RGBA")
    R = np.asarray(rm, np.float32)
    small = np.asarray(Image.fromarray(Hn).resize(rm.size, Image.BILINEAR), np.float32)
    R[..., 0] = np.clip(np.maximum(R[..., 0], 0.86 * 255) + 8 * strength * np.clip(small, -2, 2), 0, 255)   # fabric: never glossy
    Image.fromarray(R.astype(np.uint8), "RGBA").save(rmoe_png)
    return M.mean()
