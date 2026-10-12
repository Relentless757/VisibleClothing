"""Head envelope per sex: hats must clear every face/head shape the player can pick, not just White 01.

python tools/head_envelope.py   ->  _work/head_env_{male,female}.json  (same format as head_<sex>.json)

All variants share White 01's triangle layout (checked); for each vertex we keep White 01's position pushed out
along its normal by the largest amount any variant sticks out there. A variant with a different vertex count
is matched by nearest vertex instead.
"""
import glob, json, os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "_work")


def head_smr(path):
    return next(s for s in json.load(open(path))["smrs"] if s["node"] == "head")


for sex in ("male", "female"):
    base_doc = json.load(open(os.path.join(WORK, f"head_{sex}.json")))
    base = next(s for s in base_doc["smrs"] if s["node"] == "head")
    V0, N0 = np.array(base["verts"]), np.array(base["normals"])
    push = np.zeros(len(V0))
    for f in sorted(glob.glob(os.path.join(WORK, "heads", f"{sex}_*.json"))):
        h = head_smr(f)
        V = np.array(h["verts"])
        if len(V) != len(V0):  # different vertex count: nearest-vertex correspondence
            idx = np.array([np.argmin(np.linalg.norm(V - v, axis=1)) for v in V0])
            V = V[idx]
            print(f"  {os.path.basename(f)}: {len(h['verts'])} verts, matched by nearest vertex")
        push = np.maximum(push, ((V - V0) * N0).sum(1))
    env = dict(base)
    env["verts"] = (V0 + N0 * push[:, None]).tolist()
    out = dict(base_doc)
    out["smrs"] = [env if s["node"] == "head" else s for s in base_doc["smrs"]]
    json.dump(out, open(os.path.join(WORK, f"head_env_{sex}.json"), "w"))
    print(f"{sex}: envelope over {len(glob.glob(os.path.join(WORK, 'heads', sex + '_*.json')))} heads, "
          f"max push {push.max()*1000:.1f} mm, mean {push.mean()*1000:.1f} mm, >5 mm on {(push > 0.005).mean():.0%} of verts")
