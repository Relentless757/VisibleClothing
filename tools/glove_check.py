"""Sleeves vs gloves (Blender), rest pose: every long-sleeved shirt must lie over every glove.
blender -b --factory-startup -P tools/glove_check.py [-- male|female]

From each outward-facing shirt vert (inner lining that faces the arm is skipped), along its normal: if the outermost
outward-facing glove surface within 1.5 cm is outside the vert (or less than 0.5 mm under it), the vert is UNDER the
glove = the glove shows through the sleeve. geo_garment.push_over() fixes these at build time.
"""
import json, os, sys, numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

W = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_work")
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def load(p):
    q = json.load(open(p))["parts"][0]
    V, N = np.array(q["verts"]), np.array(q["normals"])
    return V, N / (np.linalg.norm(N, axis=1, keepdims=True) + 1e-12), [tuple(t) for t in q["tris"]]


for sex in args or ["male", "female"]:
    J = {n["name"]: np.array(n["world"])[:3, 3] for n in json.load(open(f"{W}/body_{sex}.json"))["nodes"]}

    def outward(v, n):
        side = "Left" if v[0] < 0 else "Right"
        a, b = J[side + "ForeArm"], J[side + "Hand"]
        ax = (b - a) / np.linalg.norm(b - a)
        r = (v - a) - ((v - a) @ ax) * ax
        return n @ (r / (np.linalg.norm(r) + 1e-9)) > 0.2

    for t in ("T1", "T2", "T3"):
        SV, SN, _ = load(f"{W}/out/ClothingOutfit{t}_{sex}.json")
        row = []
        for gt in ("T1", "T2", "T3"):
            GV, GN, GT = load(f"{W}/out/ClothingHands{gt}_{sex}.json")
            tree = BVHTree.FromPolygons([tuple(v) for v in GV], GT, all_triangles=True)
            FN = np.array([GN[list(f)].mean(0) for f in GT])
            lo, hi = GV.min(0) - 0.02, GV.max(0) + 0.02
            under, worst = 0, 0.0
            for i in np.where(np.all((SV > lo) & (SV < hi), axis=1))[0]:
                v, n = SV[i], SN[i]
                if not outward(v, n):
                    continue
                start, left = Vector(v - n * 0.015), 0.03
                while left > 1e-4:
                    h = tree.ray_cast(start, Vector(n), left)
                    if h[0] is None:
                        break
                    if FN[h[2]] @ n > 0.2:
                        s = (np.array(h[0]) - v) @ n
                        if s > -0.0005:
                            under, worst = under + 1, max(worst, s)
                            break
                    step = h[3] + 1e-4
                    start, left = start + Vector(n) * step, left - step
            row.append(f"gloves {gt}: {under}" + (f" (worst {worst * 1000:.1f} mm)" if under else ""))
        print(f"GLOVES {sex} Outfit{t} sleeve verts under the glove: " + ", ".join(row))
