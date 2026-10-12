"""Collect each item's Tripo PBR maps from `7D2D Clothing models/<Item>.fbm/` and write what Unity's Standard
game's character shader (Game/Character) wants into _work/out/:
    <Item>.png       albedo (2048)
    <Item>_n.png     normal map (2048, OpenGL / +Y like Unity)
    <Item>_rmoe.png  R = roughness, G = metallic, B = occlusion (1), A = emission (0)  (1024; low-frequency data)
                     -- the same packing as vanilla gear's _RMOE maps

python tools/prep_textures.py [Item ...]

Tripo names the maps inconsistently between exports, so they are found by pattern:
  albedo : *_basecolor*  | tripo_rgb_*    | tripo_image_*_0_0*
  normal : *_normal*     | tripo_normal_* | tripo_image_*_0_3*
  rough  : *_roughness*      metal : *_metallic*
A metallic map that is mostly bright is a bad export for cloth (it would make wool look like chrome): zeroed.
"""
import os, sys, glob, re
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "7D2D Clothing models")
OUT = os.path.join(ROOT, "_work", "out")
PATS = {
    "albedo": [r"_basecolor", r"^tripo_rgb_", r"^tripo_image_.*_0_0"],
    "normal": [r"_normal", r"^tripo_normal_", r"^tripo_image_.*_0_3"],
    "rough": [r"_roughness"],
    "metal": [r"_metallic"],
}


# per item: Tripo sometimes bakes a glossy / metal-speckled map onto plain fabric (the T2 beanie shone in game)
OVERRIDE = {
    "ClothingHeadT1": dict(rough_min=0.85, no_metal=True),   # knit hats / balaclava: wool, no metal
    "ClothingHeadT2": dict(rough_min=0.85, no_metal=True),
    "ClothingHeadT3": dict(rough_min=0.85, no_metal=True),
}


def find(folder):
    files = os.listdir(folder)
    got = {}
    for k, pats in PATS.items():
        for pat in pats:
            hit = [f for f in files if re.search(pat, f, re.I)]
            if hit:
                got[k] = os.path.join(folder, sorted(hit)[0])
                break
    return got


def load(p, mode, size):
    im = Image.open(p).convert(mode)
    return im.resize((size, size), Image.LANCZOS) if im.size != (size, size) else im


def prep(item):
    folder = os.path.join(MODELS, item + ".fbm")
    if not os.path.isdir(folder):
        print(f"{item}: no {item}.fbm folder"); return
    m = find(folder)
    if "albedo" not in m:
        print(f"{item}: no albedo found in {os.listdir(folder)}"); return
    load(m["albedo"], "RGB", 2048).save(os.path.join(OUT, f"{item}.png"))
    note = []
    if "normal" in m:
        load(m["normal"], "RGB", 2048).save(os.path.join(OUT, f"{item}_n.png")); note.append("normal")
    elif os.path.exists(os.path.join(OUT, f"{item}_n.png")):
        os.remove(os.path.join(OUT, f"{item}_n.png"))
    S = 1024
    rough = np.asarray(load(m["rough"], "L", S), np.float32) / 255 if "rough" in m else np.full((S, S), 0.8, np.float32)
    metal = np.asarray(load(m["metal"], "L", S), np.float32) / 255 if "metal" in m else np.zeros((S, S), np.float32)
    o = OVERRIDE.get(item, {})
    rough = np.maximum(rough, o.get("rough_min", 0.7))   # cloth/leather is never glossy; some Tripo roughness maps are
    if o.get("no_metal"):
        metal[:] = 0
    if metal.mean() > 0.25:
        note.append(f"metallic ignored (mean {metal.mean():.2f})")
        metal[:] = 0
    rmoe = np.zeros((S, S, 4), np.uint8)
    rmoe[..., 0] = (rough * 255).astype(np.uint8)
    rmoe[..., 1] = (metal * 255).astype(np.uint8)
    rmoe[..., 2] = 255
    Image.fromarray(rmoe, "RGBA").save(os.path.join(OUT, f"{item}_rmoe.png"))
    old_ms = os.path.join(OUT, f"{item}_ms.png")
    if os.path.exists(old_ms):
        os.remove(old_ms)
    note.append(f"rough {rough.mean():.2f} metal {metal.mean():.2f}")
    print(f"{item}: albedo + {', '.join(note) or 'nothing else'}")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    items = sys.argv[1:] or sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(MODELS, "Clothing*.fbm")))
    for it in items:
        prep(it)
