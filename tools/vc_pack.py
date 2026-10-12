"""Clothing packs: the Visible Clothing tools build either the base mod (no pack) or a *pack* - a folder with
pack.json, its models and its own fitting file - into a separate add-on mod that needs Visible Clothing installed.

Pick the pack with the environment variable VC_PACK=<pack folder> (tools/vcpack.sh sets it). Plain Python (no
Blender), so pack_unity.py / prep_textures.py / make_mod.py can use it too.

pack.json:
{
  "name": "VisibleClothing_MyPack",      // mod folder + bundle name; keep the VisibleClothing_ prefix (load order)
  "display_name": "My Clothing Pack", "author": "you", "version": "1.0.0", "description": "...",
  "items": [
    {
      "id": "RedBandana",                // unique, letters/digits; prefab gear{Male,Female}<id>
      "kind": "head",                    // head | outfit | shirt | pants | hands | feet
      "model": "models/RedBandana.fbx",  // default models/<id>.fbx; textures in models/<id>.fbm/ (Tripo layout)
      "game_item": "clothingHeadRedBandana",
      "new_item": {"extends": "clothingHeadT1", "name": "Red Bandana", "description": "A bandana."},
      "hair_mask": "Hat", "facial_hair_mask": "Full", "excludes": "",
      ...                                 // any fitting option (see docs/MAKING_CLOTHING.md)
    }
  ]
}
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_WORK = os.path.join(ROOT, "_work")
BASE_OUT = os.path.join(BASE_WORK, "out")

PACK_DIR = os.path.abspath(os.environ["VC_PACK"]) if os.environ.get("VC_PACK") else None
PACK = json.load(open(os.path.join(PACK_DIR, "pack.json"), encoding="utf-8")) if PACK_DIR else None

KINDS = ("head", "outfit", "shirt", "pants", "hands", "feet")
# transform (part) name inside the prefab per kind; the game finds it through SDCS TransformName
PART_OF_KIND = {"head": "head", "outfit": "bodyVC", "shirt": "bodyVC", "pants": "bodyVC", "hands": "handsVC",
                "feet": "feetVC"}
# fit in this order: what a garment layers against is fitted first (shoes, gloves, pants -> shirts -> hats)
KIND_ORDER = ("feet", "hands", "pants", "outfit", "shirt", "head")
# defaults every pack item gets (any key can be overridden in pack.json)
KIND_DEFAULTS = {
    "head": dict(hair_mask="Hat", facial_hair_mask="Full", excludes=""),
    "outfit": dict(hair_mask=None, facial_hair_mask=None, excludes=""),
    "shirt": dict(hair_mask=None, facial_hair_mask=None, excludes=""),
    "pants": dict(hair_mask=None, facial_hair_mask=None, excludes=""),
    "hands": dict(hair_mask=None, facial_hair_mask=None, excludes=""),
    "feet": dict(hair_mask=None, facial_hair_mask=None, excludes=""),
}

if PACK:
    NAME = PACK["name"]
    MODELS = os.path.join(PACK_DIR, "models")
    OUT = os.path.join(PACK_DIR, "build", "out")
    FIT_BLEND = os.path.join(PACK_DIR, "fitting.blend")
    FIT_TEX = os.path.join(PACK_DIR, "build", "fitting_textures")
    UNITY_ROOT = f"Assets/VC/Packs/{NAME}"
    DIST = os.path.join(PACK_DIR, "dist", NAME)
else:
    NAME = "VisibleClothing"
    MODELS = os.path.join(ROOT, "7D2D Clothing models")
    OUT = BASE_OUT
    FIT_BLEND = os.path.join(ROOT, "fitting", "VisibleClothing_Fitting.blend")
    FIT_TEX = os.path.join(ROOT, "fitting", "textures")
    UNITY_ROOT = "Assets/VC"
    DIST = os.path.join(ROOT, "Mod", "VisibleClothing")
BUNDLE = NAME.lower() + ".unity3d"
UNITY_DIR = os.path.join(ROOT, "unity", *UNITY_ROOT.split("/"))


def items():
    """id -> item config (pack items only; None for the base mod, whose items live in fit.CFG)."""
    if not PACK:
        return None
    out = {}
    for it in PACK["items"]:
        k = it["kind"]
        assert k in KINDS, f"{it['id']}: kind must be one of {KINDS}"
        out[it["id"]] = dict(KIND_DEFAULTS[k], **it)
    return out


def base_kind(item):
    """Kind of a base Visible Clothing item from its name (ClothingOutfitT2 -> outfit / shirt)."""
    for k, kind in (("Outfit", "outfit"), ("Pants", "pants"), ("Head", "head"), ("Hands", "hands"), ("Feet", "feet")):
        if item.startswith("Clothing" + k):
            return kind
    return None


def kind_of(item):
    its = items()
    if its is not None and item in its:
        return its[item]["kind"]
    return base_kind(item)


def merge_target(item):
    """Pants are merged into an outfit's prefab (one chest-slot model): the outfit id, or None."""
    its = items()
    if its is not None:
        return its.get(item, {}).get("merge_into")
    if item.startswith("ClothingPants"):
        return item.replace("Pants", "Outfit")
    return None


def model_path(item):
    its = items()
    rel = (its or {}).get(item, {}).get("model") if its else None
    if rel:
        return os.path.join(PACK_DIR, rel)
    return os.path.join(MODELS, item + ".fbx")


def texture_dir(item):
    """Folder holding the item's PBR maps (Tripo's <model>.fbm layout), or None."""
    its = items()
    rel = (its or {}).get(item, {}).get("textures") if its else None
    if rel:
        return os.path.join(PACK_DIR, rel)
    d = os.path.splitext(model_path(item))[0] + ".fbm"
    return d if os.path.isdir(d) else None


def out_dirs():
    """Fitted garments to layer against, this pack's first: [pack out, base out] (base only without a pack)."""
    return [OUT, BASE_OUT] if PACK else [BASE_OUT]
