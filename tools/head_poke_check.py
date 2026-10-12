"""Collar check: head-mesh verts (all 16 variants per sex) at or through each outfit (python tools/head_poke_check.py _work)."""
import json, sys, numpy as np, glob, os
W = sys.argv[1]
for sex in ("male", "female"):
    body = json.load(open(f"{W}/body_{sex}.json"))
    nodes = {n["name"]: n for n in body["nodes"]}
    nk = np.array([nodes["Neck"]["world"][i][3] for i in range(3)])
    heads = sorted(glob.glob(f"{W}/heads/{sex}_*.json"))
    for item in ("ClothingOutfitT1", "ClothingOutfitT2", "ClothingOutfitT3"):
        g = json.load(open(f"{W}/out/{item}_{sex}.json"))["parts"][0]
        G = np.array(g["verts"]); N = np.array(g["normals"])
        N /= np.linalg.norm(N, axis=1, keepdims=True) + 1e-9
        sel = G[:, 1] > nk[1] - 0.12
        Gs, Ns = G[sel], N[sel]
        worst_all = []
        for hf in heads:
            hs = next(s for s in json.load(open(hf))["smrs"] if s["node"] == "head")
            H = np.array(hs["verts"])
            H = H[(H[:, 1] < nk[1] + 0.03)]
            d2 = ((H[:, None, :] - Gs[None, :, :]) ** 2).sum(-1)
            j = d2.argmin(1)
            dist = np.sqrt(d2[np.arange(len(H)), j])
            sd = ((H - Gs[j]) * Ns[j]).sum(1)
            covered = dist < 0.015            # garment really is over this head vertex
            poke = covered & (sd > -0.001)    # head skin at/through the shirt surface (within 1 mm)
            worst_all.append((os.path.basename(hf)[:-5], int(poke.sum()), float(sd[covered].max()) if covered.any() else 0))
        tot = sum(w[1] for w in worst_all)
        print(f"{sex} {item}: head-mesh neck verts at/through the shirt (summed over {len(heads)} heads): {tot}; worst head {max(worst_all, key=lambda w: w[1])}")
