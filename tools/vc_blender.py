"""Blender helpers for Visible Clothing: load the vanilla body (from _work/*.json, Unity space) and
the Tripo garments, fit, weight, export.

Coordinates: Unity (x, y, z) <-> Blender (x, z, y). That swap is a mirror, so triangle winding is
reversed on the way in and again on the way out. The character faces +Y in Blender, its left is -X.
"""
import bpy, bmesh, json, math, os
import numpy as np
from mathutils import Vector, Matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "_work")
MODELS = os.path.join(ROOT, "7D2D Clothing models")


def u2b(v):
    return (v[0], v[2], v[1])


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def load_json(name):
    with open(os.path.join(WORK, name)) as f:
        return json.load(f)


def build_mesh_obj(name, smr, world=None):
    """SMR dict -> Blender object with vertex groups named after bones."""
    verts = np.array(smr["verts"], dtype=float)
    if world is not None:
        W = np.array(world)
        verts = (W[:3, :3] @ verts.T).T + W[:3, 3]
    me = bpy.data.meshes.new(name)
    tris = [(t[0], t[2], t[1]) for t in smr["tris"]]  # measured: needed for outward normals
    me.from_pydata([u2b(v) for v in verts], [], tris)
    if smr["uv"]:
        uvl = me.uv_layers.new(name="UV")
        loops = np.zeros(len(me.loops) * 2)
        idx = np.zeros(len(me.loops), dtype=int)
        me.loops.foreach_get("vertex_index", idx)
        uv = np.array(smr["uv"])[idx]
        uvl.data.foreach_set("uv", uv.reshape(-1))
    me.validate()
    me.update()
    # authored (smooth, seam-consistent) normals + original vertex index survive later trimming
    if smr["normals"]:
        a = me.attributes.new("unormal", "FLOAT_VECTOR", "POINT")
        a.data.foreach_set("vector", np.array([u2b(n) for n in smr["normals"]]).reshape(-1))
    a = me.attributes.new("orig_vi", "INT", "POINT")
    a.data.foreach_set("value", np.arange(len(me.vertices)))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if smr["bw"]:
        groups = {}
        for vi, (ws, bs) in enumerate(zip(smr["bw"], smr["bi"])):
            for w, b in zip(ws, bs):
                if w <= 0:
                    continue
                bn = smr["bones"][b]
                g = groups.get(bn) or ob.vertex_groups.new(name=bn)
                groups[bn] = g
                g.add([vi], w, "REPLACE")
    return ob


def bone_pos(data):
    return {n["name"]: Vector(u2b(np.array(n["world"])[:3, 3])) for n in data["nodes"]}


REF_HEAD = "white04"   # hats are fitted to this real head; tools/pack_unity.py morphs them onto the other 15


def load_body(sex, head="env"):
    """Returns dict part-> object (body, hands, feet, head) and bone positions.
    head="env": the envelope of all 16 faces (what shirt collars must clear); head="ref": the real reference head
    REF_HEAD (hats: fitted to it and morphed per head in game)."""
    body = load_json(f"body_{sex}.json")
    if head == "ref":
        head = json.load(open(os.path.join(WORK, "heads", f"{sex}_{REF_HEAD}.json")))
    else:
        head = load_json(f"head_env_{sex}.json" if os.path.exists(os.path.join(WORK, f"head_env_{sex}.json")) else f"head_{sex}.json")
    parts = {}
    for s in body["smrs"]:
        parts[s["node"]] = build_mesh_obj(f"{sex}_{s['node']}", s)
    for s in head["smrs"]:
        if s["node"] == "head":
            parts["head"] = build_mesh_obj(f"{sex}_head", s)
    return parts, bone_pos(body), body


def import_garment(item):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.join(MODELS, item + ".fbx"))
    obs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    assert len(obs) == 1, obs
    ob = obs[0]
    ob.name = item
    # bake transforms, then turn to face +Y like the character
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    ob.data.transform(Matrix.Rotation(math.pi, 4, "Z"))
    return ob


def verts_np(ob):
    a = np.zeros(len(ob.data.vertices) * 3)
    ob.data.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


def set_verts(ob, v):
    ob.data.vertices.foreach_set("co", np.asarray(v, dtype=float).reshape(-1))
    ob.data.update()


def group_verts(ob, names, thresh=0.3):
    """Vertex coords whose summed weight in `names` >= thresh."""
    ids = {ob.vertex_groups[n].index for n in names if n in ob.vertex_groups}
    out = []
    for v in ob.data.vertices:
        if sum(g.weight for g in v.groups if g.group in ids) >= thresh:
            out.append(v.co[:])
    return np.array(out)


def islands(ob):
    """Connected components -> list of vertex index arrays."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    seen = np.zeros(len(bm.verts), bool)
    comps = []
    for v in bm.verts:
        if seen[v.index]:
            continue
        stack, comp = [v], []
        seen[v.index] = True
        while stack:
            x = stack.pop()
            comp.append(x.index)
            for e in x.link_edges:
                o = e.other_vert(x)
                if not seen[o.index]:
                    seen[o.index] = True
                    stack.append(o)
        comps.append(np.array(comp))
    bm.free()
    return sorted(comps, key=len, reverse=True)


def render(path, objs, center, size, angles=(0, 90, 180), res=420):
    """Orthographic workbench renders around `center`, side by side into one PNG."""
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "TEXTURE"
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.film_transparent = False
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o not in objs
    cam = bpy.data.objects.get("vc_cam") or bpy.data.objects.new("vc_cam", bpy.data.cameras.new("vc_cam"))
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = size
    tiles = []
    for a in angles:
        r = math.radians(a) if a != "top" else 0
        d = Vector((math.sin(r), math.cos(r), 0)) if a != "top" else Vector((0, 0.0001, 1))  # a=0: camera at +Y
        cam.location = Vector(center) + d * 5
        cam.rotation_euler = (d * -1).to_track_quat("-Z", "Y").to_euler()
        p = path + f"_{a}.png"
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        tiles.append(p)
    return tiles


def body_material(ob, color=(0.8, 0.65, 0.55, 1)):
    m = bpy.data.materials.new("skin")
    m.diffuse_color = color
    ob.data.materials.clear()
    ob.data.materials.append(m)
    bpy.context.scene.display.shading.color_type = "TEXTURE"
