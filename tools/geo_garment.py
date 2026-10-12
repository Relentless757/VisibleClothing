"""Real-geometry clothing: fit the Tripo mesh itself onto the vanilla body, conform it, skin it.

blender -b --factory-startup -P tools/geo_garment.py -- <Item> [--render]
Writes _work/out/<Item>_male.json and <Item>_female.json (same UVs + texture, per-sex shape/weights).

Steps
  1. align   : per-kind placement (fit.py landmarks); shirts re-posed with smooth shoulder skinning
  2. conform : push verts out of the (inflated) body, pull very loose ones in, smooth the displacement
  3. skin    : weights from the nearest point of the matching body region (sleeves<-arms, torso<-torso)
  4. female  : male fit moved by the female-male body difference at each vert's anchor, re-conformed
"""
import sys, os, json, math, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vc_blender as vb
import fit
import numpy as np
import bpy, bmesh
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

OUT = os.path.join(vb.WORK, "out")

# kind -> body parts used for anchoring/skinning, clipping gap (m), max looseness (m)
KIND = {
    "outfit": dict(parts=["body"], gap=0.006, loose=0.02, loose_arm=0.012),
    "shirt": dict(parts=["body"], gap=0.006, loose=0.02, loose_arm=0.012),
    "head": dict(parts=["head", "body"], gap=0.010, loose=0.03, refit_female=True),
    "hands": dict(parts=["hands", "body"], gap=0.002, loose=0.004),
    "feet": dict(parts=["feet", "body"], gap=0.003, loose=0.012),
    "pants": dict(parts=["body", "feet"], gap=0.006, loose=0.025),
}


# ---------------------------------------------------------------- mesh helpers
def adjacency(ob):
    n = len(ob.data.vertices)
    nb = [[] for _ in range(n)]
    for e in ob.data.edges:
        a, b = e.vertices
        nb[a].append(b)
        nb[b].append(a)
    return nb


def smooth_field(F, nb, iters, lam=0.5, pin=None):
    F = F.copy()
    for _ in range(iters):
        avg = np.array([F[x].mean(0) if x else F[i] for i, x in enumerate(nb)])
        upd = F + lam * (avg - F)
        if pin is not None:
            upd[pin] = F[pin]
        F = upd
    return F


class BodySurface:
    """Union of body-part meshes with per-face region labels, nearest-point queries with barycentric
    interpolation of position, smooth normal and skin weights."""

    def __init__(self, parts, names, region_of_bone, labels=None):
        labels = labels or {}
        self.objs = [parts[n] for n in names]
        self.names = names
        self.data = []
        for ob in self.objs:
            me = ob.data
            V = vb.verts_np(ob)
            N = np.zeros(len(me.vertices) * 3)
            me.attributes["unormal"].data.foreach_get("vector", N)
            N = N.reshape(-1, 3)
            T = np.array([p.vertices[:] for p in me.polygons])
            gn = [g.name for g in ob.vertex_groups]
            W = [{gn[g.group]: g.weight for g in v.groups} for v in me.vertices]
            dom = [max(w, key=w.get) if w else "" for w in W]
            freg, fdom = [], []
            forced = labels.get(names[len(self.data)])
            for t in T:
                labs = [forced or region_of_bone(dom[i]) for i in t]
                freg.append(max(set(labs), key=labs.count))
                bs = [dom[i] for i in t]
                fdom.append(max(set(bs), key=bs.count))
            self.data.append(dict(V=V, N=N, T=T, W=W, freg=np.array(freg), fdom=fdom))
        self.bvh = {}

    def tree(self, regions):
        key = tuple(sorted(regions)) if regions else None
        if key in self.bvh:
            return self.bvh[key]
        verts, tris, owner = [], [], []
        for pi, d in enumerate(self.data):
            sel = np.ones(len(d["T"]), bool) if regions is None else np.isin(d["freg"], list(regions))
            base = len(verts)
            verts.extend(map(tuple, d["V"]))
            for fi in np.where(sel)[0]:
                tris.append(tuple(int(i) + base for i in d["T"][fi]))
                owner.append((pi, fi))
        t = (BVHTree.FromPolygons(verts, tris, all_triangles=True), owner)
        self.bvh[key] = t
        return t

    def nearest_bones(self, p, key, pred):
        """Nearest point on faces whose dominant bone satisfies pred (e.g. one finger's bones)."""
        if key not in self.bvh:
            verts, tris, owner = [], [], []
            for pi, d in enumerate(self.data):
                base = len(verts)
                verts.extend(map(tuple, d["V"]))
                for fi, b in enumerate(d["fdom"]):
                    if pred(b):
                        tris.append(tuple(int(i) + base for i in d["T"][fi]))
                        owner.append((pi, fi))
            self.bvh[key] = (BVHTree.FromPolygons(verts, tris, all_triangles=True) if tris else None, owner)
        bvh, owner = self.bvh[key]
        if bvh is None:
            return None
        loc, nrm, idx, dist = bvh.find_nearest(Vector(p))
        if loc is None:
            return None
        pi, fi = owner[idx]
        d = self.data[pi]
        bc = bary(np.array(loc), d["V"][d["T"][fi]])
        return np.array(loc), None, (pi, fi, bc)

    def nearest(self, p, regions=None):
        bvh, owner = self.tree(regions)
        loc, nrm, idx, dist = bvh.find_nearest(Vector(p))
        if loc is None:
            return None
        pi, fi = owner[idx]
        d = self.data[pi]
        tri = d["T"][fi]
        bc = bary(np.array(loc), d["V"][tri])
        n = (d["N"][tri] * bc[:, None]).sum(0)
        n /= np.linalg.norm(n) + 1e-9
        return np.array(loc), n, (pi, fi, bc)

    def eval(self, anchor, other=None):
        """Position / normal / weights of an anchor on this surface (or on `other` with the same topology)."""
        pi, fi, bc = anchor
        d = (other or self).data[pi]
        tri = d["T"][fi]
        p = (d["V"][tri] * bc[:, None]).sum(0)
        n = (d["N"][tri] * bc[:, None]).sum(0)
        n /= np.linalg.norm(n) + 1e-9
        w = {}
        for i, b in zip(tri, bc):
            for k, x in d["W"][i].items():
                w[k] = w.get(k, 0) + x * b
        return p, n, w


def bary(p, tri):
    a, b, c = tri
    v0, v1, v2 = b - a, c - a, p - a
    d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
    d20, d21 = v2 @ v0, v2 @ v1
    den = d00 * d11 - d01 * d01 or 1e-12
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return np.clip(np.array([1 - v - w, v, w]), 0, 1) / max(np.clip(np.array([1 - v - w, v, w]), 0, 1).sum(), 1e-9)


def region_of_bone(b):
    for side in ("Left", "Right"):
        if b.startswith((side + "Arm", side + "ForeArm", side + "Hand", side + "_sup_arm", side + "_sup_elbow",
                         side + "_sup_shoulder", side + "_sup_index", side + "_sup_middle", side + "_sup_ring",
                         side + "_sup_pinky", side + "_sup_thumb", side + "_sup_wrist")):
            return "arm" + side
        if b.startswith((side + "UpLeg", side + "Leg", side + "Foot", side + "Toe", side + "_sup_hip", side + "_sup_knee")):
            return "leg" + side
    if b.startswith(("Neck", "Head", "Jaw")) or "eye" in b.lower() or "lip" in b.lower() or "brow" in b.lower():
        return "head"
    return "torso"


# ---------------------------------------------------------------- shirts: smooth sleeve re-pose
def sleeve_membership(G0, c, sgn, nb):
    """Raw-garment-space sleeve mask for one side. Above the armpit: outside the armhole line
    (shoulder top -> armpit). Below it the sleeve and the torso are separate pieces of the mesh, so take
    connected components of the below-armpit verts and keep the ones sitting out on this side."""
    x = G0[:, 0] * sgn
    z = G0[:, 2]
    (sx_, sz_), (ax_, az_) = c["shoulder_top"], c["armpit"]
    m = np.zeros(len(G0), bool)
    above = z >= az_
    line_x = ax_ + (z - az_) / max(sz_ - az_, 1e-6) * (sx_ - ax_)
    m[above] = x[above] > line_x[above]
    if c.get("side_line"):                     # sleeves fused to the torso sides: cut on a line
        (bx, bz) = c["side_line"]
        lx = bx + (z - bz) / max(az_ - bz, 1e-6) * (ax_ - bx)
        m[~above] = x[~above] > lx[~above] + 0.01
        return m.astype(float)
    below = np.where(~above)[0]
    seen = np.zeros(len(G0), bool)
    for s0 in below:
        if seen[s0]:
            continue
        comp, stack = [], [s0]
        seen[s0] = True
        while stack:
            i = stack.pop()
            comp.append(i)
            for j in nb[i]:
                if not seen[j] and not above[j]:
                    seen[j] = True
                    stack.append(j)
        comp = np.array(comp)
        if np.median(x[comp]) > ax_ + 0.02:
            m[comp] = True
    return m.astype(float)


