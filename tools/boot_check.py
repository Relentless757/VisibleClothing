"""Pants over boots: how many boot points stick out through the pants, and a render per boot.

blender -b --factory-startup -P tools/boot_check.py -- <sex> <PantsItem> <out_prefix> [boot_key ...]
boot keys from _work/vanilla_boots_<sex>.json (e.g. biker_feet_A raider_feet) or ClothingFeetT1 (ours).
Prints, per boot, the side-facing boot points between hem and knee with no pants in front of them (exposed).
"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_blender as vb, preview_json as pj
import numpy as np, bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

a = sys.argv[sys.argv.index("--") + 1:]
sex, pants, out, keys = a[0], a[1], a[2], a[3:]
vb.clear()
parts, B, _ = vb.load_body(sex)
skin = bpy.data.materials.new("s"); skin.use_nodes = True
skin.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.75, 0.58, 0.48, 1)
for ob in parts.values():
    ob.data.materials.clear(); ob.data.materials.append(skin); ob.data.shade_smooth()
pobs = pj.clothing_obj(pants, sex)
P = json.load(open(os.path.join(vb.WORK, "out", f"{pants}_{sex}.json")))["parts"][0]
PV = np.array(P["verts"])[:, [0, 2, 1]]
PT = [(t[0], t[2], t[1]) for t in P["tris"]]
bvh = BVHTree.FromPolygons([tuple(v) for v in PV], PT)
vd = json.load(open(os.path.join(vb.WORK, f"vanilla_boots_{sex}.json")))
knee = B["LeftLeg"].z
bootm = bpy.data.materials.new("bootm"); bootm.use_nodes = True
bootm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.9, 0.15, 0.1, 1)
sc = bpy.context.scene; sc.render.engine = "BLENDER_EEVEE"; sc.render.resolution_x = sc.render.resolution_y = 360
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True; w.node_tree.nodes["Background"].inputs[1].default_value = 1.2
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); sun.data.energy = 3.5
sun.rotation_euler = (math.radians(40), 0, math.radians(160)); sc.collection.objects.link(sun)
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = "ORTHO"; cam.data.ortho_scale = 0.62
paths = []
for key in keys:
    if key in vd:
        d = vd[key]
        V, T = [vb.u2b(v) for v in d["verts"]], [(t[0], t[2], t[1]) for t in d["tris"]]
    else:
        q = json.load(open(os.path.join(vb.WORK, "out", f"{key}_{sex}.json")))["parts"][0]
        V, T = [vb.u2b(v) for v in q["verts"]], [(t[0], t[2], t[1]) for t in q["tris"]]
    me = bpy.data.meshes.new(key); me.from_pydata(V, [], T); me.shade_smooth()
    ob = bpy.data.objects.new(key, me); sc.collection.objects.link(ob); ob.data.materials.append(bootm)
    Vn = np.array(V)
    Nn = np.array([vb.u2b(n) for n in d["normals"]]) if key in vd else np.array([vb.u2b(n) for n in q["normals"]])
    out_n, tot = 0, 0
    hem = PV[:, 2].min() + 0.02           # points under the pants: between the hem and the knee
    for v, n in zip(Vn, Nn):
        if not (hem < v[2] < knee):
            continue
        h = np.array([n[0], n[1], 0.0])
        if np.linalg.norm(h) < 0.3:       # top / bottom faces: not seen from the side
            continue
        h /= np.linalg.norm(h)
        tot += 1
        hit = bvh.ray_cast(Vector(v + h * 0.0005), Vector(h), 0.15)
        if hit[0] is None:                # nothing of the pants in front of this boot point: it shows
            out_n += 1
    print(f"BOOT {key}: {out_n}/{tot} side-facing boot points between hem and knee are exposed")
    for i, dv in enumerate([Vector((0, 1, 0.1)), Vector((1, 0.25, 0.1))]):
        dv = dv.normalized(); cam.location = Vector((0, 0, 0.27)) + dv * 3
        cam.rotation_euler = (-dv).to_track_quat("-Z", "Y").to_euler()
        p = os.path.abspath(f"{out}_{key}_{i}.png"); sc.render.filepath = p
        bpy.ops.render.render(write_still=True); paths.append(p)
    bpy.data.objects.remove(ob)
open(out + ".txt", "w").write("\t".join(paths))
