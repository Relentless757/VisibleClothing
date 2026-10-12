"""Flatten _work/out/<Item>_<sex>.json (+ skeletons) into JsonUtility-friendly files under
unity/Assets/VC/Data, and copy the textures to unity/Assets/VC/Textures.

python tools/pack_unity.py [items...]   (default: every _work/out/*_male.json / *_female.json)
With VC_PACK=<pack folder>: <pack>/build/out -> unity/Assets/VC/Packs/<name>/ (see tools/vc_pack.py).
"""
import glob, json, os, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_pack
ROOT = vc_pack.ROOT
WORK = vc_pack.BASE_WORK         # the vanilla body / skeleton / heads read from the user's game
OUT = vc_pack.OUT                # fitted garments: base mod or the selected clothing pack
VC = vc_pack.UNITY_DIR           # unity/Assets/VC or unity/Assets/VC/Packs/<name>
TEX_SIZE = {}                    # texture -> max size, read by BuildClothing.cs (Data/_textures.json)


def skeleton(sex):
    d = json.load(open(os.path.join(WORK, f"body_{sex}.json")))
    nodes = d["nodes"]
    start = next(i for i, n in enumerate(nodes) if n["name"] == "Origin")
    keep, idx = [], {}
    for i, n in enumerate(nodes):  # Origin and everything under it (nodes are in DFS order)
        if i == start or n["parent"] in idx:
            idx[i] = len(keep)
            keep.append(n)
    return dict(names=[n["name"] for n in keep],
                parents=[idx.get(n["parent"], -1) for n in keep],
                pos=[x for n in keep for x in n["pos"]],
                rot=[x for n in keep for x in n["rot"]],
                scl=[x for n in keep for x in n["scl"]])


def pack(path):
    d = json.load(open(path))
    item, sex = d["item"], d["sex"]
    kind = vc_pack.kind_of(item)
    if kind is None:
        print(f"{item}: unknown item, skipped"); return
    if vc_pack.merge_target(item):
        return  # pants merged into their outfit's prefab (the chest slot draws one model)
    for f in glob.glob(os.path.join(OUT, f"*_{sex}.json")):   # pants that belong to this outfit
        other = os.path.basename(f)[:-len(f"_{sex}.json")]
        if vc_pack.merge_target(other) == item:
            d["parts"] = d["parts"] + json.load(open(f))["parts"]
    small = kind in ("head", "hands", "feet")   # small on screen: 1K textures; RMOE (low-frequency data) always 1K
    for p in d["parts"]:
        stem = os.path.splitext(p["texture"])[0]
        TEX_SIZE[stem] = 1024 if small else max(TEX_SIZE.get(stem, 0), 2048)
        TEX_SIZE[stem + "_n"] = TEX_SIZE[stem]
        TEX_SIZE[stem + "_rmoe"] = 1024
    bones, bone_i = [], {}
    main_acc, child_acc = new_acc(), new_acc()
    for p in d["parts"]:
        # "strings" parts go to a child mesh that gets a Cloth component in Unity
        cloth = p["part"] == "strings"
        add_part(child_acc if cloth else main_acc, single_sheet(p) if cloth else p, bones, bone_i, double=not cloth)
    sx = sex.capitalize()
    if kind in ("outfit", "shirt", "pants"):
        # first person: SDCSUtils.RemoveFPViewObstructingGearPolygons keeps a triangle only if all 3 verts have colour r == 0
        # mark collar / shoulder tops / anything near or above the neck, like vanilla gear meshes
        nodes = {n["name"]: n for n in json.load(open(os.path.join(WORK, f"body_{sex}.json")))["nodes"]}
        neck = [nodes["Neck"]["world"][i][3] for i in range(3)]
        V = main_acc["verts"]
        clip = []
        for i in range(0, len(V), 3):
            dx, dy, dz = V[i] - neck[0], V[i + 1] - neck[1], V[i + 2] - neck[2]
            clip.append(1.0 if (dx * dx + dy * dy + dz * dz) ** 0.5 < 0.17 or dy > -0.03 else 0.0)
        main_acc["clip"] = clip
        print(f"  {item} {sex}: {int(sum(clip))} verts marked for first-person removal")
    if kind == "head":
        main_acc["shapeNames"], main_acc["shapeDeltas"] = head_shapes(main_acc["verts"], sex)
        print(f"  {item} {sex}: {len(main_acc['shapeNames'])} head-fit blend shapes")
    rec = dict(prefab=f"gear{sx}{item}", part=vc_pack.PART_OF_KIND[kind], sex=sx, boneNames=bones, **main_acc)
    if child_acc["verts"]:
        rec["child"] = dict(name="strings", **child_acc)
    os.makedirs(os.path.join(VC, "Data"), exist_ok=True)
    json.dump(rec, open(os.path.join(VC, "Data", f"{item}_{sex}.json"), "w"))
    extra = f", cloth child {len(child_acc['verts'])//3} verts" if child_acc["verts"] else ""
    print(f"{item} {sex}: {len(main_acc['verts'])//3} verts, {len(main_acc['subs'])} submeshes, {len(bones)} bones{extra}")