def repose_shirt(G, B, c, place, members, G0, body_arm):
    """Each sleeve is rebuilt from the unscaled raw garment: shoulder->cuff axis rotated onto the arm bone
    line, stretched to arm length, and scaled radially to the arm's girth (+ ease). Blended into the
    torso-placed garment by the (smoothed) sleeve membership."""
    for side, sgn in (("Left", -1), ("Right", 1)):
        sb, wb = np.array(B[side + "Arm"]), np.array(B[side + "Hand"])
        wb = wb - (wb - sb) / np.linalg.norm(wb - sb) * c.get("cuff_back", 0.035)   # cuff stops short of the wrist
        sg = np.array([sgn * c["shoulder"][0], 0.0, c["shoulder"][1]])
        cg = np.array([sgn * c["cuff"][0], 0.0, c["cuff"][1]])
        dg, db = cg - sg, wb - sb
        Lg, Lb = np.linalg.norm(dg), np.linalg.norm(db)
        ag, ab = dg / Lg, db / Lb
        R = np.array(Vector(dg).rotation_difference(Vector(db)).to_matrix())
        P = (G0 - sg) @ R.T                      # raw garment, sleeve axis now along ab, joint at origin
        t = P @ ab
        radial = P - np.outer(t, ab)
        w = members[side]
        sl = (w > 0.9) & (t > 0.3 * Lg) & (t < 0.7 * Lg)
        r_g = np.median(np.linalg.norm(radial[sl], axis=1)) if sl.sum() > 10 else 0.05
        A = body_arm[side] - sb
        ta = A @ ab
        am = (ta > 0.3 * Lb) & (ta < 0.7 * Lb)
        r_b = np.median(np.linalg.norm(A[am] - np.outer(ta[am], ab), axis=1))
        kr = np.clip(r_b * c.get("ease", 1.25) / r_g, 0.5, 2.0)
        Gs = np.outer(t * (Lb / Lg), ab) + radial * kr + sb
        G = G * (1 - w[:, None]) + Gs * w[:, None]
        print(f"  {side} sleeve: length x{Lb/Lg:.2f}, girth {r_g*1000:.0f}->{r_b*1000:.0f}mm (x{kr:.2f})")
    return G, members


def align_shirt(g, parts, B, c):
    body = vb.verts_np(parts["body"])
    G0 = vb.verts_np(g)
    zc = B["Spine2"].z + 0.04
    bs = body[(np.abs(body[:, 2] - zc) < 0.03) & (np.abs(body[:, 0]) < 0.2)]
    sx = (bs[:, 0].max() - bs[:, 0].min()) * c.get("wide", 1.0) / (2 * c["chest"][0])
    zb_top, zb_hem = B["Neck"].z + c.get("top_dz", 0.02), B["Hips"].z + c.get("hem_z", 0.03)
    sz = (zb_top - zb_hem) / (c["neck"] - c["hem"])
    gs = G0[(np.abs(G0[:, 2] - c["chest"][1]) < 0.03) & (np.abs(G0[:, 0]) < c["chest"][0])]
    gcy = (gs[:, 1].min() + gs[:, 1].max()) / 2
    bcy = (bs[:, 1].min() + bs[:, 1].max()) / 2
    sy = sx * c.get("deep", 1.0)

    def place(P):
        P = np.atleast_2d(P).astype(float).copy()
        P[:, 0] *= sx
        P[:, 1] = (P[:, 1] - gcy) * sy + bcy
        P[:, 2] = (P[:, 2] - c["hem"]) * sz + zb_hem
        return P[0] if P.shape[0] == 1 else P

    G = place(G0)
    nb = adjacency(g)
    members = {}
    for side, sgn in (("Left", -1), ("Right", 1)):
        m = sleeve_membership(G0, c, sgn, nb)
        members[side] = np.clip(smooth_field(m[:, None], nb, 8, lam=0.5)[:, 0], 0, 1)  # soften across the armhole
    body_arm = {}
    for side in ("Left", "Right"):
        ids = {parts["body"].vertex_groups[n].index for n in (side + "Arm", side + "ArmRoll", side + "ForeArm", side + "ForeArmRoll")
               if n in parts["body"].vertex_groups}
        body_arm[side] = np.array([v.co[:] for v in parts["body"].data.vertices
                                   if any(g.group in ids and g.weight > 0.4 for g in v.groups)])
    G, member = repose_shirt(G, B, c, place, members, G0, body_arm)
    vb.set_verts(g, G)
    # skinning regions per vertex: sleeves take arm weights, the rest torso
    reg = np.where(member["Left"] > 0.5, "armLeft", np.where(member["Right"] > 0.5, "armRight", "torso"))
    # armpit zone: the sleeve/torso blend and anything near the body's armpit is pulled snug so the underarm
    # fabric tucks in instead of webbing from the upper arm down to the ribs
    tight = np.zeros(len(G), bool)
    for side, sgn in (("Left", -1), ("Right", 1)):
        arm = np.array(B[side + "Arm"])
        pit = np.array([arm[0] * 0.8, arm[1], arm[2] - 0.11])
        m = member[side]
        tight |= (m > 0.03) & (m < 0.97)
        tight |= np.linalg.norm(G - pit, axis=1) < c.get("pit_radius", 0.10)
    c["_tight"] = tight
    print(f"shirt: sx={sx:.3f} sz={sz:.3f}, armpit verts tightened: {tight.sum()}")
    return reg


def align_outfit(g, parts, B, c):
    fit.fit_outfit(g, parts, B, c)
    return np.array(["torso"] * len(g.data.vertices))


def upright_hat(g, G, tilt_deg):
    """Stand a cap on its opening: plane through the open boundary loop -> horizontal, opening down;
    longest horizontal extent -> front/back (Y); then tip the crown back by `tilt_deg`."""
    bm = bmesh.new(); bm.from_mesh(g.data)
    bverts = sorted({v.index for e in bm.edges if e.is_boundary for v in e.verts})
    bm.free()
    if len(bverts) >= 20:
        P = G[bverts]
        c0 = P.mean(0)
        n = np.linalg.svd(P - c0)[2][2]
    else:
        # closed mesh: the opening is the biggest flat face of the convex hull
        hb = bmesh.new()
        for v in G:
            hb.verts.new(v)
        res = bmesh.ops.convex_hull(hb, input=hb.verts)
        faces = [f for f in res["geom"] if isinstance(f, bmesh.types.BMFace)]
        f = max(faces, key=lambda f: f.calc_area())
        n = np.array(f.normal)
        c0 = np.array(f.calc_center_median())
        hb.free()
    if (G.mean(0) - c0) @ n < 0:          # normal points from the opening into the crown
        n = -n
    R = np.array(Vector(n).rotation_difference(Vector((0, 0, 1))).to_matrix())
    G = (G - c0) @ R.T
    xy = G[:, :2] - G[:, :2].mean(0)
    ev = np.linalg.eigh(xy.T @ xy)[1][:, 1]  # longest horizontal direction
    yaw = math.atan2(ev[0], ev[1])
    Rz = np.array(Matrix.Rotation(yaw, 3, "Z"))
    G = G @ Rz.T
    Rx = np.array(Matrix.Rotation(math.radians(tilt_deg), 3, "X"))  # brim higher at the front, lower at the back
    G = G @ Rx.T
    print(f"  hat: opening normal {np.round(n, 2)}, yaw {math.degrees(yaw):.0f}, tilt {tilt_deg}")
    return G


def clear_face(g, G, H, cx, cy, gap, max_move=1.0):
    """Slide the lower front of a mask forward as one smooth piece until nose, lips and chin clear it."""
    vb.set_verts(g, G)
    bvh = BVHTree.FromObject(g, bpy.context.evaluated_depsgraph_get())
    face = H[(H[:, 1] > cy + 0.03) & (H[:, 2] < 1.73) & (H[:, 2] > 1.55)]
    need = 0.0
    for v in face:
        hit = bvh.ray_cast(Vector(v), Vector((0, 1, 0)), 0.08)       # mask in front of the skin?
        if hit[0] is not None:
            need = max(need, gap - hit[3])
        else:
            back = bvh.ray_cast(Vector(v), Vector((0, -1, 0)), 0.02)  # skin already through the mask (just)
            if back[0] is not None:
                need = max(need, back[3] + gap)
    w = fit.smoothstep(cy + 0.02, cy + 0.07, G[:, 1]) * fit.smoothstep(1.75, 1.71, G[:, 2])
    move = min(max(need, 0.0), max_move)   # the biggest nose of 16 faces: the rest is left to local unclip
    print(f"  face: moving mask front {move*1000:.1f} mm forward (needed {need*1000:.1f})")
    return G + np.outer(w * move, [0, 1, 0])


def align_head(g, parts, B, c):
    H = vb.verts_np(parts["head"])
    G = vb.verts_np(g)
    zb = c["brim"]
    top = H[:, 2].max() + c["top"]
    rz = c.get("ring", zb + 0.015)
    ring = H[(H[:, 2] > rz) & (H[:, 2] < rz + 0.03) & (np.abs(H[:, 0]) < 0.11)]  # skull just above the brim (no ears)
    cx, cy = (ring[:, 0].min() + ring[:, 0].max()) / 2, (ring[:, 1].min() + ring[:, 1].max()) / 2
    w, d = np.ptp(ring[:, 0]) * c["wide"], np.ptp(ring[:, 1]) * c["deep"]
    if c.get("upright"):
        G = upright_hat(g, G, c.get("tilt", 10))
    lo, hi = G.min(0), G.max(0)
    ctr = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    G = (G - ctr) * [w / (hi[0] - lo[0]), d / (hi[1] - lo[1]), (top - zb) / (hi[2] - lo[2])] + [cx, cy, zb]
    vb.set_verts(g, G)
    if c.get("face_clear"):
        G = clear_face(g, G, H, cx, cy, c["face_clear"], c.get("face_move_max", 1.0))
    print(f"head: box {w:.3f} x {d:.3f} x {top - zb:.3f}")
    return np.array(["head" if c["brim"] > 1.6 else "any"] * len(G), dtype=object)


