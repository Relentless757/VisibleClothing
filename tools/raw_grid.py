"""Front (+Y camera) ortho render of a raw garment (as import_garment leaves it) with a 5cm grid."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_blender as vb, numpy as np, bpy
argv = sys.argv[sys.argv.index("--") + 1:]
item, view = argv[0], (argv[1] if len(argv) > 1 else "front")
vb.clear(); g = vb.import_garment(item)
G = vb.verts_np(g); lo, hi = G.min(0), G.max(0)
print("BBOX", lo.round(3), hi.round(3))
ang = {"front": 0, "side": 90, "back": 180, "top": "top"}[view]
c = (lo + hi) / 2
vb.render(os.path.join(vb.WORK, f"raw_{item}_{view}"), [g], tuple(c), 1.1, angles=(ang,), res=660)
