# Making your own visible clothing

Visible Clothing is also a framework. With it installed, **any** item in a clothing slot (head, chest, hands, feet)
that has a model gets the same treatment as the built-in clothing:

- hidden while armor in the matching slot is drawn; shown when that slot is empty or the armor is set to **Hidden**
  in the cosmetics menu;
- materials named `VC_*` are switched to the game's own character shader (vanilla lighting, every graphics API,
  vanilla first-person collar clipping);
- hats that carry per-head blend shapes are fitted to the character's head (16 faces per sex);
- while a visible outfit is drawn, vanilla boots switch to their short-shaft variant so pants can go over them;
- full gloves can hide the hand underneath (`Excludes` = `hands`).

Your add-on is a normal mod folder (XML + an asset bundle) that **requires Visible Clothing**. It has no DLL of its
own. Name it `VisibleClothing_<Something>` so it loads after Visible Clothing (mods load in folder-name order).

There are three ways to make one.

| Route | You need | Good for |
|---|---|---|
| [A. XML only](#a-xml-only-reuse-a-model) | a text editor | new items that reuse a Visible Clothing model |
| [B. Clothing pack tools](#b-clothing-pack-tools-recommended) | Blender, Unity, this repository, your game | your own 3D models |
| [C. Your own pipeline](#c-your-own-unity-pipeline-the-conventions) | Unity + your own tools | experienced modders |

---

## A. XML only: reuse a model

See [`examples/XmlOnlyExample`](../examples/XmlOnlyExample) (a ready mod: copy `VisibleClothing_XmlExample` into
`Mods`). A new item `Extends` an existing clothing item (so it sits in that clothing slot) and points its `SDCS`
model at Visible Clothing's bundle:

```xml
<append xpath="/items">
  <item name="clothingHeadXmlExampleBalaclava">
    <property name="Extends" value="clothingHeadT1"/>
    <property name="CustomIcon" value="clothingHeadT3"/>
    <property class="SDCS">
      <property name="Prefab" value="#@modfolder(VisibleClothing):Resources/VisibleClothing.unity3d?gear{sex}ClothingHeadT3"/>
      <property name="TransformName" value="head"/>
      <property name="Excludes" value=""/>
      <property name="HairMaskType" value="None"/>
      <property name="FacialHairMaskType" value="None"/>
    </property>
  </item>
</append>
```

Models in Visible Clothing's bundle (`{sex}` becomes `Male` / `Female`):

| Slot | Prefab | TransformName |
|---|---|---|
| Head | `gear{sex}ClothingHeadT1` (beanie), `T2` (beanie), `T3` (balaclava) | `head` |
| Chest | `gear{sex}ClothingOutfitT1`, `T2`, `T3` (shirt + pants) | `bodyVC` |
| Hands | `gear{sex}ClothingHandsT1` (fingerless), `T2`, `T3` | `handsVC` |
| Feet | `gear{sex}ClothingFeetT1`, `T2`, `T3` | `feetVC` |

---

## B. Clothing pack tools (recommended)

A **pack** is a folder with a `pack.json`, your models and a fitting file. The tools fit your models to the game's
body, skin them, make the female versions, build the asset bundle and write the add-on mod for you.
See [`examples/ExamplePack`](../examples/ExamplePack).

### One-time setup

1. Install Blender 5.x, Unity **2022.3.62f2** (Unity Hub), Git for Windows (Git Bash), Python 3 with
   `pip install numpy scipy pillow UnityPy`.
2. Clone this repository. If Blender, Unity or the game are not at the default paths, set `BLENDER`, `UNITY` and
   `GAME_DIR` (see the top of `tools/vcpack.sh`).
3. Read the vanilla bodies, the 32 heads and the boots from **your own** game install (nothing from the game is in
   this repository; this writes `_work/`, which is never committed):
   ```bash
   bash tools/extract_game_data.sh
   ```

### Workflow

All commands run in **Git Bash** from the repository folder, with the game closed when installing.

1. **Create a pack**
   ```bash
   bash tools/vcpack.sh new packs/MyPack VisibleClothing_MyPack
   ```
   Put your models in `packs/MyPack/models/`: `<id>.fbx`, textures in `<id>.fbm/` (the layout Tripo and most
   exporters produce: base color, normal, roughness, metallic are found by name). Edit `pack.json` (see below).
2. **Make the fitting file**
   ```bash
   bash tools/vcpack.sh fitting packs/MyPack
   ```
   Open `packs/MyPack/fitting.blend`. Every item is in the **Clothing Male** collection, roughly placed on its body
   slot. Fit each one onto the body: move, rotate, scale, sculpt, proportional-edit, modifiers (applied on build).
   - The head is **White 04**. Fit hats to it: every other face gets the hat morphed onto its own shape.
   - Keep a few millimetres between cloth and skin.
   - Gloves: one glove on the **left** hand is enough; the right one is mirrored automatically. Both is fine too.
   - Female versions are made automatically from the male fit. To fit one yourself, show *Body Female*, put a copy
     of the item (same name) in **Clothing Female**.
   - Running `fitting` again later only adds items that are not in the file yet.
3. **Build**
   ```bash
   bash tools/vcpack.sh build packs/MyPack --raw            # --raw: exactly your shape
   bash tools/vcpack.sh build packs/MyPack                  # or: plus automatic clean-up and layering
   bash tools/vcpack.sh build packs/MyPack MyHat --raw      # only some items
   ```
   The add-on mod is written to `packs/MyPack/dist/<name>/`.
4. **Install and test**: `bash tools/vcpack.sh install packs/MyPack` (or add `--install` to `build`). New items are in
   the creative menu; give them recipes / loot with your own XML in `packs/MyPack/Config/` (copied into the mod).
5. Optional checks without the game: `tools/pose_test.py` (posed renders: fist, arms up, stride, ...).

Without `--raw` the build also: pushes cloth out of the skin, keeps layering (shirts over the head and their pants,
pants over boots and shoes, shirt sleeves over every glove, `under` garments pulled under), closes slits between separate shirt panels, and adds
fist clearance to gloves. Hats always skip the seam closing; gloves only get pushed out where they are inside the skin.

### `pack.json`

```jsonc
{
  "name": "VisibleClothing_MyPack",   // mod folder + bundle name (keep the VisibleClothing_ prefix)
  "display_name": "My Pack", "author": "you", "version": "1.0.0", "description": "...", "website": "",
  "items": [ { ...item... } ]
}
```

| Item key | Meaning |
|---|---|
| `id` | unique name, letters / digits; the prefabs are `gearMale<id>` / `gearFemale<id>` |
| `kind` | `head`, `outfit` / `shirt` (chest), `pants`, `hands`, `feet` |
| `model` | model file, default `models/<id>.fbx`; several meshes are joined |
| `textures` | texture folder, default `models/<id>.fbm` (else the fitting file's image, matte) |
| `game_item` | the item this model is for: an existing clothing item, or the name of a new one |
| `new_item` | create `game_item`: `{"extends": "clothingHeadT1", "name": "...", "description": "...", "icon": "...", "icon_tint": "ff0000", "properties": {"EconomicValue": "300"}}` |
| `hair_mask` | `Full` (all hair), `Hat` (the game's hat hair), `None` (no hair, e.g. balaclava) |
| `facial_hair_mask` | `Full` or `None` |
| `excludes` | body parts to hide while worn, e.g. `hands` for full gloves (vanilla gloves do this) |
| `merge_into` | for `pants`: the outfit `id` they belong to (one chest-slot model); without it pants are their own chest item |
| `over` | items this one is fitted over (e.g. a shirt over its pants): `["MyPants"]`, base items work too (`ClothingPantsT2`) |
| `under` | items this one is pulled under (e.g. a tucked shirt under its pants, a balaclava under shirts) |
| `over_gloves` | shirts: `false` = don't push the sleeve ends out over the gloves (default `true`: Visible Clothing's three gloves and the pack's own) |
| `strings` | `true`: small loose pieces at the front of the waist get cloth physics (drawstrings) |
| `neck_tight`, `neck_gap` | hats: the neck below `Neck + neck_tight` m hugs the skin at `neck_gap` m (so collars cover it) |
| `rough_min`, `no_metal` | texture: minimum roughness (default 0.7), ignore the metallic map |
| `gap` | build without `--raw`: minimum distance from the skin (m) |

Replacing an **existing** item's look (e.g. `clothingHeadT1`) also works: leave out `new_item`. The add-on removes
the item's previous model data and adds yours, so it must load after Visible Clothing (the `VisibleClothing_` name
prefix does that).

---

## C. Your own Unity pipeline: the conventions

If you build bundles yourself, Visible Clothing still works with them when you follow these rules. (They are what
`unity/Assets/Editor/BuildClothing.cs` produces.)

- **Item / XML**: a clothing-slot item with an `SDCS` property class: `Prefab` (`#@modfolder:Resources/<bundle>?<prefab with {sex}>`),
  `TransformName`, `Excludes`, optional `HairMaskType` / `FacialHairMaskType`.
- **Prefab**: root GameObject (the prefab name) with
  - one child per part named like `TransformName` (`head`, `bodyVC`, `handsVC`, `feetVC`) holding the
    `SkinnedMeshRenderer`(s); child objects under it are stitched too (e.g. a mesh with a `Cloth` component);
  - `Origin`: a copy of the vanilla player skeleton in its bind pose (bone names must match the game's rig);
  - optional `GearBoneMap` component (silences "No GearBoneMap" warnings): a script class named `GearBoneMap`
    (global namespace) with `List<PartBones> parts`, `PartBones { string partName; List<Transform> bones; }`.
- **Materials**: name them `VC_<anything>` and put the textures in these Standard-shader slots; at runtime they are
  copied onto the game's `Game/Character` material (a mesh with a `Cloth` component gets `Game/CharacterCloth`):
  - `_MainTex` = albedo (sRGB),
  - `_BumpMap` = normal map (texture type Normal map),
  - `_DetailMask` = RMOE, linear: **R** roughness, **G** metallic, **B** ambient occlusion, **A** emission.
  Model double-sided cloth with real back faces (the shader culls back faces), except `Cloth` meshes (drawn both sides).
- **First person**: in the chest-slot mesh, set vertex colour **r = 1** on vertices that must disappear in first
  person (collar, shoulders); triangles with any such vertex are removed in first person.
- **Hats**: one blend shape per head, named race + 2-digit variant in lower case (`asian01` ... `white04`), each
  moving the hat from your fitted shape (fitted on the White 04 head) by that head's offset from White 04. A shape
  named `white04` must exist (all zeros): it marks the mesh as a fitted hat.
- **Bones**: gloves should only use bones the first-person arms animate: `Arm`, `ForeArm`, `ForeArmRoll1-4`, `Hand`,
  finger joints `1-5`, `Thumb1-3` (no `_sup_*` helpers or palm bones). Hats: no eye / eyelid bones.

## Troubleshooting

- **Clothing shows on top of armor**: the item is not in a clothing slot (`Extends` a clothing item), or Visible
  Clothing is not installed / its DLL failed to load (EAC must be off).
- **Pink / white clothing**: materials not named `VC_*`, or the RMOE texture missing (`_DetailMask`).
- **"Mod reference for a mod that is not loaded"**: route A needs the VisibleClothing mod folder name unchanged.
- **Build says the game is running**: close it (its mod files are locked), then `bash tools/vcpack.sh install <pack>`.
- **Typed `bash` in PowerShell and nothing happened**: that is WSL; use Git Bash.
