"""Build fitting/VisibleClothing_Fitting.blend for hand-fitting the clothing in Blender.

blender -b --factory-startup -P tools/make_fitting_blend.py

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

FIT = os.path.join(vb.ROOT, "fitting")
TEX = os.path.join(FIT, "textures")
OUT = os.path.join(vb.WORK, "out")
TO_BLEND = Matrix.Rotation(math.pi, 4, "Z")  # internal frame faces +Y; the fitting file faces -Y
ITEMS = [f"Clothing{k}{t}" for k in ("Outfit", "Pants", "Head", "Hands", "Feet") for t in ("T1", "T2", "T3")]


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


def main():
    os.makedirs(TEX, exist_ok=True)
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
    for it in ITEMS:
        ob = garment_from_json(it)
        ob.data.transform(TO_BLEND)
        cm.objects.link(ob)
    coll("Clothing Female")
    bpy.context.scene.unit_settings.system = "METRIC"
    out = os.path.join(FIT, "VisibleClothing_Fitting.blend")
    bpy.ops.wm.save_as_mainfile(filepath=out, relative_remap=True)
    print("SAVED", out)


main()
