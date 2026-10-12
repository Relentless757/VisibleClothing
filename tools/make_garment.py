"""Turn an aligned Tripo garment into a body-conforming, body-weighted clothing mesh.

blender -b --factory-startup -P tools/make_garment.py -- <Item> <male|female> [--render]

For each body part the garment covers (body / hands / feet / head):
  1. copy that vanilla part, inflate it along its normals by `offset`
  2. keep only faces that a ray along the normal finds garment near (BVH)
  3. remap the kept faces' UVs to fill 0..1, then Cycles-bake the garment's colour (selected-to-active)
     plus a coverage mask (-> alpha cutout)
  4. weights are the vanilla part's own skin weights, so the clothing deforms exactly like the skin
Output: _work/out/<Item>_<sex>.json + one PNG per part.
"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_blender as vb
import fit
import numpy as np
import bpy, bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

OUT = os.path.join(vb.WORK, "out")

# which vanilla parts a garment kind may cover, and how far to inflate each (metres)
KIND_PARTS = {
    "outfit": [("body", 0.006)],
    "shirt": [("body", 0.006)],
    "head": [("head", 0.012), ("body", 0.007)],
    "hands": [("hands", 0.003), ("body", 0.005)],
    "feet": [("feet", 0.003), ("body", 0.004)],
}
TEX = {"body": 2048, "head": 1024, "hands": 1024, "feet": 1024}
REACH_OUT, REACH_IN = 0.12, 0.07  # how far outside / inside the inflated skin we look for garment


def inflate_copy(src, offset, name):
    me = src.data.copy()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    for gname in [g.name for g in src.vertex_groups]:
        ob.vertex_groups.new(name=gname)
    for v in src.data.vertices:  # vertex groups are per-object: copy weights
        for g in v.groups:
            ob.vertex_groups[src.vertex_groups[g.group].name].add([v.index], g.weight, "REPLACE")
    me.update()
    n = np.zeros(len(me.vertices) * 3)
    me.attributes["unormal"].data.foreach_get("vector", n)
    co = vb.verts_np(ob) + n.reshape(-1, 3) * offset
    vb.set_verts(ob, co)
    return ob


def covered_faces(ob, bvhs, min_hits=1):
    me = ob.data
    keep = []
    vhit = np.zeros(len(me.vertices), bool)
    for v in me.vertices:
        o = v.co + v.normal * REACH_OUT
        for bvh in bvhs:
            loc, nrm, idx, dist = bvh.ray_cast(o, -v.normal, REACH_OUT + REACH_IN)
            if loc is not None:
                vhit[v.index] = True
                break
    for p in me.polygons:
        if vhit[list(p.vertices)].sum() >= min_hits:
            keep.append(p.index)
    return keep


def keep_only(ob, faces):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    ks = set(faces)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in ks], context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def normalise_uvs(ob, pad=0.01):
    uv = ob.data.uv_layers.active.data
    a = np.zeros(len(uv) * 2)
    uv.foreach_get("uv", a)
    a = a.reshape(-1, 2)
    lo, hi = a.min(0), a.max(0)
    a = (a - lo) / np.maximum(hi - lo, 1e-6) * (1 - 2 * pad) + pad
    uv.foreach_set("uv", a.reshape(-1))


def garment_material(g, mode):
    """mode 'color': emission = garment basecolor;  'mask': emission = white."""
    img = next((i for i in bpy.data.images if i.size[0] > 0 and i.name != "Render Result" and not i.name.startswith("vc_")), None)
    m = bpy.data.materials.new("vc_src_" + mode)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(em.outputs[0], out.inputs[0])
    if mode == "color":
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.links.new(tex.outputs[0], em.inputs[0])
    else:
        em.inputs[0].default_value = (1, 1, 1, 1)
    g.data.materials.clear()
    g.data.materials.append(m)


def target_material(ob, img):
    m = bpy.data.materials.new("vc_tgt_" + ob.name)
    m.use_nodes = True
    nt = m.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.nodes.active = tex
    ob.data.materials.clear()
    ob.data.materials.append(m)


def bake(sources, target, size, mode):
    img = bpy.data.images.new(f"vc_{target.name}_{mode}", size, size, alpha=True, float_buffer=False)
    img.generated_color = (0, 0, 0, 0)
    target_material(target, img)
    for s in sources:
        garment_material(s, mode)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 1
    sc.cycles.device = "CPU"
    bpy.ops.object.select_all(action="DESELECT")
    for s in sources:
        s.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.bake(type="EMIT", use_selected_to_active=True, cage_extrusion=REACH_OUT,
                        max_ray_distance=REACH_OUT + REACH_IN, margin=0, use_clear=True, target="IMAGE_TEXTURES")
    px = np.array(img.pixels[:]).reshape(size, size, 4)
    return px


def dilate(rgb, mask, steps=12):
    """Bleed colour outward from covered texels so mip-mapped cutout edges don't go dark."""
    rgb = rgb.copy()
    m = mask.copy()
    for _ in range(steps):
        acc = np.zeros_like(rgb)
        cnt = np.zeros(m.shape)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sm = np.roll(m, (dy, dx), (0, 1))
            acc += np.roll(rgb, (dy, dx), (0, 1)) * sm[..., None]
            cnt += sm
        grow = (~m) & (cnt > 0)
        rgb[grow] = acc[grow] / cnt[grow][:, None]
        m = m | grow
    return rgb


