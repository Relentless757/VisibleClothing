"""Build fitting/VisibleClothing_Fitting.blend for hand-fitting the clothing in Blender.

blender -b --factory-startup -P tools/make_fitting_blend.py
With VC_PACK=<pack folder>: builds <pack>/fitting.blend with the pack's items (see tools/vc_pack.py). Items with no
fit yet are imported from their model and roughly placed on their body slot. If the pack's fitting file exists, only
missing items are added: fitted ones are never touched.

Layout (metres, Z up, character faces -Y = Blender's Front view):
  Body Male / Body Female   vanilla body, hands, feet, head = White 04 (hats are fitted to it and morph onto the
                            other 15 faces in game); hidden: all 16 faces combined (shirt collars clear it)
  Clothing Male             the 12 garments as currently fitted - edit these
  Clothing Female           empty: drop a copy of an item here (same name) to override the auto-made female fit
Textures are kept next to the file in fitting/textures/.
"""
import sys, os, json, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_blender as vb
import numpy as np
import bpy, bmesh
from mathutils import Matrix
import math

PACK = vb.vc_pack.PACK
FIT_FILE = vb.vc_pack.FIT_BLEND
TEX = vb.vc_pack.FIT_TEX
OUT = vb.vc_pack.OUT
TO_BLEND = Matrix.Rotation(math.pi, 4, "Z")  # internal frame faces +Y; the fitting file faces -Y
ITEMS = list(vb.vc_pack.items()) if PACK else     [f"Clothing{k}{t}" for k in ("Outfit", "Pants", "Head", "Hands", "Feet") for t in ("T1", "T2", "T3")]


def place_raw(item, B):
    """A pack item with no fit yet: import its model and scale / move it onto its body slot (internal frame,
    character faces +Y, left = -X). Only a starting point: the modder fits it by hand."""
    kind = vb.vc_pack.kind_of(item)
    ob = vb.import_garment(item)
    G = vb.verts_np(ob)
    lo, hi = G.min(0), G.max(0)
    head, hips, foot = np.array(B["Head"]), np.array(B["Hips"]), np.array(B["LeftFoot"])
    target = {   # (centre, height)
        "head": (head + [0, 0.01, 0.07], 0.26),
        "outfit": (np.array(B["Spine2"]) + [0, 0, -0.05], 0.62),
        "shirt": (np.array(B["Spine2"]) + [0, 0, -0.05], 0.62),
        "pants": ((hips + foot) / 2 + [0, 0, 0.04], hips[2] + 0.08 - foot[2]),
        "hands": (np.array(B["LeftHand"]) + [-0.05, 0.02, -0.03], 0.22),
        "feet": ((foot + np.array(B["RightFoot"])) / 2 + [0, 0.04, -0.03], 0.16),
    }[kind]
    if kind == "head":   # hats: by width (a beanie is short, a balaclava tall), top at the top of the skull
        s = 0.205 / max(hi[0] - lo[0], 1e-6)
        P = (G - (lo + hi) / 2) * s
        P += [head[0], head[1] + 0.01, head[2] + 0.205 - P[:, 2].max()]
        vb.set_verts(ob, P)
    else:
        s = target[1] / max(hi[2] - lo[2], 1e-6)
        vb.set_verts(ob, (G - (lo + hi) / 2) * s + target[0])
    ob.data.shade_smooth()
    print(f"  {item}: placed on the {kind} slot (scale x{s:.3f}) - fit it by hand")
    return ob


def coll(name, parent=None, hide=False):
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    if hide:
        bpy.context.view_layer.layer_collection.children[name].hide_viewport = True
    return c


def move_to(ob, c):
    for u in list(ob.users_collection):
        u.objects.unlink(ob)
    c.objects.link(ob)


