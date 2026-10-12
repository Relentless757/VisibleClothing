"""Female clothing from the male bake: body/feet/head share topology between sexes, so keep the male
faces, UVs and texture and only swap in female positions, normals and skin weights.

python tools/derive_female.py <Item>   (reads _work/out/<Item>_male.json [+ <Item>_female.json for parts
                                        whose topology differs, e.g. hands], writes <Item>_female.json)
"""
import json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "_work")
OUT = os.path.join(WORK, "out")


def smr_by_node(path):
    d = json.load(open(os.path.join(WORK, path)))
    return {s["node"]: s for s in d["smrs"]}


def main(item):
    male = json.load(open(os.path.join(OUT, f"{item}_male.json")))
    fm, mm = smr_by_node("body_female.json"), smr_by_node("body_male.json")
    fm.update({k: v for k, v in smr_by_node("head_female.json").items() if k == "head"})
    mm.update({k: v for k, v in smr_by_node("head_male.json").items() if k == "head"})
    own_path = os.path.join(OUT, f"{item}_female.json")
    own = {p["part"]: p for p in json.load(open(own_path))["parts"]} if os.path.exists(own_path) else {}
    out = dict(item=item, sex="female", parts=[])
    for p in male["parts"]:
        f, m = fm[p["part"]], mm[p["part"]]
        if f["tris"] != m["tris"]:
            if p["part"] in own:
                out["parts"].append(own[p["part"]])
                print(f"{p['part']}: topology differs -> female bake")
            else:
                print(f"{p['part']}: topology differs and no female bake! skipped")
            continue
        src = np.array(p["src"])
        V, N = np.array(f["verts"]), np.array(f["normals"])
        q = dict(p)
        q["verts"] = (V[src] + N[src] * p["offset"]).tolist()
        q["normals"] = N[src].tolist()
        bones = f["bones"]
        ws = []
        for i in src:
            pairs = sorted(((w, bones[b]) for w, b in zip(f["bw"][i], f["bi"][i]) if w > 0), reverse=True)[:4]
            t = sum(w for w, _ in pairs) or 1
            ws.append([[n, w / t] for w, n in pairs])
        q["weights"] = ws
        out["parts"].append(q)
        print(f"{p['part']}: derived {len(src)} verts from male")
    json.dump(out, open(own_path, "w"))


if __name__ == "__main__":
    for it in sys.argv[1:]:
        main(it)
