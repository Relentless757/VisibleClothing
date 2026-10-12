"""Close-up EEVEE renders of exported clothing on the body.
blender -b -P tools/closeup.py -- <sex> <out_prefix> <cx,cy,cz> <size> <Item[+Item]> [dir ...]   dirs like 0,1,0.2"""
import sys, os, math; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_blender as vb, preview_json as pj, bpy
from mathutils import Vector
a = sys.argv[sys.argv.index("--") + 1:]
sex, out, ctr, size, items = a[0], a[1], Vector(map(float, a[2].split(","))), float(a[3]), a[4].split("+")
dirs = [Vector(map(float, d.split(","))) for d in a[5:]] or [Vector((0, 1, 0.1))]
vb.clear(); parts, B, _ = vb.load_body(sex)
skin = bpy.data.materials.new("s"); skin.use_nodes = True
skin.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.75, 0.58, 0.48, 1)
for o in parts.values(): o.data.shade_smooth(); o.data.materials.append(skin)
for it in items: pj.clothing_obj(it, sex)
sc = bpy.context.scene; sc.render.engine = "BLENDER_EEVEE"; sc.render.resolution_x = sc.render.resolution_y = 480
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True; w.node_tree.nodes["Background"].inputs[1].default_value = 1.2
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); sun.data.energy = 3.5; sun.rotation_euler = (math.radians(40), 0, math.radians(160)); sc.collection.objects.link(sun)
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam; cam.data.type = "ORTHO"; cam.data.ortho_scale = size
paths = []
for i, d in enumerate(dirs):
    d = d.normalized(); cam.location = ctr + d * 2; cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    p = os.path.abspath(f"{out}_{i}.png"); sc.render.filepath = p; bpy.ops.render.render(write_still=True); paths.append(p)
open(out + ".txt", "w").write("\t".join(paths))