def garment_from_json(item):
    d = json.load(open(os.path.join(OUT, f"{item}_male.json")))
    verts, tris, uvs = [], [], []
    for p in d["parts"]:  # garment + optional cloth pieces (drawstrings) in one object
        if p["part"] == "lining":   # generated again on rebuild (seam lining), not hand-fitted
            continue
        base = len(verts)
        verts += [vb.u2b(v) for v in p["verts"]]
        tris += [(t[0] + base, t[2] + base, t[1] + base) for t in p["tris"]]
        uvs += p["uv"]
    p = d["parts"][0]
    me = bpy.data.meshes.new(item)
    me.from_pydata(verts, [], tris)
    uvl = me.uv_layers.new(name="UVMap")
    idx = np.zeros(len(me.loops), dtype=int)
    me.loops.foreach_get("vertex_index", idx)
    uvl.data.foreach_set("uv", np.array(uvs)[idx].reshape(-1))
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)  # undo the UV-seam split; UVs stay per corner
    bm.to_mesh(me); bm.free()
    me.shade_smooth()
    ob = bpy.data.objects.new(item, me)
    tex = os.path.join(TEX, p["texture"])
    shutil.copy2(os.path.join(OUT, p["texture"]), tex)
    m = bpy.data.materials.new(item)
    m.use_nodes = True
    t = m.node_tree.nodes.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(tex)
    m.node_tree.links.new(t.outputs[0], m.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    me.materials.append(m)
    return ob


def add_missing_items():
    """Pack fitting file already there: import only the items it does not have yet."""
    bpy.ops.wm.open_mainfile(filepath=FIT_FILE)
    cm = bpy.data.collections.get("Clothing Male")
    have = {o.name.split(".")[0] for o in cm.all_objects}
    new = [it for it in ITEMS if it not in have]
    if not new:
        print("fitting file has every item; nothing added")
        return
    _, B, _ = vb.load_body("male", head="ref")
    for o in [o for o in bpy.data.objects if o.name.startswith("male_") and o.users_collection == (bpy.context.scene.collection,)]:
        bpy.data.objects.remove(o)
    for it in new:
        ob = place_raw(it, B)
        ob.data.transform(TO_BLEND)
        move_to(ob, cm)
    bpy.ops.wm.save_mainfile()
    print("SAVED", FIT_FILE, "added", new)


def main():
    os.makedirs(TEX, exist_ok=True)
    if PACK and os.path.exists(FIT_FILE):
        return add_missing_items()
    vb.clear()
    skin = bpy.data.materials.new("skin (reference)")
    skin.diffuse_color = (0.75, 0.6, 0.5, 1)
    skin.use_nodes = True
    skin.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.75, 0.6, 0.5, 1)
    for sex in ("male", "female"):
        c = coll(f"Body {sex.capitalize()}", hide=(sex == "female"))
        parts, B, _ = vb.load_body(sex, head="ref")   # a real head (White 04): hats are fitted to it, others morph
        env, _, _ = vb.load_body(sex)                  # all 16 faces combined: what shirt collars must clear
        parts["head (all 16 faces combined)"] = env.pop("head")
        for o in env.values():
            bpy.data.objects.remove(o)
        for name, ob in parts.items():
            ob.name = f"{sex}_{name}"
            if "combined" in name:
                ob.hide_set(True)
            ob.data.transform(TO_BLEND)
            ob.data.shade_smooth()
            ob.data.materials.append(skin)
            ob.hide_select = True          # reference: can't be grabbed by accident
            move_to(ob, c)
    cm = coll("Clothing Male")
    _, Bm, _ = vb.load_body("male", head="ref")
    for o in [o for o in bpy.data.objects if not o.users_collection or o.users_collection[0] == bpy.context.scene.collection]:
        if o.type == "MESH" and o.name.startswith("male_"):
            bpy.data.objects.remove(o)
    for it in ITEMS:
        if os.path.exists(os.path.join(OUT, f"{it}_male.json")):
            ob = garment_from_json(it)
        else:
            ob = place_raw(it, Bm)
        ob.data.transform(TO_BLEND)
        move_to(ob, cm)
    coll("Clothing Female")
    bpy.context.scene.unit_settings.system = "METRIC"
    out = FIT_FILE
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out, relative_remap=True)
    print("SAVED", out)


main()
