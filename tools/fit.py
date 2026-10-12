"""Fit one Tripo garment onto the vanilla body (one sex) in Blender, weight it, export JSON.

blender -b --factory-startup -P tools/fit.py -- <Item> <male|female> [--render]
"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_blender as vb
import numpy as np
import bpy
from mathutils import Vector, Matrix

TORSO = ["Hips", "Spine", "Spine1", "Spine2", "Spine3"]

# per item tuning: z ranges are fractions between named bones, filled in fit_* below
CFG = {
    "ClothingOutfitT1": dict(kind="outfit", hem=0.03, top_dz=0.0, over=["ClothingPantsT1"]),
    # sleeved shirts: landmarks in the raw garment frame (after import_garment), read off tools/raw_grid.py
    # chest = (half width at z), shoulder = joint-ish point (x, z), cuff = sleeve end centre (x, z), hem/neck z
    "ClothingOutfitT2": dict(kind="shirt", over=["ClothingPantsT2"], seam_lining=True, chest=(0.25, 0.45), shoulder=(0.25, 0.60), cuff=(0.44, 0.07), hem=0.03, neck=0.66, shoulder_top=(0.27, 0.64), armpit=(0.25, 0.43)),
    "ClothingOutfitT3": dict(kind="shirt", under=["ClothingPantsT3"], chest=(0.22, 0.45), shoulder=(0.24, 0.66), cuff=(0.47, 0.25), hem=0.02, neck=0.76, shoulder_top=(0.26, 0.71), armpit=(0.23, 0.50), side_line=(0.23, 0.02), pit_radius=0.17),
    # pants: merged into the matching ClothingOutfit piece at bundle time
    "ClothingPantsT1": dict(kind="pants", strings=True),
    "ClothingPantsT2": dict(kind="pants"),
    "ClothingPantsT3": dict(kind="pants", deep=1.12, waist=0.09),
    # hats: box fit around the skull; brim = bottom edge height (m), top = gap above the crown
    "ClothingHeadT1": dict(kind="head", brim=1.715, ring=1.745, top=0.025, wide=1.14, deep=1.08, upright=True, tilt=12, unclip_zmin=1.75),
    "ClothingHeadT2": dict(kind="head", brim=1.715, ring=1.745, top=0.025, wide=1.14, deep=1.08, upright=True, tilt=12, unclip_zmin=1.75),
    "ClothingHeadT3": dict(kind="head", brim=1.43, ring=1.73, top=0.008, wide=1.0, deep=1.0, face_clear=0.004, face_move_max=0.008, unclip_reach=0.015, neck_tight=0.03, neck_gap=0.003, under=["ClothingOutfitT1", "ClothingOutfitT2", "ClothingOutfitT3"], kind_over=dict(loose=0.008, gap=0.003, unclip_smooth=4, refit_female=False)),
    "ClothingFeetT1": dict(kind="feet"),
    "ClothingFeetT2": dict(kind="feet"),
    "ClothingFeetT3": dict(kind="feet"),
    # gloves (left, raw frame): fingers +Y, back of hand +Z, thumb +X; knuckle line y and width across it
    "ClothingHandsT1": dict(kind="hands", knuckle=(0.38, 0.37)),
    "ClothingHandsT2": dict(kind="hands", knuckle=(0.15, 0.36), wide=1.05, fingers=dict(
        Thumb=((0.10, -0.133), (0.317, 0.0)), Index=((0.042, 0.117), (0.05, 0.475)), Middle=((-0.075, 0.117), (-0.083, 0.49)),
        Ring=((-0.183, 0.117), (-0.2, 0.433)), Pinky=((-0.267, 0.108), (-0.29, 0.30)))),
    # T3 re-export (2026-10-11): upright pose -> tools/frames/ClothingHandsT3.json rotates it flat first
    "ClothingHandsT3": dict(kind="hands", knuckle=(0.09, 0.53), kind_over=dict(loose=0.01), fingers=dict(
        Thumb=((0.20, -0.15), (0.475, 0.008)), Index=((0.15, 0.10), (0.20, 0.533)), Middle=((0.0, 0.10), (0.0, 0.617)),
        Ring=((-0.117, 0.10), (-0.15, 0.55)), Pinky=((-0.225, 0.083), (-0.275, 0.45)))),
}

# a clothing pack (VC_PACK) brings its own items: hand-fitted in its fitting file, options from its pack.json
if _pack_items := __import__("vc_pack").items():
    CFG = _pack_items


def slice_interval(V, z, dz, axis, center=0.0):
    """Extent along `axis` of the connected run of verts around `center` in slab |z-z0|<dz."""
    s = V[np.abs(V[:, 2] - z) < dz][:, axis]
    if len(s) == 0:
        return None
    s = np.sort(s)
    i = np.searchsorted(s, center)
    i = min(max(i, 0), len(s) - 1)
    lo = hi = i
    gap = 0.03
    while lo > 0 and s[lo] - s[lo - 1] < gap:
        lo -= 1
    while hi < len(s) - 1 and s[hi + 1] - s[hi] < gap:
        hi += 1
    return s[lo], s[hi]


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def rot_about(P, pivot, axis, ang):
    R = np.array(Matrix.Rotation(ang, 3, Vector(axis)))
    return (P - pivot) @ R.T + pivot


def repose_sleeves(G, B, inner=0.13, outer=0.24):
    """Rotate each sleeve (frontal plane, then sagittal) about the shoulder so its axis lies on the arm bone line."""
    for side, sgn in (("Left", -1), ("Right", 1)):
        sh, el, ha = (np.array(B[side + n]) for n in ("Arm", "ForeArm", "Hand"))
        arm_dir = (ha - sh) / np.linalg.norm(ha - sh)
        x = G[:, 0] * sgn
        m = x > outer
        if m.sum() < 30:
            continue
        S = G[m]
        c = S.mean(0)
        u, sv, vt = np.linalg.svd(S - c)
        d = vt[0] * np.sign(vt[0][0] * sgn)
        w = smoothstep(inner, outer, x)[:, None]
        # frontal (XZ) angle, rotate about Y through the shoulder joint
        a_g = math.atan2(d[2], abs(d[0])); a_b = math.atan2(arm_dir[2], abs(arm_dir[0]))
        ang = (a_b - a_g) * -sgn
        G = G * (1 - w) + rot_about(G, sh, (0, 1, 0), ang) * w
        # sagittal (forward/back) angle about Z
        S2 = G[m]; c2 = S2.mean(0); u, sv, vt = np.linalg.svd(S2 - c2); d2 = vt[0] * np.sign(vt[0][0] * sgn)
        b_g = math.atan2(d2[1], abs(d2[0])); b_b = math.atan2(arm_dir[1], abs(arm_dir[0]))
        G = G * (1 - w) + rot_about(G, sh, (0, 0, 1), (b_b - b_g) * -sgn) * w
        # move sleeve centreline onto the bone line
        c3 = G[m].mean(0)
        t = np.dot(c3 - sh, arm_dir)
        off = (sh + t * arm_dir) - c3
        G = G + w * off
        print(f"  {side} sleeve: frontal {math.degrees(a_g):.1f}->{math.degrees(a_b):.1f} sagittal {math.degrees(b_g):.1f}->{math.degrees(b_b):.1f} shift {np.round(off,3)}")
    return G


def shrinkwrap_out(g, targets, offset):
    """Push garment verts that sit inside (or within `offset` of) the body back outside it."""
    for t in targets:
        m = g.modifiers.new("sw_" + t.name, "SHRINKWRAP")
        m.target = t
        m.wrap_method = "NEAREST_SURFACEPOINT"
        m.wrap_mode = "OUTSIDE"
        m.offset = offset
        bpy.context.view_layer.objects.active = g
        bpy.ops.object.modifier_apply(modifier=m.name)


def fit_outfit(g, parts, B, c):
    body = vb.verts_np(parts["body"])
    G = vb.verts_np(g)
    top = B["Neck"].z + c.get("top_dz", 0.03)
    bottom = B["Hips"].z + c["hem"]
    sz = (top - bottom) / (G[:, 2].max() - G[:, 2].min()) * c.get("scale", 1.0)
    G = (G - [0, 0, G[:, 2].max()]) * sz + [0, 0, top]
    zc = B["Spine2"].z + 0.04
    slab = lambda V: V[np.abs(V[:, 2] - zc) < 0.03]
    bs, gs = slab(body), slab(G)
    bs = bs[np.abs(bs[:, 0]) < 0.2]
    gs = gs[np.abs(gs[:, 0] - np.median(G[:, 0])) < 0.2]
    gcx = (G[:, 0].min() + G[:, 0].max()) / 2
    gcy = (gs[:, 1].min() + gs[:, 1].max()) / 2
    bcy = (bs[:, 1].min() + bs[:, 1].max()) / 2
    G[:, 0] = (G[:, 0] - gcx) * c.get("wide", 1.0)
    G[:, 1] = (G[:, 1] - gcy) * c.get("deep", 1.0) + bcy + c.get("dy", 0.0)
    if c.get("sleeves"):
        G = repose_sleeves(G, B)
    vb.set_verts(g, G)
    c["_zmin"] = max(bottom + 0.04, B["Hips"].z + c.get("waist", -0.04))  # bake: nothing below the waistline
    c["_max_down"] = -0.55                          # ...and no downward-facing skin (crotch, buttock creases)
    print(f"outfit: sz={sz:.3f}")
    return [("all", [g], lambda bones: True)]


def copy_obj(g, name):
    m = g.copy()
    m.data = g.data.copy()
    m.name = name
    bpy.context.scene.collection.objects.link(m)
    return m


def fit_shirt(g, parts, B, c):
    """Torso and each sleeve get their own rigid-ish copy of the garment; returns bake regions."""
    body = vb.verts_np(parts["body"])
    G0 = vb.verts_np(g)
    # --- torso: box fit (x/y by chest width, z from hem to neck)
    zc = B["Spine2"].z + 0.04
    bs = body[(np.abs(body[:, 2] - zc) < 0.03) & (np.abs(body[:, 0]) < 0.2)]
    bw = bs[:, 0].max() - bs[:, 0].min()
    sx = bw * 1.06 / (2 * c["chest"][0])
    zb_top, zb_hem = B["Neck"].z + 0.02, B["Hips"].z - 0.12
    sz = (zb_top - zb_hem) / (c["neck"] - c["hem"])
    gs = G0[np.abs(G0[:, 2] - c["chest"][1]) < 0.03]
    gs = gs[np.abs(gs[:, 0]) < c["chest"][0]]
    gcy = (gs[:, 1].min() + gs[:, 1].max()) / 2
    bcy = (bs[:, 1].min() + bs[:, 1].max()) / 2
    T = G0.copy()
    T[:, 0] *= sx
    T[:, 1] = (T[:, 1] - gcy) * sx * c.get("deep", 1.0) + bcy
    T[:, 2] = (T[:, 2] - c["hem"]) * sz + zb_hem
    vb.set_verts(g, T)
    regions = []
    # --- sleeves: similarity transform shoulder->cuff onto arm joint->wrist
    for side, sgn in (("Left", -1), ("Right", 1)):
        sb, wb = np.array(B[side + "Arm"]), np.array(B[side + "Hand"])
        sg = np.array([sgn * c["shoulder"][0], 0.0, c["shoulder"][1]])
        cg = np.array([sgn * c["cuff"][0], 0.0, c["cuff"][1]])
        dg, db = cg - sg, wb - sb
        s = np.linalg.norm(db) / np.linalg.norm(dg)
        R = np.array(Vector(dg).rotation_difference(Vector(db)).to_matrix())
        S = (G0 - sg) @ R.T * s + sb
        sl = copy_obj(g, f"sleeve{side}")
        vb.set_verts(sl, S)
        # a target face belongs to this sleeve when most of its verts are dominated by this side's arm bones
        pre = tuple(side + k for k in ("Arm", "ForeArm", "Hand")) + (side + "_sup_arm", side + "_sup_elbow", side + "_sup_shoulder")
        regions.append((f"arm{side}", [sl], lambda bones, pre=pre: sum(b.startswith(pre) for b in bones) * 2 > len(bones)))
    armsel = [r[2] for r in regions]
    regions.insert(0, ("torso", [g], lambda bones: not any(f(bones) for f in armsel)))
    c["_zmin"] = B["Hips"].z + c.get("waist", -0.04)
    c["_max_down"] = -0.55
    print(f"shirt: torso sx={sx:.3f} sz={sz:.3f}")
    return regions


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    item, sex = argv[0], argv[1]
    c = CFG[item]
    vb.clear()
    parts, B, data = vb.load_body(sex)
    for o in parts.values():
        vb.body_material(o)
    g = vb.import_garment(item)
    src = globals()["fit_" + c["kind"]](g, parts, B, c)
    if "--render" in argv:
        out = os.path.join(vb.WORK, f"fit_{item}_{sex}")
        vis = [g] + list(parts.values())
        center = {"outfit": (0, 0, 1.25), "head": (0, 0, 1.7), "feet": (0, 0, 0.25), "hands": (-0.5, 0.1, 1.15)}[c["kind"]]
        size = {"outfit": 1.3, "head": 0.5, "feet": 0.7, "hands": 0.4}[c["kind"]]
        vb.render(out, vis, center, size, angles=(0, 90, 180))


if __name__ == "__main__":
    main()
