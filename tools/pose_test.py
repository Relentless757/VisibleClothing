"""Pose the vanilla body + exported clothing with linear blend skinning (the same maths Unity runs) and render.
Catches what rest-pose previews can't: gaps opening at the shoulder, gloves ballooning in a fist, masks vs a turned head.

blender -b --factory-startup -P tools/pose_test.py -- <sex> <out_prefix> <pose> <cx,cy,cz> <size> <Item[+Item]> [dir ...]
poses: rest | arms_forward | arms_up | fist | head_turn | aim (arms forward + fists + head turn) | stride | crouch | wrist_back | wrist_down
Positions/dirs are Blender coords (character faces +Y, left = -X).
"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_blender as vb, preview_json as pj
import numpy as np
import bpy
from mathutils import Vector, Matrix, Quaternion

a = sys.argv[sys.argv.index("--") + 1:]
sex, out, pose, ctr, size, items = a[0], a[1], a[2], Vector(map(float, a[3].split(","))), float(a[4]), a[5].split("+")
dirs = [Vector(map(float, d.split(","))) for d in a[6:]] or [Vector((0, 1, 0.1))]

body = vb.load_json(f"body_{sex}.json")
nodes = body["nodes"]
idx = {n["name"]: i for i, n in enumerate(nodes)}
REST = [np.array(n["world"]) for n in nodes]
LOCAL = []
for i, n in enumerate(nodes):
    p = n["parent"]
    LOCAL.append(np.linalg.inv(REST[p]) @ REST[i] if p >= 0 else REST[i])


def rot(axis, deg):  # Unity-space rotation matrix (4x4)
    q = Quaternion(Vector(axis).normalized(), math.radians(deg)).to_matrix()
    M = np.eye(4)
    M[:3, :3] = np.array(q)
    return M


def J(name):
    return REST[idx[name]][:3, 3]


def pose_rotations(pose):
    """bone -> world-space (Unity) rotation about the bone's own joint."""
    R = {}
    if pose in ("arms_forward", "aim"):
        for s, sg in (("Left", -1), ("Right", 1)):
            R[s + "Arm"] = rot((1, 0, 0), -55) @ rot((0, 0, 1), sg * 35)    # raise to the side, then forward
            R[s + "ForeArm"] = rot((0, 1, 0), sg * -40)                      # bend the elbow inward
    if pose == "arms_up":
        for s, sg in (("Left", -1), ("Right", 1)):
            R[s + "Arm"] = rot((0, 0, 1), sg * 95)
    if pose in ("fist", "aim"):
        for s in ("Left", "Right"):
            across = J(s + "HandIndex1") - J(s + "HandPinky1")
            sg = 1 if s == "Left" else -1
            for f in ("Index", "Middle", "Ring", "Pinky"):
                for k in (1, 2, 3):
                    R[f"{s}Hand{f}{k}"] = rot(across * sg, 65)
            R[s + "HandThumb2"] = rot(J(s + "HandThumb2") - J(s + "HandThumb1"), 0) @ rot(across * sg, 35)
    if pose in ("wrist_back", "wrist_down"):   # first-person grips bend the wrist a lot; fingers spread / half curled
        for s in ("Left", "Right"):
            across = J(s + "HandIndex1") - J(s + "HandPinky1")
            sg = 1 if s == "Left" else -1
            R[s + "Hand"] = rot(across * sg, -55 if pose == "wrist_back" else 60)
            for f, spread in (("Index", 8), ("Middle", 0), ("Ring", -8), ("Pinky", -16)):
                R[f"{s}Hand{f}1"] = rot(across * sg, 25)
                R[f"{s}Hand{f}2"] = rot(across * sg, 20)
            R[s + "HandThumb2"] = rot(across * sg, 15)
    if pose == "stride":
        R["LeftUpLeg"] = rot((1, 0, 0), -40)
        R["LeftLeg"] = rot((1, 0, 0), 20)
        R["RightUpLeg"] = rot((1, 0, 0), 25)
        R["RightLeg"] = rot((1, 0, 0), 35)
    if pose == "crouch":
        for s in ("Left", "Right"):
            R[s + "UpLeg"] = rot((1, 0, 0), -95)
            R[s + "Leg"] = rot((1, 0, 0), 115)
    if pose in ("head_turn", "aim"):
        R["Neck"] = rot((0, 1, 0), 25) @ rot((1, 0, 0), 12)
        R["Head"] = rot((0, 1, 0), 30)
    return R


