"""Render the exported clothing (_work/out/<Item>_<sex>.json, i.e. what goes into the bundle) on the
vanilla body, smooth shaded, with the alpha cutout.

blender -b --factory-startup -P tools/preview_json.py -- <sex> <out.png> <Item> [<Item> ...]
Each item becomes one row of front / side / back.
"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_blender as vb
import numpy as np
import bpy
from mathutils import Vector

OUT = os.path.join(vb.WORK, "out")


def clothing_obj(item, sex):
    d = json.load(open(os.path.join(OUT, f"{item}_{sex}.json")))
    obs = []
    for p in d["parts"]:
        me = bpy.data.meshes.new(item + p["part"])
        me.from_pydata([vb.u2b(v) for v in p["verts"]], [], [(t[0], t[2], t[1]) for t in p["tris"]])
        uvl = me.uv_layers.new(name="UV")
        idx = np.zeros(len(me.loops), dtype=int)
        me.loops.foreach_get("vertex_index", idx)
        uvl.data.foreach_set("uv", np.array(p["uv"])[idx].reshape(-1))
        me.shade_smooth()
        ob = bpy.data.objects.new(item + p["part"], me)
        bpy.context.scene.collection.objects.link(ob)
        m = bpy.data.materials.new("cloth")
        m.use_nodes = True
        nt = m.node_tree
        bsdf = nt.nodes["Principled BSDF"]
        bsdf.inputs["Roughness"].default_value = 0.85
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(os.path.join(OUT, p["texture"]), check_existing=True)
        nt.links.new(t.outputs[0], bsdf.inputs["Base Color"])
        mt = nt.nodes.new("ShaderNodeMath")  # hard cutout like the game's alpha test
        mt.operation = "GREATER_THAN"
        mt.inputs[1].default_value = 0.5
        nt.links.new(t.outputs[1], mt.inputs[0])
        nt.links.new(mt.outputs[0], bsdf.inputs["Alpha"])
        ob.data.materials.append(m)
        obs.append(ob)
    return obs


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    sex, out, items = argv[0], argv[1], argv[2:]
    vb.clear()
    parts, B, _ = vb.load_body(sex)
    skin = bpy.data.materials.new("skin")
    skin.use_nodes = True
    skin.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.72, 0.55, 0.45, 1)
    for o in parts.values():
        o.data.shade_smooth()
        o.data.materials.clear()
        o.data.materials.append(skin)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y = 520, 620
    sc.render.film_transparent = False
    world = bpy.data.worlds.new("w"); sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.18, 0.19, 0.21, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(150))
    sc.collection.objects.link(sun)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam); sc.camera = cam
    cam.data.type = "ORTHO"
    rows = []
    for item in items:
        cl = [o for it in item.split("+") for o in clothing_obj(it, sex)]   # "A+B" shows both together
        kind = next(k for k in ("Outfit", "Head", "Hands", "Feet", "Pants") if k in item)
        center, size = {"Outfit": ((0, 0, 0.95), 2.0), "Head": ((0, 0, 1.63), 0.55),
                         "Hands": ((-0.565, 0.17, 1.12), 0.28), "Feet": ((0, 0, 0.3), 0.75), "Pants": ((0, 0, 0.62), 1.35)}[kind]
        cam.data.ortho_scale = size
        tiles = []
        dirs = {"Hands": [Vector((-0.63, -0.18, 0.75)), Vector((0.63, 0.18, -0.75)), Vector((0.2, 0.95, 0.1))]}.get(kind)
        for ai, a in enumerate((20, 90, 180)):
            r = math.radians(a)
            d = dirs[ai].normalized() if dirs else Vector((math.sin(r), math.cos(r), 0.12))
            cam.location = Vector(center) + d * 4
            cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
            p = os.path.join(vb.WORK, f"pv_{item.replace('+', '_')}_{sex}_{a}.png")
            sc.render.filepath = p
            bpy.ops.render.render(write_still=True)
            tiles.append(p)
        rows.append(tiles)
        for o in cl:
            bpy.data.objects.remove(o)
    with open(out + ".txt", "w") as f:
        f.write("\n".join("\t".join(r) for r in rows))


if __name__ == "__main__":
    main()