def save_png(path, px):
    from PIL import Image  # noqa: blender's python may lack PIL -> fallback below
    Image.fromarray((np.clip(px[::-1], 0, 1) * 255).astype(np.uint8), "RGBA").save(path)


def save_png_bpy(path, px):
    h, w = px.shape[:2]
    img = bpy.data.images.new("vc_save", w, h, alpha=True)
    img.pixels[:] = px.reshape(-1)
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def export_part(ob, part, tex_name):
    me = ob.data
    me.calc_loop_triangles()
    uvl = me.uv_layers.active.data
    # split vertices per loop so UV seams survive (Unity wants one UV per vertex)
    key2i, verts, normals, uvs, weights, tris = {}, [], [], [], [], []
    gnames = [g.name for g in ob.vertex_groups]
    un = me.attributes["unormal"].data
    ov = me.attributes["orig_vi"].data
    src = []
    for lt in me.loop_triangles:
        tri = []
        for li in lt.loops:
            loop = me.loops[li]
            vi = loop.vertex_index
            uv = tuple(round(x, 6) for x in uvl[li].uv)
            k = (vi, uv)
            if k not in key2i:
                v = me.vertices[vi]
                key2i[k] = len(verts)
                verts.append([v.co.x, v.co.z, v.co.y])           # back to Unity space
                nn = un[vi].vector
                normals.append([nn.x, nn.z, nn.y])
                src.append(ov[vi].value)
                uvs.append(list(uv))
                ws = sorted(((g.weight, gnames[g.group]) for g in v.groups if g.weight > 0), reverse=True)[:4]
                tot = sum(w for w, _ in ws) or 1
                weights.append([[n, w / tot] for w, n in ws])
            tri.append(key2i[k])
        tris.append([tri[0], tri[2], tri[1]])  # back to Unity winding
    return dict(part=part, texture=tex_name, src=src, verts=verts, normals=normals, uv=uvs, weights=weights, tris=tris)


def dominant_bones(ob):
    names = [g.name for g in ob.vertex_groups]
    out = []
    for v in ob.data.vertices:
        best = max(v.groups, key=lambda g: g.weight, default=None)
        out.append(names[best.group] if best else "")
    return out


def split_by_faces(ob, face_sets):
    """Duplicate ob once per face set (keeping only those faces)."""
    objs = []
    for name, faces in face_sets:
        o = ob.copy()
        o.data = ob.data.copy()
        o.name = f"{ob.name}_{name}"
        bpy.context.scene.collection.objects.link(o)
        keep_only(o, faces)
        objs.append(o)
    return objs


