"""Weight sanity checks: leg weights on shirts, arm weights on torso fabric, pants weighted to the other leg, gloves
bound only to the hand. python tools/weights_check.py _work/out _work"""
import json, sys, numpy as np, re
OUT = sys.argv[1]; W = sys.argv[2]
def load(item, sex): return json.load(open(f"{OUT}/{item}_{sex}.json"))
def is_leg(b): return re.match(r"(Left|Right)(UpLeg|Leg|Foot|Toe)|(Left|Right)_sup_(hip|knee)", b) is not None
def is_arm(b, side=None):
    s = "(Left|Right)" if side is None else side
    return re.match(s + r"(Arm|ForeArm|Hand)|" + s + r"_sup_(arm|elbow|wrist|index|middle|ring|pinky|thumb)", b) is not None
for sex in ("male", "female"):
    nodes = {n["name"]: n for n in json.load(open(f"{W}/body_{sex}.json"))["nodes"]}
    P = lambda b: np.array([nodes[b]["world"][i][3] for i in range(3)])
    hips_y = P("Hips")[1]
    for item in ("ClothingOutfitT1", "ClothingOutfitT2", "ClothingOutfitT3"):
        d = load(item, sex)
        for p in d["parts"]:
            V = np.array(p["verts"]); Wt = p["weights"]
            legw = np.array([sum(w for b, w in ws if is_leg(b)) for ws in Wt])
            m = legw > 0.05
            # torso verts = |x| < 0.17 (inside the shoulders), check arm influence
            torso = np.abs(V[:, 0]) < 0.17
            armw = np.array([sum(w for b, w in ws if is_arm(b)) for ws in Wt])
            ta = torso & (armw > 0.10)
            print(f"{item} {sex} part={p['part']:8s} verts={len(V)} | leg-bone w>0.05: {m.sum()} (max {legw.max():.2f}) y-range rel hips [{(V[m,1]-hips_y).min() if m.any() else 0:.3f},{(V[m,1]-hips_y).max() if m.any() else 0:.3f}] | torso(|x|<.17) verts w/ arm-bone w>0.10: {ta.sum()} (max {armw[torso].max():.2f})")
    for item in ("ClothingPantsT1", "ClothingPantsT2", "ClothingPantsT3"):
        d = load(item, sex)
        for p in d["parts"]:
            V = np.array(p["verts"]); Wt = p["weights"]
            left = V[:, 0] > 0.02   # Unity: +x = character's left? check with bones
            # determine side sign from bone positions
            lx = P("LeftUpLeg")[0]
            sideL = np.sign(V[:, 0]) == np.sign(lx)
            below = V[:, 1] < P("LeftUpLeg")[1] - 0.08
            cross = []
            for i, ws in enumerate(Wt):
                if not below[i]: continue
                opp = "Right" if sideL[i] else "Left"
                cw = sum(w for b, w in ws if b.startswith(opp) and is_leg(b))
                if cw > 0.05: cross.append(cw)
            spine = np.array([sum(w for b, w in ws if b.startswith("Spine")) for ws in Wt])
            hand = np.array([sum(w for b, w in ws if is_arm(b)) for ws in Wt])
            print(f"{item} {sex} part={p['part']:8s} verts={len(V)} | leg verts below crotch weighted >5% to the OTHER leg: {len(cross)} (max {max(cross) if cross else 0:.2f}) | arm/hand-weighted verts: {(hand>0.01).sum()} | Spine-weighted: {(spine>0.05).sum()}")
    for item in ("ClothingHandsT1", "ClothingHandsT2", "ClothingHandsT3"):
        p = load(item, sex)["parts"][0]
        Wt = p["weights"]
        only_hand = sum(1 for ws in Wt if len(ws) == 1 and ws[0][0].endswith("Hand"))
        bones = {b for ws in Wt for b, w in ws}
        fing = sum(1 for ws in Wt if any(re.search(r"Hand(Index|Middle|Ring|Pinky)[123]|HandThumb[234]", b) and w > 0.2 for b, w in ws))
        print(f"{item} {sex}: {len(Wt)} verts, {only_hand / len(Wt):.0%} bound 100% to the hand, {fing / len(Wt):.0%} with >0.2 on a finger joint, {len(bones)} bones")