def align_feet(g, parts, B, c):
    F = vb.verts_np(parts["feet"])
    G = vb.verts_np(g)
    # the pair sits side by side along Y: every piece (inner layers, bits split off by holes) goes with its sock
    mid = (G[:, 1].min() + G[:, 1].max()) / 2
    socks = [np.where(G[:, 1] < mid)[0], np.where(G[:, 1] >= mid)[0]]
    reg = np.array(["any"] * len(G), dtype=object)
    for ix, side, sgn in zip(socks, ("Left", "Right"), (-1, 1)):
        S = G[ix]
        h = np.ptp(S[:, 2])
        low = S[S[:, 2] < S[:, 2].min() + 0.25 * h]
        top = S[S[:, 2] > S[:, 2].max() - 0.2 * h]
        toe = 1 if low[:, 0].mean() > top[:, 0].mean() else -1   # the foot part sticks out toward the toes
        ang = math.pi / 2 if toe == 1 else -math.pi / 2           # turn the toe to +Y (character forward)
        R = np.array(Matrix.Rotation(ang, 3, "Z"))
        S = S @ R.T
        low = S[S[:, 2] < S[:, 2].min() + 0.25 * h]
        foot = F[F[:, 0] * sgn > 0]
        k = np.ptp(foot[:, 1]) * c.get("len", 1.04) / np.ptp(low[:, 1])
        S = S * k
        low = S[S[:, 2] < S[:, 2].min() + 0.25 * h * k]
        S = S + [foot[:, 0].mean() - low[:, 0].mean(), foot[:, 1].min() - 0.006 - low[:, 1].min(), 0.004 - S[:, 2].min()]
        G[ix] = S
        reg[ix] = "any"
        print(f"feet: {side} sock scale {k:.3f} toe {toe:+d}X, top z {S[:, 2].max():.3f}")
    vb.set_verts(g, G)
    return reg


def align_hands(g, parts, B, c, side="Left"):
    """Rigid placement of the (left) glove on one hand; the right hand gets the mirror image."""
    G = vb.verts_np(g)
    m = 1 if side == "Left" else -1
    if side == "Right":
        G[:, 0] *= -1
    fg, tg = np.array([0, 1.0, 0]), np.array([1.0 * m, 0, 0])       # fingers, thumb side (raw glove)
    ng = np.cross(tg, fg) * m                                          # back of the hand
    hand, mid = np.array(B[side + "Hand"]), np.array(B[side + "HandMiddle1"])
    ind, pin = np.array(B[side + "HandIndex1"]), np.array(B[side + "HandPinky1"])
    fb = mid - hand; fb /= np.linalg.norm(fb)
    tb = ind - pin; tb -= fb * (tb @ fb); tb /= np.linalg.norm(tb)
    nb_ = np.cross(tb, fb) * m
    R = np.stack([fb, tb, nb_]).T @ np.stack([fg, tg, ng])
    ky, kw = c["knuckle"]
    slab = G[np.abs(G[:, 1] - ky) < 0.03]
    kc = np.array([(slab[:, 0].min() + slab[:, 0].max()) / 2, ky, (slab[:, 2].min() + slab[:, 2].max()) / 2])
    k = (np.linalg.norm(ind - pin) + 0.035) * c.get("wide", 1.0) / kw
    # hand mesh across the knuckles: its centre and thickness (the joints sit off-centre)
    Hm = vb.verts_np(parts["hands"])
    kl = Hm - pin
    along = kl @ tb
    perp = kl - np.outer(along, tb)
    near = (along > -0.01) & (along < np.linalg.norm(ind - pin) + 0.01) & (np.abs(perp @ fb) < 0.012) & (np.abs(perp @ nb_) < 0.05)
    hn = Hm[near] @ nb_
    kb = (ind + pin) / 2
    if near.sum() > 10:
        kb = kb + nb_ * ((hn.max() + hn.min()) / 2 - kb @ nb_)
        h_thick = np.ptp(hn)
    gthick = np.ptp(slab[:, 2]) * k
    kn = (h_thick * c.get("thick", 1.0) / gthick) if near.sum() > 10 else 1.0
    S = np.diag([1.0, c.get("long", 1.0), kn])  # raw glove: y = finger axis, z = back-of-hand axis
    place = lambda P: (((P - kc) * k) @ S) @ R.T + kb + c.get("shift", 0) * fb
    G0 = G.copy()
    G = place(G0)
    print(f"hands {side}: scale {k:.3f}, thickness x{kn:.2f}, back-of-hand {np.round(nb_, 2)}")
    if c.get("fingers"):
        G = repose_fingers(G0, G, c, B, side, m, place)
    return G


FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")


def repose_fingers(G0, G, c, B, side, m, place):
    """Each glove finger (raw-frame base->tip landmarks) is rotated about its base onto the body finger's
    chord (Finger1 -> Finger4 tip) and stretched to its length. Glove verts are given to the nearest finger
    segment past its base; the membership is smoothed across the mesh so the palm blends."""
    raw = c["fingers"]
    segs = []
    for f in FINGERS:
        (bx, by), (tx, ty) = raw[f]
        bxy, txy = np.array([bx * m, by]), np.array([tx * m, ty])   # mirrored glove: x flips
        # finger centre height: median z of raw verts near the base->tip line
        d = txy - bxy
        L = np.linalg.norm(d)
        t = np.clip(((G0[:, :2] - bxy) @ d) / (L * L), 0, 1)
        r = np.linalg.norm(G0[:, :2] - (bxy + np.outer(t, d)), axis=1)
        near = (r < 0.04) & (t > 0.1)
        z = np.median(G0[near, 2]) if near.sum() > 5 else np.median(G0[:, 2])
        segs.append((np.array([*bxy, z]), np.array([*txy, z])))
    # membership in raw space
    D = np.full((len(G0), len(FINGERS)), np.inf)
    T = np.zeros_like(D)
    for j, (b, tp) in enumerate(segs):
        d = tp - b
        t = ((G0 - b) @ d) / (d @ d)
        q = b + np.outer(np.clip(t, 0, 1), d)
        D[:, j] = np.linalg.norm(G0 - q, axis=1)
        T[:, j] = t
    own = np.argmin(D, axis=1)
    nb = adj_from_verts(G0)
    out = G.copy()
    W = np.zeros_like(D)
    for j in range(len(FINGERS)):
        w = ((own == j) & (T[:, j] > -0.05)).astype(float) * fit.smoothstep(-0.12, 0.08, T[:, j])
        W[:, j] = np.clip(smooth_field(w[:, None], nb, 6, lam=0.5)[:, 0], 0, 1)
    tot = np.maximum(W.sum(1), 1.0)
    acc = np.zeros_like(G)
    for j, f in enumerate(FINGERS):
        bg, tg_ = place(segs[j][0]), place(segs[j][1])
        bb = np.array(B[f"{side}Hand{f}1"])
        tb_ = np.array(B[f"{side}Hand{f}4"])
        tb_ = tb_ + (tb_ - np.array(B[f"{side}Hand{f}3"])) * 0.6   # skin tip lies past the last joint
        dg, db = tg_ - bg, tb_ - bb
        Rf = np.array(Vector(dg).rotation_difference(Vector(db)).to_matrix())
        sl = np.linalg.norm(db) / np.linalg.norm(dg)
        P = (G - bg) @ Rf.T
        a = db / np.linalg.norm(db)
        along = P @ a
        P = P + np.outer(along * (sl - 1), a) + bb
        acc += P * W[:, j:j + 1]
        print(f"    {f}: rot {math.degrees(Vector(dg).angle(Vector(db))):.0f} deg, length x{sl:.2f}")
    wsum = W.sum(1, keepdims=True)
    c["_W_" + side] = W            # per-vertex finger membership, used to keep palm weights off the fingers
    sw = np.minimum(wsum, 1.0)
    return G * (1 - sw) + acc / np.maximum(wsum, 1e-9) * sw


def adj_from_verts(G0):
    """Adjacency of the current garment object (vertex order matches G0)."""
    return _ADJ["nb"]


_ADJ = {}



