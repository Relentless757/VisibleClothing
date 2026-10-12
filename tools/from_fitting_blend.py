"""Read hand-fitted garments from fitting/VisibleClothing_Fitting.blend and produce the bundle data.

blender -b --factory-startup -P tools/from_fitting_blend.py -- [Item ...] [--raw]

For every object in "Clothing Male" (optionally only the named items):
  - takes its evaluated mesh in world space (modifiers + transforms applied), UVs and image texture
  - light clean-up: pushes anything that ended up inside the skin (or under-layer: head envelope, the outfit's
    pants, boots) back out; --raw skips it
  - layering and skin weights: geo_garment.finish() / garment_weights(), the same code as the automatic fit
    (region labels smoothed over the garment, so a sleeve hanging next to the ribs still follows the arm)
  - female: an object of the same name in "Clothing Female" is used as is; otherwise the male fit is moved
    by the female-minus-male body difference
Writes _work/out/<Item>_{male,female}.json + <Item>.png, then run tools/pack_unity.py and the Unity build.
"""
import sys, os, json, shutil, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_blender as vb
import fit
import numpy as np
import bpy, bmesh
from mathutils import Matrix
import importlib.util

spec = importlib.util.spec_from_file_location("gg", os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo_garment.py"))
gg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gg)

FIT = os.path.join(vb.ROOT, "fitting", "VisibleClothing_Fitting.blend")
OUT = os.environ.get("VC_FIT_OUT", os.path.join(vb.WORK, "out"))   # VC_FIT_OUT: write elsewhere (dry run)
FROM_BLEND = Matrix.Rotation(math.pi, 4, "Z")
GAP = {"Outfit": 0.004, "Pants": 0.004, "Head": 0.005, "Hands": 0.0015, "Feet": 0.002}


def grab(collection, only):
    """Pull mesh data out of the fitting file before it is closed."""
    got = {}
    c = bpy.data.collections.get(collection)
    if not c:
        return got
    dg = bpy.context.evaluated_depsgraph_get()
    for ob in c.all_objects:
        if ob.type != "MESH":
            continue
        name = ob.name.split(".")[0]
        if only and name not in only:
            continue
        if name in got and (ob.hide_get() or not got[name]["visible"]):
            # two objects for one item (an old fit kept next to a new one): the visible one wins
            print(f"  {name}: several objects, using {got[name]['obj'] if ob.hide_get() else ob.name} (visible)")
            if ob.hide_get():
                continue
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        me.transform(FROM_BLEND @ ob.matrix_world)
        me.calc_loop_triangles()
        V = np.array([v.co[:] for v in me.vertices])
        uvl = me.uv_layers.active.data if me.uv_layers.active else None
        tris, uvs = [], []
        for lt in me.loop_triangles:
            tris.append(tuple(lt.vertices))
            uvs.append([tuple(uvl[li].uv) for li in lt.loops] if uvl else [(0, 0)] * 3)
        img = None
        for m in ob.material_slots:
            if m.material and m.material.use_nodes:
                for n in m.material.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image:
                        img = bpy.path.abspath(n.image.filepath, library=n.image.library)
                        break
            if img:
                break
        got[name] = dict(V=V, tris=tris, uvs=uvs, img=img, visible=not ob.hide_get(), obj=ob.name)
        ev.to_mesh_clear()
    return got


def build(name, d):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in d["V"]], [], d["tris"])
    uvl = me.uv_layers.new(name="UV")
    flat = [uv for tri in d["uvs"] for uv in tri]
    uvl.data.foreach_set("uv", np.array(flat).reshape(-1))
    me.update()
    # a raw import (e.g. a Tripo FBX) splits verts along UV seams: weld them (UVs live on the loops and stay), or
    # weight smoothing stops at every seam and the seams crack when the garment moves
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def regions(g, surf, nb, iters=6):
    """Nearest-body-region label per vertex, then majority-smoothed over the garment's own edges."""
    G = vb.verts_np(g)
    lab = []
    for v in G:
        r = surf.nearest(v)
        pi, fi, _ = r[2]
        lab.append(surf.data[pi]["freg"][fi])
    lab = np.array(lab, dtype=object)
    for _ in range(iters):
        new = lab.copy()
        for i, x in enumerate(nb):
            if x:
                vals = list(lab[x]) + [lab[i]]
                new[i] = max(set(vals), key=vals.count)
        lab = new
    return lab


