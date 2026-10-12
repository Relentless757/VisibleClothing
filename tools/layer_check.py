"""Layering check (Blender), rest pose, Unity space:
  - each of the 16 head variants per sex vs each outfit collar (head skin must stay under the shirt)
  - pants waistband under its shirt hem (T3: the shirt tucked under the pants); balaclava neck under each shirt
blender -b --factory-startup -P tools/layer_check.py [-- male|female]

Ray test instead of nearest point (nearest point miscounts along open edges such as collars and hems): from each
inner vertex, along its own normal, look for the outer garment. Covered = the outer garment is there (within 2 cm
either side); POKE = covered but the outer surface is less than 1 mm outside the inner vertex (or behind it).
"""
import json, os, sys, glob, numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

W = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_work")
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SEXES = args or ["male", "female"]


def part(item, sex, k=0):
    p = json.load(open(f"{W}/out/{item}_{sex}.json"))["parts"][k]
    return np.array(p["verts"]), np.array(p["normals"]), [tuple(t) for t in p["tris"]]


def bvh(V, T, N):
    N = N / (np.linalg.norm(N, axis=1, keepdims=True) + 1e-12)
    return BVHTree.FromPolygons([tuple(v) for v in V], T, all_triangles=True), N, T


def ray_layer(outer, P, N, reach=0.02, gap=0.001):
    """s = how far outside the inner vertex the outer garment is, along the inner normal (nan = not covered, or the
    inner vertex is lining facing the other way: those follow their outer surface)."""
    tree, ON, OT = outer
    s = np.full(len(P), np.nan)
    for i, (p, n) in enumerate(zip(P, N)):
        n = n / (np.linalg.norm(n) + 1e-12)
        hit = tree.ray_cast(Vector(p - n * reach), Vector(n), 2 * reach)
        if hit[0] is not None and ON[list(OT[hit[2]])].mean(0) @ n > 0.2:
            s[i] = hit[3] - reach
    return s


def report(name, s, gap=0.001):
    cov = ~np.isnan(s)
    n = max(cov.sum(), 1)
    poke = (s[cov] < gap)
    print(f"LAYER {name}: {cov.sum()} covered verts, POKE {poke.sum()} ({poke.sum() / n:.1%})"
          + (f", worst {-s[cov].min() * 1000:.1f} mm through" if poke.any() and s[cov].min() < 0 else ""))
    return poke.sum()


for sex in SEXES:
    body = json.load(open(f"{W}/body_{sex}.json"))
    neck = np.array([n for n in body["nodes"] if n["name"] == "Neck"][0]["world"])[:3, 3]
    heads = sorted(glob.glob(f"{W}/heads/{sex}_*.json"))
    for t in ("T1", "T2", "T3"):
        SV, SN, ST = part(f"ClothingOutfit{t}", sex)
        shirt = bvh(SV, ST, SN)
        tot, worst = 0, ("", 0)
        for hf in heads:
            hs = next(x for x in json.load(open(hf))["smrs"] if x["node"] == "head")
            H, HN = np.array(hs["verts"]), np.array(hs["normals"])
            sel = H[:, 1] < neck[1] + 0.03
            s = ray_layer(shirt, H[sel], HN[sel])
            cov = ~np.isnan(s)
            k = int((s[cov] < 0.001).sum())
            tot += k
            if k > worst[1]:
                worst = (os.path.basename(hf)[:-5], k, -s[cov].min() * 1000)
        print(f"LAYER {sex} heads under shirt{t}: {tot} head verts at/through the collar over {len(heads)} heads; worst {worst}")
        PV, PN, PT = part(f"ClothingPants{t}", sex)
        if t == "T3":   # skin-tight tactical shirt: tucked into its pants
            report(f"{sex} shirt{t} tucked under pants{t}", ray_layer(bvh(PV, PT, PN), SV, SN))
        else:
            report(f"{sex} pants{t} under shirt{t}", ray_layer(shirt, PV, PN))
        BV, BN, _ = part("ClothingHeadT3", sex)
        report(f"{sex} balaclava under shirt{t}", ray_layer(shirt, BV, BN))