def bake_regions(region_objs, size):
    """Bake every (target, sources) pair into one shared image; returns RGBA array with coverage alpha."""
    img_c = bpy.data.images.new("vc_color", size, size, alpha=True)
    img_m = bpy.data.images.new("vc_mask", size, size, alpha=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 1
    sc.cycles.device = "CPU"
    for img, mode in ((img_c, "color"), (img_m, "mask")):
        img.generated_color = (0, 0, 0, 0)
        for i, (tgt, sources) in enumerate(region_objs):
            target_material(tgt, img)
            for s in sources:
                garment_material(s, mode)
            bpy.ops.object.select_all(action="DESELECT")
            for s in sources:
                s.select_set(True)
            tgt.select_set(True)
            bpy.context.view_layer.objects.active = tgt
            bpy.ops.object.bake(type="EMIT", use_selected_to_active=True, cage_extrusion=REACH_OUT,
                                max_ray_distance=REACH_OUT + REACH_IN, margin=0, use_clear=(i == 0),
                                target="IMAGE_TEXTURES")
    col = np.array(img_c.pixels[:]).reshape(size, size, 4)
    msk = np.array(img_m.pixels[:]).reshape(size, size, 4)
    mask = msk[..., 0] > 0.5
    return np.dstack([dilate(col[..., :3], mask), mask.astype(float)]), mask.mean()


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    item, sex = argv[0], argv[1]
    c = fit.CFG[item]
    os.makedirs(OUT, exist_ok=True)
    vb.clear()
    parts, B, data = vb.load_body(sex)
    g = vb.import_garment(item)
    regions = getattr(fit, "fit_" + c["kind"])(g, parts, B, c)
    if c.get("mirror"):  # single left glove -> add a mirrored copy for the right hand
        name, srcs, sel = regions[0]
        m = fit.copy_obj(g, "mirrored")
        co = vb.verts_np(m)
        co[:, 0] *= -1
        vb.set_verts(m, co)
        m.data.flip_normals()
        regions[0] = (name, srcs + [m], sel)
    dg = bpy.context.evaluated_depsgraph_get()
    result = dict(item=item, sex=sex, parts=[])
    made, all_sources = [], [s for r in regions for s in r[1]]
    for part, offset in c.get("parts", KIND_PARTS[c["kind"]]):
        ob = inflate_copy(parts[part], offset, f"vc_{part}")
        dom = dominant_bones(ob)
        zmin, zmax = c.get("_zmin", c.get("zmin", -9)), c.get("zmax", 9)
        face_sets, union = [], set()
        for name, srcs, sel in regions:
            bvhs = [BVHTree.FromObject(s, dg) for s in srcs]
            cov = set(covered_faces(ob, bvhs))
            fs = [p.index for p in ob.data.polygons
                  if p.index in cov and p.index not in union
                  and zmin <= p.center.z <= zmax and p.normal.z >= c.get("_max_down", -2)
                  and sel([dom[v] for v in p.vertices])]
            union.update(fs)
            face_sets.append((name, fs, srcs))
        print(f"part {part}: " + ", ".join(f"{n}={len(f)}" for n, f, _ in face_sets) + f" of {len(ob.data.polygons)}")
        if len(union) < 20:
            bpy.data.objects.remove(ob)
            continue
        keep_only(ob, sorted(union))  # indices change: rebuild face sets by centre lookup
        normalise_uvs(ob)
        # re-derive region membership on the trimmed mesh
        dom = dominant_bones(ob)
        assigned = set()
        sets = []
        for name, srcs, sel in regions:
            fs = [p.index for p in ob.data.polygons if p.index not in assigned and sel([dom[v] for v in p.vertices])]
            assigned.update(fs)
            sets.append((name, fs, srcs))
        robjs = [(o, srcs) for o, (_, fs, srcs) in zip(split_by_faces(ob, [(n, f) for n, f, _ in sets]), sets) if len(o.data.polygons)]
        px, cov = bake_regions(robjs, TEX[part])
        tex_name = f"{item}_{sex}_{part}.png"
        save_png_bpy(os.path.join(OUT, tex_name), px)
        print(f"  baked {tex_name}: coverage {cov:.2%}")
        for o, _ in robjs:
            bpy.data.objects.remove(o)
        ex = export_part(ob, part, tex_name)
        ex["offset"] = offset
        result["parts"].append(ex)
        made.append((ob, tex_name))
    with open(os.path.join(OUT, f"{item}_{sex}.json"), "w") as f:
        json.dump(result, f)
    if "--render" in argv:
        preview(made, parts, c, item, sex, all_sources)


def preview(made, parts, c, item, sex, sources):
    for ob, tex in made:
        img = bpy.data.images.load(os.path.join(OUT, tex))
        m = bpy.data.materials.new("prev")
        m.use_nodes = True
        nt = m.node_tree
        bsdf = nt.nodes["Principled BSDF"]
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = img
        nt.links.new(t.outputs[0], bsdf.inputs["Base Color"])
        nt.links.new(t.outputs[1], bsdf.inputs["Alpha"])
        ob.data.materials.clear()
        ob.data.materials.append(m)
    for o in parts.values():
        vb.body_material(o)
    k = {"shirt": "outfit"}.get(c["kind"], c["kind"])
    center = {"outfit": (0, 0, 1.2), "head": (0, 0, 1.65), "feet": (0, 0, 0.25), "hands": (-0.5, 0.15, 1.12)}[k]
    size = {"outfit": 1.4, "head": 0.55, "feet": 0.7, "hands": 0.35}[k]
    for s in sources:
        s.hide_render = True
    vis = [o for o, _ in made] + list(parts.values())
    tiles = vb.render(os.path.join(vb.WORK, f"mg_{item}_{sex}"), vis, center, size, angles=(0, 90, 180))
    print("RENDER", " ".join(tiles))


if __name__ == "__main__":
    main()