def align_pants(g, parts, B, c):
    """Waistband just above the shirt hem, hems at the ankle, hip width/depth matched; below the crotch each
    leg's centre line slides (smoothly) onto the body's hip->ankle line."""
    body = vb.verts_np(parts["body"])
    G = vb.verts_np(g)
    lo, hi = G.min(0), G.max(0)
    if c.get("strings"):  # separate hanging pieces at the front of the waistband -> cloth-simulated drawstrings
        free = [ix for ix in vb.islands(g) if 60 <= len(ix) <= 400 and G[ix, 2].min() > lo[2] + 0.6 * (hi[2] - lo[2])
                and np.abs(G[ix, 0]).max() < 0.09 and G[ix, 1].mean() > 0.05]
        c["_free"] = np.concatenate(free) if free else None
        print(f"pants: {len(free)} drawstring pieces ({sum(len(f) for f in free)} verts) kept free for cloth")
    crotch = G[np.abs(G[:, 0] - (lo[0] + hi[0]) / 2) < 0.025][:, 2].min()   # lowest point on the centre line
    top, hem = B["Hips"].z + c.get("waist", 0.05), B["LeftFoot"].z + c.get("hem", 0.01)
    sz = (top - hem) / (hi[2] - lo[2])
    zh = B["Hips"].z - 0.06                                               # widest part of the hips/seat
    bs = body[(np.abs(body[:, 2] - zh) < 0.02)]
    zg = lo[2] + (zh - hem) / sz                                          # same height on the raw pants
    gs = G[np.abs(G[:, 2] - zg) < 0.02]
    sx = np.ptp(bs[:, 0]) * c.get("wide", 1.06) / np.ptp(gs[:, 0])
    sy = np.ptp(bs[:, 1]) * c.get("deep", 1.10) / np.ptp(gs[:, 1])
    gc = np.array([(gs[:, 0].min() + gs[:, 0].max()) / 2, (gs[:, 1].min() + gs[:, 1].max()) / 2])
    bc = np.array([(bs[:, 0].min() + bs[:, 0].max()) / 2, (bs[:, 1].min() + bs[:, 1].max()) / 2])
    G = np.column_stack([(G[:, 0] - gc[0]) * sx + bc[0], (G[:, 1] - gc[1]) * sy + bc[1], (G[:, 2] - lo[2]) * sz + hem])
    zc = (crotch - lo[2]) * sz + hem
    reg = np.array(["any"] * len(G), dtype=object)
    for side, sgn in (("Left", -1), ("Right", 1)):
        hip, knee, ank = (np.array(B[side + n]) for n in ("UpLeg", "Leg", "Foot"))
        leg = (G[:, 0] * sgn > 0) & (G[:, 2] < zc)
        reg[leg & (G[:, 2] < zc - 0.05)] = "leg" + side
        D = np.zeros_like(G)
        for z0 in np.arange(hem, zc, 0.02):
            sl = leg & (np.abs(G[:, 2] - z0) < 0.012)
            if sl.sum() < 6:
                continue
            ctr = (G[sl].min(0) + G[sl].max(0)) / 2
            # body leg line at this height (hip->knee->ankle, piecewise)
            a_, b_ = (hip, knee) if z0 > knee[2] else (knee, ank)
            t = (z0 - a_[2]) / (b_[2] - a_[2] + 1e-9)
            tgt = a_ + (b_ - a_) * t
            D[sl, 0], D[sl, 1] = tgt[0] - ctr[0], tgt[1] - ctr[1]
        w = fit.smoothstep(zc + 0.02, zc - 0.10, G[:, 2])[:, None]
        G = G + D * w * leg[:, None]
    vb.set_verts(g, G)
    print(f"pants: crotch z {zc:.3f}, scale x{sx:.3f} y{sy:.3f} z{sz:.3f}")
    return reg


# ---------------------------------------------------------------- conform + skin
def spread(D, G, r=0.012):
    """Stacked layers (folded cuffs, hems, collars) must move together: every vert takes the largest push found
    within r, so an inner layer is never pushed out past the layer lying on top of it."""
    from mathutils.kdtree import KDTree
    mag = np.linalg.norm(D, axis=1)
    idx = np.where(mag > 1e-6)[0]
    if not len(idx):
        return D
    kd = KDTree(len(idx))
    for j, i in enumerate(idx):
        kd.insert(G[i], j)
    kd.balance()
    out = D.copy()
    best = mag.copy()
    for v in range(len(G)):
        for co, j, dist in kd.find_range(G[v], r):
            i = idx[j]
            if mag[i] > best[v]:
                best[v] = mag[i]
                out[v] = D[i]
    return out


def conform(g, surf, reg, gap, loose, nb, iters=3, loose_arm=None, tight=None, loose_tight=0.006, coll=None):
    """Displacement so every vert sits >= gap outside and <= loose from its region's skin; smoothed.
    gap: scalar or per vertex. coll: surface for the clipping test (body + whatever lies under the garment:
    the head envelope, the pants under a shirt); looseness is always measured from the body (surf)."""
    G = vb.verts_np(g)
    coll = coll or surf
    gap = np.broadcast_to(np.asarray(gap, float), (len(G),))
    regions_for = {"torso": {"torso"}, "armLeft": {"armLeft"}, "armRight": {"armRight"},
                   "head": {"head"}, "legLeft": {"legLeft"}, "legRight": {"legRight"}, "any": None}
    anchors = [None] * len(G)
    for it in range(iters):
        D = np.zeros_like(G)
        for i, v in enumerate(G):
            r = surf.nearest(v, regions_for.get(reg[i]))
            if r is None:
                continue
            p, n, a = r
            anchors[i] = a
            h = (v - p) @ n
            lim = loose_arm if (loose_arm and str(reg[i]).startswith("arm")) else loose
            if tight is not None and tight[i]:
                lim = loose_tight
            if h > lim:                         # too loose w.r.t. its own region: pull in
                D[i] = -n * (h - lim) * 0.6
            pa, na, _ = coll.nearest(v)          # clipping: against the whole body (+ layers), any region
            ha = (v - pa) @ na
            if ha < gap[i]:
                D[i] = na * (gap[i] - ha)
        D = smooth_field(spread(D, G), nb, 6)
        G = G + D
        print(f"  conform pass {it}: mean move {np.linalg.norm(D, axis=1).mean()*1000:.1f} mm, max {np.linalg.norm(D, axis=1).max()*1000:.1f} mm")
    # final hard pass: nothing inside the skin (no smoothing, small)
    for i, v in enumerate(G):
        r = surf.nearest(v, regions_for.get(reg[i]))
        if r is None:
            continue
        anchors[i] = r[2]
        pa, na, _ = coll.nearest(v)
        ha = (v - pa) @ na
        if ha < gap[i] * 0.6:
            G[i] = v + na * (gap[i] * 0.6 - ha)
    vb.set_verts(g, G)
    return anchors


def unclip(g, surf, gap, nb, iters=4, reach=0.03, zmin=-9.0, smooth=4, ymax=9.0, zmax=9.0):
    """Reverse pass: body verts that poke through the garment (ears, toes, nipples, knuckles) push the
    garment faces above them outward. Only counts when the body vert projects inside a garment face, so
    skin just past a hem or cuff edge doesn't inflate it."""
    body = np.concatenate([d["V"] for d in surf.data])
    bn = np.concatenate([d["N"] for d in surf.data])
    gap = np.broadcast_to(np.asarray(gap, float), (len(g.data.vertices),))
    for it in range(iters):
        G = vb.verts_np(g)
        lo, hi = G.min(0) - reach, G.max(0) + reach
        sel = np.all((body > lo) & (body < hi), axis=1) & (body[:, 2] > zmin) & (body[:, 2] < zmax) & (body[:, 1] < ymax)
        me = g.data
        tris = [tuple(p.vertices) for p in me.polygons]
        bvh = BVHTree.FromPolygons([tuple(v) for v in G], tris)
        D = np.zeros_like(G)
        hits = 0
        for b, n in zip(body[sel], bn[sel]):
            loc, fn, fi, dist = bvh.find_nearest(Vector(b), reach)
            if loc is None:
                continue
            fn = np.array(fn)
            if fn @ n < 0.2:                       # garment face must roughly face the same way as the skin
                continue
            pv = list(tris[fi])
            # only skin the garment actually covers: a line along the skin normal through b meets it
            hit = bvh.ray_cast(Vector(b - n * reach), Vector(n), 2 * reach)
            if hit[0] is None:
                continue
            h = (b - np.array(loc)) @ fn
            gf = gap[pv].mean()
            if h > -gf:
                hits += 1
                for v in pv:
                    push = fn * (h + gf)
                    if push @ push > D[v] @ D[v]:
                        D[v] = push
        if not hits:
            break
        D = smooth_field(spread(D, G), nb, smooth, lam=0.5) * (1.3 if smooth <= 4 else 1.8)
        vb.set_verts(g, G + D)
        print(f"  unclip pass {it}: {hits} skin points poking, max push {np.linalg.norm(D, axis=1).max()*1000:.1f} mm")


def finger_seg(b, side):
    """(finger, is_base) for a finger bone of this side, else None. The base bones (HandIndex0 .. Pinky0 and their
    _sup_*_00 / _00_palm helpers, Thumb1 / _sup_thumb_01*) sit in the palm: they cup it, so they belong to both the
    palm and their finger."""
    for f in FINGERS:
        if b.startswith(f"{side}Hand{f}"):
            k = b[len(side) + 4 + len(f):]
            return f, k == ("1" if f == "Thumb" else "0")
        sup = f"{side.lower()}_sup_{f.lower()}_"
        if b.lower().startswith(sup):
            k = b[len(sup):len(sup) + 2]
            return f, k == ("01" if f == "Thumb" else "00")
    return None


def finger_bone(b, side, f=None):
    sg = finger_seg(b, side)
    return sg is not None and (f is None or sg[0] == f)


def palm_bone(b, side):
    sg = finger_seg(b, side)
    return sg is None or sg[1]


def finger_membership_geo(g, surf, reg, nb, iters=8):
    """Per-vertex finger membership from the skin under the glove (each finger's non-base bone weights at the
    nearest hand point), smoothed along the glove's own edges so a glove finger moves as one piece. Used when the
    fit has no finger repose (gloves without finger landmarks, hand-fitted gloves)."""
    G = vb.verts_np(g)
    M = np.zeros((len(G), len(FINGERS)))
    for i, v in enumerate(G):
        r_ = str(reg[i])
        if not r_.startswith("arm"):
            continue
        r = surf.nearest(v, {r_})
        if r is None:
            continue
        for bn, x in surf.eval(r[2])[2].items():
            sg = finger_seg(bn, r_[3:])
            if sg and not sg[1]:
                M[i, FINGERS.index(sg[0])] += x
    return np.clip(smooth_field(M, nb, iters, lam=0.5), 0, 1)


