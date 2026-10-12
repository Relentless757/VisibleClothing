# Visible Clothing (7 Days to Die V3.2)

Gives the 12 V3.2 clothing items real 3D models. A piece is drawn whenever the matching armor slot is empty, or that
armor piece is set to **Hidden** in the cosmetics menu.

| Slot  | Tattered (T1)          | Patchwork (T2)           | ThermaCore (T3)              |
|-------|------------------------|--------------------------|------------------------------|
| Head  | Cap Liner (beanie)     | Cap Liner (beanie)       | Cap Liner (balaclava)        |
| Body  | Undergarments + pants  | Long Underwear + pants   | Combat Layer + pants         |
| Hands | Glove Liners (fingerless) | Glove Liners          | Glove Liners                 |
| Feet  | Socks                  | Socks                    | Socks                        |

- Male and female versions; hats morph onto each of the 16 faces per sex.
- Uses the game's own character shader; first-person collar clipping like vanilla; full gloves hide the hand.
- Pants go over vanilla boots (the game's short-shaft boot variant is used); T1 drawstrings use cloth physics.

**Download:** see the Nexus Mods page (release zip). **Requirements:** EAC off (contains a DLL). In multiplayer,
install on the server and every client.

## How it works

- `src/VisibleClothing.cs` (Harmony):
  - `SDCSUtils.setupEquipment`: hides a clothing piece while the matching armor is drawn.
  - `SDCSUtils.Stitch`: swaps the bundle's fallback materials for a copy of a vanilla `Game/Character` material,
    sets the hat's per-head blend shape (`tmpArchetype` race + variant), first-person clip fallback.
  - `GearVariantMatrixSO.GetVariantOrEmpty`: asks for the shorter-shaft boot while our outfit is drawn.
- `Mod/VisibleClothing/Config/items.xml`: SDCS data for the 12 clothing items (`Excludes=hands` on full gloves).

## Building from source

Nothing derived from the game is in this repository; the tools read **your own** install.

Requirements: Blender 5.x, Unity 2022.3.62f2, .NET SDK, Python 3 with `numpy`, `scipy`, `Pillow`, `UnityPy`, and
the source 3D models (`7D2D Clothing models/<Item>.fbx` + `.fbm` textures, not included).

1. Extract the vanilla body, heads and boots into `_work/` (`tools/extract_body.py`, `tools/head_envelope.py`,
   `tools/dump_boots.py`).
2. Fit every garment: `bash _work/refit_all.sh`, or per item
   `blender -b --factory-startup -P tools/geo_garment.py -- ClothingOutfitT2`.
   Hand-fitting: `tools/make_fitting_blend.py` writes `fitting/VisibleClothing_Fitting.blend`; edit it, then
   `bash tools/rebuild_from_fitting.sh [Item ...] [--raw] [--install]` (Git Bash, game closed). See `fitting/README.md`.
3. `python tools/prep_textures.py`, `python tools/pack_unity.py`, then the Unity batch build
   (`-executeMethod BuildClothing.Build`, see `tools/rebuild_from_fitting.sh`).
4. `dotnet build -c Release` in `src/` (references the game's managed DLLs and 0Harmony).

Checks: `tools/pose_test.py` (posed renders), `tools/layer_check.py`, `tools/boot_check.py`, `tools/weights_check.py`.
`MODLOG.md` is the development journal.

## Credits

By Elisk. 3D models generated with Tripo AI and hand-fitted in Blender; the fitting pipeline, code and packaging
were built with AI assistance (Claude). 7 Days to Die is by The Fun Pimps; no game files are included.

## License

MIT, see [LICENSE](LICENSE). Covers the code and tools in this repository. 7 Days to Die and its assets belong to
The Fun Pimps and are not covered.
