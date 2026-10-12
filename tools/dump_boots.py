"""Vanilla boot meshes (feet / feet_A parts) -> _work/vanilla_boots_<sex>.json, for fitting pants over them.
python tools/dump_boots.py _work/vanilla_boots_female.json <game>/Data/Addressables/Standalone/player_assets_entities/player/female/gear/*.bundle
"""
import UnityPy, sys, json, numpy as np, os
from UnityPy.helpers.MeshHelper import MeshHandler
out = sys.argv[1]; bundles = sys.argv[2:]
res = {}
for b in bundles:
    env = UnityPy.load(b)
    for o in env.objects:
        if o.type.name != "SkinnedMeshRenderer": continue
        smr = o.read(); go = smr.m_GameObject.read()
        if go.m_Name not in ("feet", "feet_A"): continue

        mesh = smr.m_Mesh.read(); h = MeshHandler(mesh); h.process()
        tris = [list(t) for sub in h.get_triangles() for t in sub]
        key = os.path.basename(b)[:-7] + "_" + go.m_Name
        if key in res: continue
        res[key] = dict(verts=[list(v) for v in h.m_Vertices], normals=[list(v) for v in h.m_Normals], tris=tris)
        print(key, len(h.m_Vertices))
json.dump(res, open(out, "w"))