def head_shapes(Vflat, sex):
    """Hats are fitted to the reference head (vc_blender.REF_HEAD, White 04). One blend shape per real head moves the
    hat by that head's offset from the reference at the nearest head points, so it sits on every head as it was
    fitted on the reference (White 04's own shape is zero). The DLL turns on the shape named after the character's head (race + variant, e.g. "asian02").
    Hat parts far from the head (more than ~4.5 cm) keep their shape."""
    import numpy as np
    from scipy.spatial import cKDTree
    head = lambda path: np.array(next(x for x in json.load(open(path))["smrs"] if x["node"] == "head")["verts"])
    env_path = os.path.join(WORK, "heads", f"{sex}_white04.json")   # the reference head hats are fitted to
    if not os.path.exists(env_path):
        return [], []
    E = head(env_path)
    P = np.array(Vflat).reshape(-1, 3)
    d, idx = cKDTree(E).query(P, k=6)
    w = 1.0 / (d + 1e-4)
    w /= w.sum(1, keepdims=True)
    t = np.clip((0.045 - d[:, 0]) / (0.045 - 0.02), 0, 1)
    fade = t * t * (3 - 2 * t)
    names, deltas = [], []
    for f in sorted(glob.glob(os.path.join(WORK, "heads", f"{sex}_*.json"))):
        V = head(f)
        if len(V) != len(E):   # a variant with its own topology: match by nearest vertex (as head_envelope.py)
            V = V[cKDTree(V).query(E)[1]]
        D = ((V - E)[idx] * w[..., None]).sum(1) * fade[:, None]
        names.append(os.path.basename(f)[len(sex) + 1:-5].lower())
        deltas += np.round(D, 6).reshape(-1).tolist()
    return names, deltas


def new_acc():
    return dict(verts=[], normals=[], uv=[], boneIdx=[], boneW=[], subs=[])


def single_sheet(p):
    """Cloth strings: the model's strings are flat closed tubes (front, back and rim faces). Unity Cloth moves both
    sides independently, so they pass through each other and the back side flickers through (dark patches). The game's
    cloth shader (Game/CharacterCloth) draws both sides of a face, like vanilla's single-layer capes: keep only the
    faces looking forward (Unity +z), compacted."""
    import numpy as np
    N = np.array(p["normals"]); T = np.array(p["tris"])
    T = T[N[T].mean(1)[:, 2] > 0]          # exported vertex normals point outward; +z = the character's front
    used = sorted(set(T.reshape(-1).tolist()))
    remap = {o: i for i, o in enumerate(used)}
    q = dict(p)
    for k in ("verts", "normals", "uv", "weights"):
        q[k] = [p[k][i] for i in used]
    q["tris"] = [[remap[a] for a in t] for t in T.tolist()]
    print(f"  strings: single sheet {len(q['tris'])} of {len(p['tris'])} faces")
    return q


def add_part(acc, p, bones, bone_i, double=True):
    # double-sided: Tripo garments are open shells, so add an inward-facing copy of every face.
    # Not for cloth pieces: Cloth welds each vertex with its copy and recomputes normals, the opposite
    # faces cancel out and the strings flicker black (the strings are closed tubes anyway).
    p = dict(p)
    if double:
        nv = len(p["verts"])
        p["verts"] = p["verts"] + p["verts"]
        p["normals"] = p["normals"] + [[-x for x in n] for n in p["normals"]]
        p["uv"] = p["uv"] + p["uv"]
        p["weights"] = p["weights"] + p["weights"]
        p["tris"] = p["tris"] + [[t[0] + nv, t[2] + nv, t[1] + nv] for t in p["tris"]]
    base = len(acc["verts"]) // 3
    acc["verts"] += [x for v in p["verts"] for x in v]
    acc["normals"] += [x for v in p["normals"] for x in v]
    acc["uv"] += [x for v in p["uv"] for x in v]
    for ws in p["weights"]:
        ws = (ws + [["", 0.0]] * 4)[:4]
        for name, w in ws:
            if name and name not in bone_i:
                bone_i[name] = len(bones)
                bones.append(name)
            acc["boneIdx"].append(bone_i.get(name, 0))
            acc["boneW"].append(w)
    acc["subs"].append(dict(texture=os.path.splitext(p["texture"])[0], tris=[base + i for t in p["tris"] for i in t]))
    os.makedirs(os.path.join(VC, "Textures"), exist_ok=True)
    stem = os.path.splitext(p["texture"])[0]
    for name in (p["texture"], stem + "_n.png", stem + "_rmoe.png"):   # albedo + optional normal + RMOE
        src, dst = os.path.join(OUT, name), os.path.join(VC, "Textures", name)
        if os.path.exists(src) and (not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src)):
            shutil.copy2(src, dst)
    for old in (stem + "_ms.png", stem + "_ms.png.meta"):   # Standard-shader metal/smooth map (before RMOE)
        if os.path.exists(os.path.join(VC, "Textures", old)):
            os.remove(os.path.join(VC, "Textures", old))


def main():
    os.makedirs(os.path.join(VC, "Data"), exist_ok=True)
    for sex in ("male", "female"):
        json.dump(skeleton(sex), open(os.path.join(VC, "Data", f"skeleton_{sex}.json"), "w"))
    items = sys.argv[1:]
    files = sorted(glob.glob(os.path.join(OUT, "*_male.json")) + glob.glob(os.path.join(OUT, "*_female.json")))
    for f in files:
        if not items or any(os.path.basename(f).startswith(i + "_") for i in items):
            pack(f)
    old = os.path.join(VC, "Data", "_textures.json")
    sizes = dict(json.load(open(old)) if os.path.exists(old) and items else {}, **TEX_SIZE)
    json.dump(sizes, open(old, "w"), indent=0)


if __name__ == "__main__":
    main()