def leg_bone(b):
    return region_of_bone(b).startswith("leg")


def weight_setup(g, surf, reg, c, kind, B, nb):
    """Per vertex: [(anchor, share), ...] on the body + an optional bone filter.
    - sleeves / gloves / pant legs (arm, leg regions): nearest point on their own limb
    - shirts: torso fabric anchors on the torso skin, except the shoulder cap, which blends to the nearest skin
      anywhere (deltoid = arm bones) so it follows a raised arm without opening a gap; leg bones are dropped so the
      hem doesn't follow the thighs
    - pants: below the hips each side drops the other leg's bones (no crotch webbing in a stride)
    - gloves: glove fingers take only that finger's bones; palm / back / cuff only hand, forearm and palm (base)
      bones, so a fist curls the fingers without ballooning the palm; the transition zone keeps the skin's blend"""
    G = vb.verts_np(g)
    anchors, filt = [], []
    FW = c.get("_fingerW")
    if kind == "hands" and (FW is None or FW.max() < 0.5):
        FW = finger_membership_geo(g, surf, reg, nb)
        print(f"  glove finger membership from the skin: {(FW.max(1) > 0.6).sum()} finger verts, "
              f"{(FW.max(1) < 0.15).sum()} palm verts of {len(FW)}")
    shoulders = [np.array(B[sd + "Arm"]) for sd in ("Left", "Right")]
    pits = [np.array([p[0] * 0.8, p[1], p[2] - 0.11]) for p in shoulders]   # same armpit point as align_shirt
    zsh = shoulders[0][2]
    for i, v in enumerate(G):
        r_ = str(reg[i])
        f = None
        if kind in ("outfit", "shirt"):
            # whole-body share: shoulder cap (deltoid) and right at the armpit, where sleeve and torso fabric must
            # move with the skin directly under them or skin shows between sleeve and side when the arm swings
            dsh = min(np.linalg.norm(v - p) for p in shoulders)
            t = float(fit.smoothstep(0.16, 0.09, dsh) * fit.smoothstep(zsh - 0.09, zsh - 0.03, v[2]))
            t = max(t, float(fit.smoothstep(0.08, 0.03, min(np.linalg.norm(v - p) for p in pits))))
            rt = surf.nearest(v, {r_} if r_.startswith("arm") else {"torso"})
            ra = surf.nearest(v) if t > 0 else None
            a = ([(rt[2], 1 - t)] if rt else []) + ([(ra[2], t)] if ra else [])
            f = lambda b: not leg_bone(b)
        elif r_.startswith(("arm", "leg")):
            r = surf.nearest(v, {r_})
            a = [(r[2], 1.0)] if r else []
        else:
            r = surf.nearest(v)
            a = [(r[2], 1.0)] if r else []
            if kind == "pants" and v[2] < B["Hips"].z:
                other = "Right" if v[0] < 0 else "Left"     # Blender: the character's left is -X
                f = (lambda b, o=other: region_of_bone(b) != "leg" + o)
        if kind == "hands" and r_.startswith("arm"):
            side = r_[3:]
            m = FW[i] if FW is not None else np.zeros(len(FINGERS))
            j = int(np.argmax(m))
            if m[j] > 0.6:
                # glove finger: anchor on *its own* finger's skin (the nearest skin may be the neighbouring finger)
                fn = FINGERS[j]
                rf = surf.nearest_bones(v, ("finger", side, fn), lambda b, side=side, fn=fn: finger_bone(b, side, fn))
                if rf:
                    a = [(rf[2], 1.0)]
                f = (lambda b, side=side, fn=fn: finger_bone(b, side, fn))
            elif m.max() < 0.15:
                f = (lambda b, side=side: palm_bone(b, side))
        anchors.append(a)
        filt.append(f)
    return anchors, filt


def spatial_smooth(W, G, r, iters=2):
    """Average weights over everything within r, connected or not: separate pieces that meet at a seam (a sleeve
    sewn into its armhole) must move together or the seam opens when the limb moves."""
    from mathutils.kdtree import KDTree
    kd = KDTree(len(G))
    for i, v in enumerate(G):
        kd.insert(v, i)
    kd.balance()
    nbr = []
    for v in G:
        hits = kd.find_range(v, r)
        idx = np.array([h[1] for h in hits])
        wt = np.exp(-(np.array([h[2] for h in hits]) / (0.5 * r)) ** 2)
        nbr.append((idx, wt / wt.sum()))
    for _ in range(iters):
        W = np.array([(W[idx] * wt[:, None]).sum(0) for idx, wt in nbr])
    return W


def skin(anchors, surf, nb, other=None, smooth=3, filt=None, fallback=None, G=None, seam_r=0.0):
    """anchors: per vertex an anchor, None, or a list of (anchor, share) whose skin weights are blended.
    seam_r > 0 (with G): also smooth across disconnected pieces within that distance."""
    bones = {}
    rows = []
    for i, a in enumerate(anchors):
        if a is None:
            a = []
        elif not isinstance(a, list):
            a = [(a, 1.0)]
        w = {}
        for an, sh in a:
            for kk, x in surf.eval(an, other)[2].items():
                w[kk] = w.get(kk, 0) + x * sh
        if filt is not None and filt[i] is not None:
            kept = {kk: x for kk, x in w.items() if filt[i](kk)}
            if sum(kept.values()) < 1e-3 and fallback:
                kept = fallback(i)
            w = kept
        rows.append(w)
        for kk in w:
            bones.setdefault(kk, len(bones))
    W = np.zeros((len(rows), len(bones)))
    for i, w in enumerate(rows):
        for kk, x in w.items():
            W[i, bones[kk]] = x
    W = smooth_field(W, nb, smooth, lam=0.4)
    if seam_r > 0 and G is not None:
        W = spatial_smooth(W, G, seam_r)
    names = list(bones)
    out = []
    for row in W:
        top = np.argsort(-row)[:4]
        tot = row[top].sum() or 1
        out.append([[names[j], float(row[j] / tot)] for j in top if row[j] > 1e-4])
    return out


def weight_fallback(reg, kind):
    """A vert whose filtered skin weights came out empty: palm -> the hand itself, shirt -> hips."""
    def fb(i):
        r_ = str(reg[i])
        if r_.startswith("arm"):
            return {r_[3:] + "Hand": 1.0}
        return {"Hips": 1.0} if kind in ("outfit", "shirt") else {}
    return fb


# The first-person rig deforms the arm only with these (vanilla FP_ARM_M/F use nothing else). Helper bones
# (_sup_*) and the palm bones (HandIndex0 ..) are keyed by third-person animations but not first-person ones, so
# there they sit at rest under their parent: glove fabric weighted to them stays behind (wrist helpers hang off the
# forearm, so a bent wrist dragged the T2 thumb base across the hand).
FP_SAFE = re.compile(r"^(Left|Right)(Arm|ForeArm|ForeArmRoll[1-4]|Hand|Hand(Index|Middle|Ring|Pinky)[1-5]|HandThumb[1-3])$")


def fp_safe_weights(weights, kind):
    """Gloves: every arm-side bone the FP rig doesn't deform with gives its weight to its nearest ancestor that it
    does; wrist helpers split between Hand and the last forearm twist bone (about what they do in third person).
    Other garments (sleeve cuffs): only the wrist helpers."""
    nodes = vb.load_json("body_male.json")["nodes"]
    parent = {n["name"]: nodes[n["parent"]]["name"] if n["parent"] >= 0 else None for n in nodes}

    def remap(b):
        if kind == "head" and region_of_bone(b) == "head" and b not in ("Head", "Neck", "Neck1", "Jaw"):
            # hats: facial bones (eyelids, brows, lips) animate blinks and expressions; a mask edge that follows
            # an eyelid folds over the eye in game. They ride on the head instead.
            return [("Head", 1.0)]
        m = re.match(r"^(Left|Right)_sup_wrist_", b)
        if m:
            return [(m.group(1) + "Hand", 0.5), (m.group(1) + "ForeArmRoll4", 0.5)]
        if kind != "hands" or FP_SAFE.match(b) or region_of_bone(b) not in ("armLeft", "armRight"):
            return [(b, 1.0)]
        a = parent.get(b)
        while a and not FP_SAFE.match(a):
            a = parent.get(a)
        return [(a or b, 1.0)]

    out = []
    for ws in weights:
        acc = {}
        for b, w in ws:
            for b2, f in remap(b):
                acc[b2] = acc.get(b2, 0.0) + w * f
        top = sorted(acc.items(), key=lambda t: -t[1])[:4]
        tot = sum(w for _, w in top) or 1.0
        out.append([[b, w / tot] for b, w in top if w > 1e-4])
    return out


def garment_weights(g, surf, reg, c, kind, B, nb):
    wa, wf = weight_setup(g, surf, reg, c, kind, B, nb)
    seam = 0.015 if kind in ("outfit", "shirt", "pants") else 0.0   # not gloves: neighbouring fingers are that close
    W = skin(wa, surf, nb, smooth=1 if kind == "hands" else 3, filt=wf, fallback=weight_fallback(reg, kind),
             G=vb.verts_np(g), seam_r=seam)
    return fp_safe_weights(W, kind)