def posed_worlds(R):
    W = [None] * len(nodes)
    for i, n in enumerate(nodes):
        p = n["parent"]
        W[i] = (W[p] if p >= 0 else np.eye(4)) @ LOCAL[i]
        if n["name"] in R:
            j = W[i][:3, 3].copy()
            T, Ti = np.eye(4), np.eye(4)
            T[:3, 3], Ti[:3, 3] = j, -j
            W[i] = T @ R[n["name"]] @ Ti @ W[i]
    return W


SKIN = {}
for i, n in enumerate(nodes):
    pass
WP = posed_worlds(pose_rotations(pose))
SKIN = {n["name"]: WP[i] @ np.linalg.inv(REST[i]) for i, n in enumerate(nodes)}


def lbs(V, weights):
    out = np.zeros_like(V)
    for k, (v, ws) in enumerate(zip(V, weights)):
        acc = np.zeros(3)
        tot = 0
        for b, w in ws:
            if b in SKIN:
                acc += w * (SKIN[b][:3, :3] @ v + SKIN[b][:3, 3])
                tot += w
        out[k] = acc / tot if tot > 0 else v
    return out


vb.clear()
parts, B, _ = vb.load_body(sex)
skin_mat = bpy.data.materials.new("s"); skin_mat.use_nodes = True
skin_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = \
    (0.1, 0.9, 0.1, 1) if os.environ.get("VC_GREEN") else (0.75, 0.58, 0.48, 1)   # VC_GREEN: skin stands out
headdoc = json.load(open(os.environ["VC_HEAD"])) if os.environ.get("VC_HEAD") else vb.load_json(f"head_{sex}.json")  # a real head, not the envelope
smrs = {s["node"]: s for s in body["smrs"]}
smrs["head"] = next(s for s in headdoc["smrs"] if s["node"] == "head")
for name, ob in parts.items():
    s = smrs[name]
    if name == "head" and len(s["verts"]) != len(ob.data.vertices):
        bpy.data.objects.remove(ob); ob = parts["head"] = vb.build_mesh_obj(f"{sex}_head", s)
    ws = [[(s["bones"][b], w) for w, b in zip(bw, bi) if w > 0] for bw, bi in zip(s["bw"], s["bi"])]
    V = lbs(np.array(s["verts"]), ws)
    vb.set_verts(ob, [vb.u2b(v) for v in V])
    ob.data.shade_smooth(); ob.data.materials.clear(); ob.data.materials.append(skin_mat)
if os.environ.get("VC_NOBODY"):   # garment only: tells a hole in the garment from a pale patch in its texture
    for ob in parts.values():
        ob.hide_render = True
for it in items:
    d = json.load(open(os.path.join(vb.WORK, "out", f"{it}_{sex}.json")))
    obs = pj.clothing_obj(it, sex)
    for ob, p in zip(obs, d["parts"]):
        V = lbs(np.array(p["verts"]), p["weights"])
        vb.set_verts(ob, [vb.u2b(v) for v in V])
sc = bpy.context.scene; sc.render.engine = "BLENDER_EEVEE"; sc.render.resolution_x = sc.render.resolution_y = 460
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True; w.node_tree.nodes["Background"].inputs[1].default_value = 1.2
if os.environ.get("VC_GREEN") and os.environ.get("VC_NOBODY"):   # holes in the garment show green
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.1, 0.9, 0.1, 1)
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); sun.data.energy = 3.5
sun.rotation_euler = (math.radians(40), 0, math.radians(160)); sc.collection.objects.link(sun)
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = "ORTHO"; cam.data.ortho_scale = size
paths = []
for i, d in enumerate(dirs):
    d = d.normalized(); cam.location = ctr + d * 3; cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    p = os.path.abspath(f"{out}_{i}.png"); sc.render.filepath = p; bpy.ops.render.render(write_still=True); paths.append(p)
open(out + ".txt", "w").write("\t".join(paths))