def process(item, male, female, raw):
    c = dict(fit.CFG[item])
    kind = c["kind"]
    k = dict(gg.KIND[kind], **c.get("kind_over", {}))
    k["gap"] = GAP[next(x for x in GAP if x in item)]   # hand fits sit closer than the automatic fit's margins
    tex = f"{item}.png"
    if male["img"] and os.path.exists(male["img"]):
        shutil.copy2(male["img"], os.path.join(OUT, tex))
    todo = [("male", male), ("female", female)]
    while todo:
        sex, d = todo.pop(0)
        if d is None:
            d = female
        vb.clear()
        parts, B, _ = vb.load_body(sex, head="ref" if kind == "head" else "env")
        g = build(item, d)
        # welded vert of each input vert (same position), computed before anything moves
        from mathutils.kdtree import KDTree
        kd = KDTree(len(g.data.vertices))
        for i, v in enumerate(g.data.vertices):
            kd.insert(v.co, i)
        kd.balance()
        widx = [kd.find(v)[1] for v in d["V"]]
        nb = gg.adjacency(g)
        surf = gg.BodySurface(parts, k["parts"], gg.region_of_bone)
        reg = regions(g, surf, nb)
        c.pop("_free", None)
        if item == "ClothingPantsT1":  # cloth drawstrings: small separate pieces at the front of the waistband
            G0 = vb.verts_np(g)
            free = [ix for ix in vb.islands(g) if 60 <= len(ix) <= 400 and G0[ix, 2].min() > B["Hips"].z - 0.25
                    and np.abs(G0[ix, 0]).max() < 0.09 and G0[ix, 1].mean() > 0.0]
            c["_free"] = np.concatenate(free) if free else None
        pre = vb.verts_np(g)
        if raw:   # the shape exactly as modelled; weights the same way as the automatic fit
            anchors = [(lambda r: r[2] if r else None)(surf.nearest(v, {reg[i]})) for i, v in enumerate(pre)]
            w = gg.garment_weights(g, surf, reg, c, kind, B, nb)
        elif kind == "hands":
            # gloves are fitted snug by hand: keep the shape exactly; only verts actually inside the skin step out to
            # 0.6 mm, one by one (a smoothed push widened the finger openings; the 3 cm unclip stretched the thumb
            # hole into a fin)
            k["gap"] = 0.001
            surf, anchors, w = gg.finish(item, g, parts, B, reg, c, k, nb, sex, pre, iters=0, loose=9.0,
                                         loose_arm=None, unclip_on=False)
        else:     # light clean-up (no pulling in: loose = 9 m, unless the item sets handfit_loose) + the same layering
                  # and weights as the automatic fit
            hl = c.get("handfit_loose")
            surf, anchors, w = gg.finish(item, g, parts, B, reg, c, k, nb, sex, pre, iters=4 if hl else 1,
                                         loose=hl or 9.0, loose_arm=None)
            if hl and kind == "head":
                # tighten the hood only: the mask over the face keeps the hand-fitted shape (pulled in, its top
                # edge folded over the nose bridge), blended back from in front of the ears
                H = vb.verts_np(parts["head"])
                ear_y = H[:, 1].mean() + 0.03                    # Blender: +Y = the face side
                G = vb.verts_np(g)
                t = np.clip((G[:, 1] - ear_y) / 0.04, 0, 1)
                t = (t * t * (3 - 2 * t))[:, None]
                vb.set_verts(g, G * (1 - t) + pre * t)
                w = gg.garment_weights(g, surf, reg, c, kind, B, nb)
        json.dump(dict(item=item, sex=sex, parts=gg.export_parts(g, w, tex, c)),
                  open(os.path.join(OUT, f"{item}_{sex}.json"), "w"))
        if sex == "male" and female is None:
            # derive the female fit: same-topology parts move with the body; hands go by nearest point
            fparts, _, _ = vb.load_body("female", head="ref" if kind == "head" else "env")
            fsurf = gg.BodySurface(fparts, k["parts"], gg.region_of_bone)
            G = vb.verts_np(g)
            F = G.copy()
            same = all(np.array_equal(a["T"], b["T"]) for a, b in zip(surf.data, fsurf.data))
            for i, a in enumerate(anchors):
                if not a:
                    continue
                pm = surf.eval(a)[0]
                pf = surf.eval(a, fsurf)[0] if same else fsurf.nearest(pm, {reg[i]})[0]
                F[i] = G[i] + (pf - pm)
            female = dict(d, V=F[widx])   # back to the un-welded vertex list the female mesh is rebuilt from
        print(f"{item} {sex}: {len(d['V'])} verts")


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    raw = "--raw" in argv
    only = [a for a in argv if not a.startswith("--")]
    bpy.ops.wm.open_mainfile(filepath=FIT)
    males, females = grab("Clothing Male", only), grab("Clothing Female", only)
    # layer order: what a garment layers against must be fitted first (shoes, pants -> shirts -> hats)
    order = ["Feet", "Hands", "Pants", "Outfit", "Head"]
    rank = lambda it: (next((i for i, x in enumerate(order) if x in it), len(order)), it)
    for item, m in sorted(males.items(), key=lambda kv: rank(kv[0])):
        process(item, m, females.get(item), raw)
    print("DONE", len(males), "items")


main()