# ---------------------------------------------------------------- layering: what lies under a garment
def surface_obj(name, V, T, N=None):
    """Blender object for a collision-only surface (no skin weights) with the 'unormal' attribute BodySurface reads."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in V], [], [tuple(int(i) for i in t) for t in T])
    me.update()
    if N is None:
        N = np.array([v.normal[:] for v in me.vertices])
    at = me.attributes.new("unormal", "FLOAT_VECTOR", "POINT")
    at.data.foreach_set("vector", np.asarray(N, float).reshape(-1))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def fitted_obj(item, sex, part="garment"):
    """A fitted garment from _work/out (Unity coords, flipped winding) back in Blender space."""
    path = os.path.join(OUT, f"{item}_{sex}.json")
    if not os.path.exists(path):
        print(f"  (no {item}_{sex}.json to layer over)")
        return None
    for p in json.load(open(path))["parts"]:
        if p["part"] == part:
            V = np.array(p["verts"])[:, [0, 2, 1]]
            T = np.array(p["tris"])[:, [0, 2, 1]]
            return surface_obj(f"{item}_{sex}_under", V, T)
    return None


class Points:
    """Point set with normals, shaped like BodySurface.data for unclip()."""
    def __init__(self, V, N):
        self.data = [dict(V=np.asarray(V, float), N=np.asarray(N, float))]


def boot_points(sex, zmax):
    """Every boot the pants may be worn over: the vanilla boots (the short-shaft feet_A variant where there is one;
    the DLL asks the game for it while a Visible Clothing outfit is drawn) and our own clothing shoes."""
    V, N = [], []
    path = os.path.join(vb.WORK, f"vanilla_boots_{sex}.json")
    if os.path.exists(path):
        d = json.load(open(path))
        for base in sorted({kk[:-2] if kk.endswith("_A") else kk for kk in d}):
            cand = [d[kk] for kk in (base, base + "_A") if kk in d]
            m = min(cand, key=lambda x: max(v[1] for v in x["verts"]))   # shorter shaft = the variant drawn
            V.append(np.array(m["verts"])[:, [0, 2, 1]])
            N.append(np.array(m["normals"])[:, [0, 2, 1]])
    for t in (1, 2, 3):
        p = os.path.join(OUT, f"ClothingFeetT{t}_{sex}.json")
        if os.path.exists(p):
            for part in json.load(open(p))["parts"]:
                V.append(np.array(part["verts"])[:, [0, 2, 1]])
                N.append(np.array(part["normals"])[:, [0, 2, 1]])
    if not V:
        return None
    V, N = np.concatenate(V), np.concatenate(N)
    keep = V[:, 2] < zmax
    print(f"  boots: {keep.sum()} points below z {zmax:.2f}")
    return Points(V[keep], N[keep])


def collision_surface(item, c, kind, parts, surf, sex):
    """Body plus what this garment must lie over: shirts over the head envelope (its base reaches down over the
    shoulders) and over the fitted garments in c["over"] (an untucked shirt over its pants). Garments worn under
    another one (c["under"]: a tucked shirt, the balaclava) are pulled under it afterwards (pull_under)."""
    names, labels = list(surf.names), {}
    if kind in ("outfit", "shirt"):
        names.append("head")
        labels["head"] = "under"
    for x in c.get("over", []):
        ob = fitted_obj(x, sex)
        if ob is not None:
            parts["_" + x] = ob
            names.append("_" + x)
            labels["_" + x] = "under"
    if names == list(surf.names):
        return surf
    print(f"  collision surface: {names}")
    return BodySurface(parts, names, region_of_bone, labels)


def pull_under(g, outers, coll, nb, margin=0.002, min_gap=0.0015, reach=0.03, iters=3):
    """Keep this garment under the outer garments it is worn with: wherever an outer garment covers a vert (a ray
    along the vert's normal meets it within `reach`), pull the vert in to `margin` inside it, smoothly, but never
    closer than `min_gap` to the skin (coll). Ray test, not nearest point, so open edges (hems, collars) only act
    where the outer garment really is over this one."""
    trees = [BVHTree.FromObject(o, bpy.context.evaluated_depsgraph_get()) for o in outers]
    for it in range(iters):
        G = vb.verts_np(g)
        g.data.update()
        Nv = np.array([v.normal[:] for v in g.data.vertices])
        D = np.zeros_like(G)
        n_in = 0
        for i, (v, n) in enumerate(zip(G, Nv)):
            best = 0.0
            if n @ coll.nearest(v)[1] < 0.2:   # inner lining faces the skin: it follows its outer surface (spread)
                continue
            for t in trees:
                hit = t.ray_cast(Vector(v - n * reach), Vector(n), 2 * reach)
                if hit[0] is not None:
                    need = margin - (hit[3] - reach)     # > 0: the outer surface is less than margin outside v
                    best = max(best, need)
            if best > 0:
                D[i] = -n * best
                n_in += 1
        if not n_in:
            break
        D = smooth_field(spread(D, G, r=0.008), nb, 3, lam=0.5)
        G = G + D
        # never into the skin
        for i in np.where(np.linalg.norm(D, axis=1) > 1e-6)[0]:
            pa, na, _ = coll.nearest(G[i])
            h = (G[i] - pa) @ na
            if h < min_gap:
                G[i] = G[i] + na * (min_gap - h)
        vb.set_verts(g, G)
        print(f"  under outer garments, pass {it}: {n_in} verts pulled in, max {np.linalg.norm(D, axis=1).max()*1000:.1f} mm")


def gaps(g, c, k, B):
    """Per-vertex gap + tight mask (looseness capped at loose_tight): shirts' armpit zone, and a hat's neck (a
    balaclava neck hugs the skin so any shirt collar lies over it)."""
    G = vb.verts_np(g)
    gap = np.full(len(G), float(k["gap"]))
    tight = c.get("_tight")
    tight = np.zeros(len(G), bool) if tight is None or len(tight) != len(G) else np.asarray(tight, bool).copy()
    if c.get("neck_tight") is not None:
        neck = G[:, 2] < B["Neck"].z + c["neck_tight"]
        gap[neck] = c.get("neck_gap", 0.002)
        tight |= neck
        print(f"  neck hugging the skin: {neck.sum()} verts")
    return gap, tight


def close_seams(g, maxd=0.025, min_island=40, iters=4):
    """Pieces that are sewn together in the real garment (a sleeve set into its armhole) but are separate islands
    in the mesh: each open-edge vert moves toward the nearest point on a neighbouring piece's open edge (both sides
    meet in the middle, a few passes), so no slit shows skin. Together with the seam-crossing weight smoothing they
    stay closed when the limb moves."""
    from mathutils.kdtree import KDTree
    bm = bmesh.new(); bm.from_mesh(g.data)
    bedges = [(e.verts[0].index, e.verts[1].index) for e in bm.edges if e.is_boundary]
    bm.free()
    if not bedges:
        return
    isl = np.full(len(g.data.vertices), -1)
    for k_, ix in enumerate(vb.islands(g)):
        if len(ix) >= min_island:
            isl[ix] = k_
    inc = {}
    for a_, b2 in bedges:
        inc.setdefault(a_, []).append(b2)
        inc.setdefault(b2, []).append(a_)
    bnd = np.array([i for i in inc if isl[i] >= 0], int)
    nb = adjacency(g)
    first = None
    for it in range(iters):
        G = vb.verts_np(g)
        kd = KDTree(len(bnd))
        for j, i in enumerate(bnd):
            kd.insert(G[i], j)
        kd.balance()
        D = np.zeros_like(G)
        moved, gapsz = [], []
        for i in bnd:
            best = None
            for co, j, d in kd.find_range(G[i], maxd):
                o = bnd[j]
                if isl[o] == isl[i] or isl[o] < 0:
                    continue
                for o2 in inc[o]:                     # nearest point on the other piece's open edges at o
                    a_, d_ = G[o], G[o2] - G[o]
                    t = np.clip((G[i] - a_) @ d_ / (d_ @ d_ + 1e-12), 0, 1)
                    q = a_ + t * d_
                    dq = np.linalg.norm(q - G[i])
                    if best is None or dq < best[1]:
                        best = (q, dq)
            if best and best[1] > 1e-5:
                D[i] = (best[0] - G[i]) * 0.5
                moved.append(i)
                gapsz.append(best[1])
        if not moved:
            break
        if first is None:
            first = (len(moved), np.median(gapsz))
        D = smooth_field(D, nb, 2, lam=0.3, pin=np.array(moved))   # ease the rows next to the seam along
        vb.set_verts(g, G + D)
    if first:
        print(f"  seams: {first[0]} open-edge verts closed onto a neighbouring piece (gap median {first[1]*1000:.1f} mm"
              f" -> {np.median(gapsz)*1000:.1f} mm after {it + 1} passes)")


def seam_lining(g, parts, maxd=0.03, reach=0.035, offset=0.0025, min_island=40):
    """A garment sewn from separate panels can show a slit of skin along its seams once sleeves are re-posed and the
    arms move. Under every seam, a strip of the body surface (offset a little, skinned exactly like the skin, textured
    from the nearest garment point) lines the garment, so a slit shows fabric. Holes inside a panel (cut-outs) are
    not seams and stay open."""
    from mathutils.kdtree import KDTree
    G = vb.verts_np(g)
    bm = bmesh.new(); bm.from_mesh(g.data)
    bnd = np.array(sorted({v.index for e in bm.edges if e.is_boundary for v in e.verts}), int)
    bm.free()
    isl = np.full(len(G), -1)
    for k_, ix in enumerate(vb.islands(g)):
        if len(ix) >= min_island:
            isl[ix] = k_
    bnd = bnd[isl[bnd] >= 0]
    kd = KDTree(len(bnd))
    for j, i in enumerate(bnd):
        kd.insert(G[i], j)
    kd.balance()
    seam = [i for i in bnd if any(isl[bnd[j]] != isl[i] for _, j, _ in kd.find_range(G[i], maxd))]
    if not seam:
        return None
    ks = KDTree(len(seam))
    for j, i in enumerate(seam):
        ks.insert(G[i], j)
    ks.balance()
    tree = BVHTree.FromObject(g, bpy.context.evaluated_depsgraph_get())
    body = parts["body"]
    me = body.data
    BV = vb.verts_np(body)
    BN = np.zeros(len(me.vertices) * 3); me.attributes["unormal"].data.foreach_get("vector", BN); BN = BN.reshape(-1, 3)
    faces = []
    for poly in me.polygons:
        ctr = BV[list(poly.vertices)].mean(0)
        if ks.find(ctr)[2] > reach:
            continue
        n = BN[list(poly.vertices)].mean(0); n /= np.linalg.norm(n) + 1e-9
        # only where the garment is over the skin: of 5 rays (normal + 4 tilted 35 deg) at least 2 meet it, so a
        # slit (fabric all around) counts and skin just past a collar or hem (fabric on one side only) doesn't
        t1 = np.cross(n, [0, 0, 1] if abs(n[2]) < 0.9 else [1, 0, 0]); t1 /= np.linalg.norm(t1)
        t2 = np.cross(n, t1)
        dirs = [n] + [n * 0.82 + t * 0.57 for t in (t1, -t1, t2, -t2)]
        if sum(tree.ray_cast(Vector(ctr), Vector(d), 0.05)[0] is not None for d in dirs) < 2:
            continue
        faces.append(list(poly.vertices))
    if not faces:
        return None
    used = sorted({i for f in faces for i in f})
    remap = {v: j for j, v in enumerate(used)}
    V = BV[used] + BN[used] * offset
    kg = KDTree(len(G))
    for i, v in enumerate(G):
        kg.insert(v, i)
    kg.balance()
    uvl = g.data.uv_layers.active.data
    vuv = {}
    for lp in g.data.loops:
        vuv.setdefault(lp.vertex_index, tuple(uvl[lp.index].uv))
    UV = [vuv.get(kg.find(v)[1], (0.0, 0.0)) for v in V]
    gn = [x.name for x in body.vertex_groups]
    W = []
    for i in used:
        ws = sorted(((gn[x.group], x.weight) for x in me.vertices[i].groups), key=lambda t: -t[1])[:4]
        tot = sum(w for _, w in ws) or 1
        W.append([[b, w / tot] for b, w in ws])
    T = []
    for f in faces:
        for t in range(1, len(f) - 1):
            T.append([remap[f[0]], remap[f[t]], remap[f[t + 1]]])
    print(f"  seam lining: {len(T)} triangles under {len(seam)} seam verts")
    return dict(V=V, N=BN[used], UV=UV, W=W, T=T)


def _rotm(axis, deg):
    q = Matrix.Rotation(math.radians(deg), 3, Vector(axis).normalized())
    M = np.eye(4); M[:3, :3] = np.array(q)
    return M


def fist_skin_matrices(sex):
    """Bone skinning matrices (Unity space) for a tight fist, the same pose tools/pose_test.py calls 'fist'."""
    nodes = vb.load_json(f"body_{sex}.json")["nodes"]
    idx = {n["name"]: i for i, n in enumerate(nodes)}
    REST = [np.array(n["world"]) for n in nodes]
    J = lambda b: REST[idx[b]][:3, 3]
    R = {}
    for s in ("Left", "Right"):
        across = J(s + "HandIndex1") - J(s + "HandPinky1")
        sg = 1 if s == "Left" else -1
        for f in ("Index", "Middle", "Ring", "Pinky"):
            for k_ in (1, 2, 3):
                R[f"{s}Hand{f}{k_}"] = _rotm(across * sg, 65)
        R[s + "HandThumb2"] = _rotm(across * sg, 35)
    W = [None] * len(nodes)
    for i, n in enumerate(nodes):
        p = n["parent"]
        L = np.linalg.inv(REST[p]) @ REST[i] if p >= 0 else REST[i]
        W[i] = (W[p] if p >= 0 else np.eye(4)) @ L
        if n["name"] in R:
            T, Ti = np.eye(4), np.eye(4)
            T[:3, 3], Ti[:3, 3] = W[i][:3, 3], -W[i][:3, 3]
            W[i] = T @ R[n["name"]] @ Ti @ W[i]
    return {n["name"]: W[i] @ np.linalg.inv(REST[i]) for i, n in enumerate(nodes)}


def _lbs(V, weights, S):
    out = np.zeros_like(V)
    for k_, (v, ws) in enumerate(zip(V, weights)):
        acc, tot = np.zeros(3), 0.0
        for b, w in ws:
            if b in S:
                acc += w * (S[b][:3, :3] @ v + S[b][:3, 3]); tot += w
        out[k_] = acc / tot if tot > 0 else v
    return out


def fist_clearance(g, weights, parts, sex, nb, gap=0.0015, iters=5):
    """Snug gloves: where knuckles or fingertips come through the glove in a fist, push just those spots of the glove
    out (in the rest shape) by the depth + gap. Rest-pose fit elsewhere is untouched."""
    S = fist_skin_matrices(sex)
    hand = parts["hands"]
    gn = [x.name for x in hand.vertex_groups]
    HW = [[(gn[x.group], x.weight) for x in v.groups] for v in hand.data.vertices]
    H = vb.verts_np(hand)[:, [0, 2, 1]]                       # Unity space for the bone matrices
    HN = np.zeros(len(H) * 3); hand.data.attributes["unormal"].data.foreach_get("vector", HN)
    HN = HN.reshape(-1, 3)[:, [0, 2, 1]]
    Hp = _lbs(H, HW, S)
    HNp = _lbs(H + HN * 0.01, HW, S) - Hp
    HNp /= np.linalg.norm(HNp, axis=1, keepdims=True) + 1e-12
    tris = [tuple(p.vertices) for p in g.data.polygons]
    for it in range(iters):
        G = vb.verts_np(g)
        Gp = _lbs(G[:, [0, 2, 1]], weights, S)
        bvh = BVHTree.FromPolygons([tuple(v) for v in Gp], tris)
        need = np.zeros(len(G))
        hits = 0
        Hb = H[:, [0, 2, 1]]                                   # skin rest positions, Blender space
        for p, n, h0 in zip(Hp, HNp, Hb):
            # start 4 mm under the skin (a finger is ~15 mm thick: deeper starts exit the far side of the finger)
            hit = bvh.ray_cast(Vector(p - n * 0.004), Vector(n), 0.03)
            if hit[0] is None:
                continue
            # only the fabric that covers this skin at rest (not the palm a curled fingertip presses into)
            if np.linalg.norm(G[tris[hit[2]][0]] - h0) > 0.02:
                continue
            s_ = hit[3] - 0.004                                # glove surface along the skin normal (< 0: inside)
            if s_ < gap:
                hits += 1
                for v in tris[hit[2]]:
                    need[v] = max(need[v], gap - s_)
        if not hits:
            break
        # push away from the hand (not along vertex normals: mirrored / hand-made gloves may face either way)
        hb = BVHTree.FromObject(hand, bpy.context.evaluated_depsgraph_get())
        Dir = np.zeros_like(G)
        for i in np.where(need > 0)[0]:
            loc, nrm, _, d_ = hb.find_nearest(Vector(G[i]))
            v = G[i] - np.array(loc)
            Dir[i] = v / np.linalg.norm(v) if np.linalg.norm(v) > 1e-4 else np.array(nrm)
        D = smooth_field((Dir * need[:, None]), nb, 2, lam=0.5)
        D = spread(D, G, r=0.004)
        vb.set_verts(g, G + D)
        print(f"  fist clearance pass {it}: {hits} skin points at/through the glove, max push {need.max()*1000:.1f} mm")


def finish(item, g, parts, B, reg, c, k, nb, sex, pre, iters=3, loose=None, loose_arm="kind", unclip_on=True,
           unclip_reach=0.03):
    """Shared by the automatic fit and the hand-fitting rebuild: conform against the body and whatever lies under
    the garment, unclip, keep cloth pieces as modelled, skin. Returns (surf, anchors, weights)."""
    kind = c["kind"]
    if kind in ("outfit", "shirt", "pants"):   # not hats: the mask's edge would snap onto the hood's face opening
        close_seams(g, maxd=0.06)            # re-posed sleeves open their armholes by up to ~6 cm under the arm
    surf = BodySurface(parts, k["parts"], region_of_bone)
    coll = collision_surface(item, c, kind, parts, surf, sex)
    gap, tight = gaps(g, c, k, B)
    anchors = conform(g, surf, reg, gap, k["loose"] if loose is None else loose, nb, iters=iters,
                      loose_arm=k.get("loose_arm") if loose_arm == "kind" else loose_arm, tight=tight,
                      loose_tight=c.get("loose_tight", 0.006 if c.get("neck_tight") is None else 0.004), coll=coll)
    if unclip_on:
        unclip(g, coll, gap, nb, zmin=c.get("unclip_zmin", -9.0), smooth=k.get("unclip_smooth", 4),
               ymax=c.get("unclip_ymax", 9.0), reach=c.get("unclip_reach", unclip_reach))
        if kind == "pants":
            boots = boot_points(sex, B["LeftLeg"].z)
            if boots is not None:
                unclip(g, boots, k["gap"], nb, iters=3, reach=0.035)
    outers = [o for o in (fitted_obj(x, sex) for x in c.get("under", [])) if o is not None]
    if outers:
        pull_under(g, outers, coll, nb)
    if kind in ("outfit", "shirt", "pants"):
        close_seams(g, maxd=0.012)          # conform / unclip move the two sides of a seam a little differently
    keep_free(g, pre, c)
    c["_lining"] = seam_lining(g, parts) if c.get("seam_lining") else None
    weights = garment_weights(g, surf, reg, c, kind, B, nb)
    if kind == "hands" and c.get("fist_clearance", True):
        fist_clearance(g, weights, parts, sex, nb)
    return surf, anchors, weights


def export(g, weights, tex, part, faces=None):
    """faces: optional predicate on a triangle's 3 vertex indices (to split a garment into parts)."""
    me = g.data
    me.calc_loop_triangles()
    uvl = me.uv_layers.active.data
    key2i, verts, normals, uvs, ws, tris = {}, [], [], [], [], []
    for lt in me.loop_triangles:
        if faces is not None and not faces(lt.vertices):
            continue
        tri = []
        for li in lt.loops:
            vi = me.loops[li].vertex_index
            uv = tuple(round(x, 6) for x in uvl[li].uv)
            k = (vi, uv)
            if k not in key2i:
                v = me.vertices[vi]
                key2i[k] = len(verts)
                verts.append([v.co.x, v.co.z, v.co.y])
                normals.append([v.normal.x, v.normal.z, v.normal.y])
                uvs.append(list(uv))
                ws.append(weights[vi])
            tri.append(key2i[k])
        tris.append([tri[0], tri[2], tri[1]])
    return dict(part=part, texture=tex, verts=verts, normals=normals, uv=uvs, weights=ws, tris=tris)


