"""Read the vanilla player body + skeleton from the user's own game install into a local JSON
(for fitting only; output stays in _work/, never shipped)."""
import UnityPy, sys, json, numpy as np
from UnityPy.helpers.MeshHelper import MeshHandler

bundle, want, out = sys.argv[1:4]
env = UnityPy.load(bundle)

def trs(t):
    p, r, s = t.m_LocalPosition, t.m_LocalRotation, t.m_LocalScale
    return [p.x, p.y, p.z], [r.x, r.y, r.z, r.w], [s.x, s.y, s.z]

def mat(p, q, s):
    x, y, z, w = q
    R = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                  [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                  [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
    M = np.eye(4); M[:3, :3] = R * np.array(s); M[:3, 3] = p
    return M

root = None
for p, o in env.container.items():
    if p.endswith(want) and o.type.name == "GameObject":
        g = o.read()
        if g.m_Transform.read().m_Father.path_id == 0:
            root = g; break
assert root, "root not found"

nodes, smrs = [], []
def walk(go, parent, W):
    t = go.m_Transform.read()
    p, q, s = trs(t)
    Wc = W @ mat(p, q, s)
    idx = len(nodes)
    nodes.append(dict(name=go.m_Name, parent=parent, pos=p, rot=q, scl=s, world=Wc.tolist(), path_id=t.object_reader.path_id))
    for c in go.m_Component:
        if c.component.type.name == "SkinnedMeshRenderer":
            smrs.append((idx, c.component.read()))
    for ch in t.m_Children:
        walk(ch.read().m_GameObject.read(), idx, Wc)
walk(root, -1, np.eye(4))
pid2name = {n["path_id"]: n["name"] for n in nodes}

out_smrs = []
for idx, smr in smrs:
    mesh = smr.m_Mesh.read()
    h = MeshHandler(mesh); h.process()
    tris = []
    for sub in h.get_triangles():
        tris.extend([list(t) for t in sub])
    bones = [pid2name.get(b.path_id, "?") for b in smr.m_Bones]
    out_smrs.append(dict(
        node=nodes[idx]["name"], mesh=mesh.m_Name,
        verts=[list(v) for v in h.m_Vertices], normals=[list(v) for v in (h.m_Normals or [])],
        uv=[list(v) for v in (h.m_UV0 or [])], tris=tris,
        bw=[list(v) for v in (h.m_BoneWeights or [])], bi=[list(map(int, v)) for v in (h.m_BoneIndices or [])],
        bindposes=[np.array([[m.e00, m.e01, m.e02, m.e03], [m.e10, m.e11, m.e12, m.e13],
                             [m.e20, m.e21, m.e22, m.e23], [m.e30, m.e31, m.e32, m.e33]]).tolist() for m in mesh.m_BindPose],
        bones=bones, root_bone=pid2name.get(smr.m_RootBone.path_id),
        materials=[]))
    print(nodes[idx]["name"], mesh.m_Name, len(h.m_Vertices), "verts", len(tris), "tris", len(bones), "bones", "weights" if h.m_BoneWeights else "NO WEIGHTS")
json.dump(dict(nodes=[{k: v for k, v in n.items() if k != "path_id"} for n in nodes], smrs=out_smrs), open(out, "w"))
print(len(nodes), "nodes ->", out)