def garment_texture(item):
    """Original Tripo basecolor -> _work/out/<item>.png (2048)."""
    img = next(i for i in bpy.data.images if i.size[0] > 0 and i.name != "Render Result")
    dst = os.path.join(OUT, f"{item}.png")
    if not os.path.exists(dst):
        from_path = bpy.path.abspath(img.filepath)
        cp = img.copy()
        cp.scale(2048, 2048)
        cp.filepath_raw = dst
        cp.file_format = "PNG"
        cp.save()
    return f"{item}.png"


def join_seams(g, dist, min_island=40):
    """A garment modelled as separate panels whose edges overlap a few mm (sewn seams): join each open-edge vert to
    the nearest open-edge vert of another panel within dist, so the panels move as one cloth when sleeves are
    re-posed and skinned. Holes inside one panel (cut-outs) are left alone."""
    bm = bmesh.new(); bm.from_mesh(g.data)
    bm.verts.ensure_lookup_table()
    isl = np.full(len(bm.verts), -1)
    for k_, ix in enumerate(vb.islands(g)):
        if len(ix) >= min_island:
            isl[ix] = k_
    bnd = [v for v in {v for e in bm.edges if e.is_boundary for v in e.verts} if isl[v.index] >= 0]
    from mathutils.kdtree import KDTree
    kd = KDTree(len(bnd))
    for j, v in enumerate(bnd):
        kd.insert(v.co, j)
    kd.balance()
    target, n0 = {}, len(set(isl[isl >= 0]))
    for v in bnd:
        if v in target:
            continue
        best = None
        for co, j, d in kd.find_range(v.co, dist):
            o = bnd[j]
            if isl[o.index] != isl[v.index] and o not in target and (best is None or d < best[1]):
                best = (o, d)
        if best:
            o = best[0]
            o.co = (v.co + o.co) / 2
            target[v] = o
    bmesh.ops.weld_verts(bm, targetmap=target)
    bm.to_mesh(g.data); bm.free()
    g.data.update()
    print(f"  joined seams: {len(target)} open-edge verts welded across panels (<= {dist*1000:.0f} mm); "
          f"{n0} panels -> {len([i for i in vb.islands(g) if len(i) >= min_island])}")


def fit_one(item, c, sex, tex_holder):
    vb.clear()
    parts, B, _ = vb.load_body(sex, head="ref" if c["kind"] == "head" else "env")
    g = vb.import_garment(item)
    tex_holder.append(garment_texture(item))
    fr = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frames", item + ".json")
    if os.path.exists(fr):  # re-exported model in a different pose: rotate into the frame its landmarks use
        f = json.load(open(fr))
        vb.set_verts(g, (vb.verts_np(g) - np.array(f["c0"])) @ np.array(f["R"]).T)
    bm = bmesh.new(); bm.from_mesh(g.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)  # Tripo splits verts on UV seams: weld for smoothing
    bm.to_mesh(g.data); bm.free()
    if c.get("join_seams"):
        join_seams(g, c["join_seams"])
    if c["kind"] == "hands":  # left glove + mirrored right glove in one object
        n0 = len(g.data.vertices)
        _ADJ["nb"] = adjacency(g)
        L = align_hands(g, parts, B, c, "Left")
        Rr = align_hands(g, parts, B, c, "Right")
        r = g.copy(); r.data = g.data.copy(); bpy.context.scene.collection.objects.link(r)
        vb.set_verts(g, L); vb.set_verts(r, Rr)
        r.data.flip_normals()  # mirroring turns the faces inside out
        bpy.ops.object.select_all(action="DESELECT")
        g.select_set(True); r.select_set(True); bpy.context.view_layer.objects.active = g
        bpy.ops.object.join()
        reg = np.array(["armLeft"] * n0 + ["armRight"] * n0, dtype=object)
        z = np.zeros((n0, len(FINGERS)))
        c["_fingerW"] = np.vstack([c.pop("_W_Left", z), c.pop("_W_Right", z)])
    else:
        reg = globals()["align_" + c["kind"]](g, parts, B, c)
    return parts, B, g, reg


def export_parts(g, weights, tex, c):
    free = c.get("_free")
    if free is None:
        out = [export(g, weights, tex, "garment")]
    else:
        fs = set(int(i) for i in free)
        out = [export(g, weights, tex, "garment", lambda t: not any(v in fs for v in t)),
               export(g, weights, tex, "strings", lambda t: all(v in fs for v in t))]
    L = c.get("_lining")
    if L:   # own part (the hand-fitting file leaves it out; pack_unity merges it into the garment mesh)
        out.append(dict(part="lining", texture=tex, verts=[[v[0], v[2], v[1]] for v in L["V"]],
                        normals=[[n[0], n[2], n[1]] for n in L["N"]], uv=[list(u) for u in L["UV"]],
                        weights=L["W"], tris=[[t[0], t[2], t[1]] for t in L["T"]]))
    return out


def keep_free(g, pre, c):
    """Cloth pieces keep their modelled shape: undo any conform/unclip moves on them."""
    if c.get("_free") is not None:
        G = vb.verts_np(g)
        G[c["_free"]] = pre[c["_free"]]
        vb.set_verts(g, G)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    item = argv[0]
    c = fit.CFG[item]
    k = dict(KIND[c["kind"]], **c.get("kind_over", {}))
    os.makedirs(OUT, exist_ok=True)
    texh = []
    parts, B, g, reg = fit_one(item, c, "male", texh)
    tex = texh[0]
    nb = adjacency(g)
    pre = vb.verts_np(g)
    surf, anchors, weights = finish(item, g, parts, B, reg, c, k, nb, "male", pre)
    male_G = vb.verts_np(g)
    json.dump(dict(item=item, sex="male", parts=export_parts(g, weights, tex, c)),
              open(os.path.join(OUT, f"{item}_male.json"), "w"))
    # ---- female
    fparts, fB, _ = vb.load_body("female", head="ref" if c["kind"] == "head" else "env")
    fsurf = BodySurface(fparts, k["parts"], region_of_bone)
    same = all(np.array_equal(a["T"], b["T"]) for a, b in zip(surf.data, fsurf.data))
    if same and not k.get("refit_female"):  # move each vert by the body difference at its anchor, re-conform
        F = male_G.copy()
        for i, a in enumerate(anchors):
            if a:
                F[i] = male_G[i] + (surf.eval(a, fsurf)[0] - surf.eval(a)[0])
        vb.set_verts(g, F)
        pre = F.copy()
        _, _, fweights = finish(item, g, fparts, fB, reg, c, k, nb, "female", pre, iters=2)
    else:
        print("female: fitting from scratch")
        fparts, fB, g, reg = fit_one(item, c, "female", [])
        nb = adjacency(g)
        pre = vb.verts_np(g)
        _, _, fweights = finish(item, g, fparts, fB, reg, c, k, nb, "female", pre)
    json.dump(dict(item=item, sex="female", parts=export_parts(g, fweights, tex, c)),
              open(os.path.join(OUT, f"{item}_female.json"), "w"))
    print("DONE", item)


if __name__ == "__main__":
    main()
