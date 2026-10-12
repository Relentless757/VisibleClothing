# Visible Clothing — MODLOG

Goal: render the 3.2 clothing items (clothingHead/Outfit/Hands/Feet T1–T3) on the player when the matching
armor slot is empty, or the armor piece is set to Hidden in the cosmetic menu. Done = works in game (TP, FP,
character-screen preview), both sexes.

## Environment (measured 2026-10-10)
- Game: `F:\SteamLibrary\steamapps\common\7 Days To Die`, V 3.2 (b10) — Constants: Major 3, **Minor 20**, Build 10; Steam buildid 24994517
- Unity 2022.3.62f2 (UnityPlayer.dll 2022.3.62.7762112); editor 2022.3.62f2 installed at `C:\Program Files\Unity\Hub\Editor\2022.3.62f2`
- Decompile (current): `<Game>\_research\decomp_3.2\vanilla`
- Blender: `F:\Game Related Programs\Creation Stuff\Blender Foundation\blender.exe`; UnityPy 1.25.2
- Mods folder is the game's own `Mods\`; HotReload + DevLink installed. EAC must be off for DLL mods.

## Source models (`7D2D Clothing models/`)
Tripo AI static meshes, 1 m normalized box, Z-up, no armature/weights, one 4K basecolor each.
- Feet T1 ankle socks (pair), T2 white tube socks (pair), T3 tactical tall socks (pair)
- Hands T1 fingerless wrap, T2 red knit glove, T3 tactical glove — **left hand only** → mirror for right
- Head T1 grey beanie, T2 red beanie, T3 balaclava
- Outfit T1 tank top, T2 patched henley (long sleeve), T3 tactical long-sleeve shirt
- HandsT1 uses texture folder `dog+plush+3d+model.fbm`, OutfitT1 `tank+top...`, FeetT1 `old+shoes...` (Tripo names)

## How the game does it (ground truth)
- `EquipmentSlots`: Head0 Chest1 Hands2 Feet3, BiomeBadge4-7, **ClothingHead8 ClothingChest9 ClothingHands10 ClothingFeet11**
- Vanilla clothing items (`items.xml` ~18394 `clothingMaster`) have **no `SDCS` class** → never rendered.
- `SDCSUtils.setupEquipment(GameObject, TransformCatalog, string[], EntityAlive, bool isUI, bool ignoreDlc, bool useTempCosmetics)`
  loops all 12 slots: renders slot j if `slotItem.ItemClass.SDCSData != null` (or cosmetic), and **skips when
  `CosmeticSlots[j] == ItemClass.MissingItem`** (= "Hidden" in cosmetic menu). Empty/hidden → base body shows.
- HairMask only set for `ItemClassArmor{EquipSlot: Head}` → clothing hats need it set by our patch.
- FP rig ignores parts containing head/helmet/feet/boots; FP part named `body*` gets `_ClipFPV` polygon removal.
- Gear prefab layout: root (Animator, RigBuilder, GearBoneMap) → children `body`/`hands`/`feet`/`head` SMRs +
  `Origin` skeleton. Stitch() maps SMR bones by **name** to the player rig. GearBoneMap optional (fallback warns).
- Mod prefab path syntax: `#@modfolder:Resources/X.unity3d?gear*Name` — `*` → Male/Female.
- Rebuild trigger: `Equipment.Apply` / `XUiM_PlayerEquipment.HandleRefreshEquipment` → `EModelSDCS.UpdateEquipment`.
- Vanilla player assets: `<Game>\Data\Addressables\Standalone\player_assets_entities\player\{male,female}\common.bundle`
  (playerMale.fbx / playerFemale.fbx) — read locally for fitting only, never shipped.

## Route
XML + Harmony DLL + one AssetBundle.
1. XML: add `<property class="SDCS">` to the 12 clothing items → our bundle prefabs.
2. Harmony on `SDCSUtils.setupEquipment` (entity overload): prefix hides clothing slot 8+k when armor slot k is
   visibly rendered (restore in finalizer); postfix applies the hat's HairMaskType.
3. Assets: fit each static mesh onto vanilla male+female bodies in Blender, transfer skin weights from body,
   mirror glove for right hand, build prefabs + bundle in Unity 2022.3.62f2 (built from raw data by editor script).

## Asset pipeline (real Tripo geometry — user's choice 2026-10-10)
Run per item: `blender -b --factory-startup -P tools/geo_garment.py -- <Item>` → `_work/out/<Item>_{male,female}.json`
+ `<Item>.png` (original texture, 2048). Then `python tools/pack_unity.py` → Unity
`-executeMethod BuildClothing.Build` → copy `unity/BundleOut/visibleclothing.unity3d` to `Mod/VisibleClothing/Resources/`.
Previews: `bash tools/pv.sh <name> <Items...>` → `_work/<name>.png`. Hand coverage check: `_work/cov.py`.
- `tools/extract_body.py`: vanilla body/head mesh + skeleton + weights → `_work/*.json` (local only).
- Unity↔Blender: blender (x,y,z) = unity (x,z,y); triangle winding must be flipped both ways (measured: without the
  flip, normals point inward).
- Align per kind (`tools/fit.py` CFG = landmarks): shirts = torso box fit + each sleeve rebuilt from the raw mesh
  (shoulder→cuff onto arm bone, length + girth matched), sleeve/torso split by armhole line + below-armpit mesh
  connectivity (T3: side-seam line, sleeves fused to torso). Hats: opening = largest convex-hull face, stood upright,
  12° tilt, box fit to skull. Socks: islands, toe→+Y, heel/length fit. Gloves: raw frame fingers +Y, thumb +X,
  back +Z (!! top-down camera has image-up = -Y), knuckle-centre/thickness from hand mesh, per-finger re-pose.
- Conform: push out of whole body (gap), pull in toward own region (loose), smoothed; reverse "unclip" pass for
  skin poking through (only where a ray along the skin normal meets the garment; hats ignore skin below 1.75 m).
- Weights: nearest point on the garment's own body region, barycentric, smoothed, top-4.
- Female: body/feet/head topology == male → male fit + (female − male) body offset at each anchor, re-conformed.
  Hands topology differs → refit from scratch.
- pack_unity duplicates faces inward (Tripo shells are open, double-sided look).

## Log
- 2026-10-10 recon done, route chosen.
- 2026-10-10 first approach (texture baked onto inflated body copy) built; user asked for real models instead.
- 2026-10-11 all 12 items fitted with real geometry, both sexes; bundle 24 prefabs / 79 MB. Not yet tested in game.
- 2026-10-11 in-game test (user): clothing shows. Hat visible in FP -> part renamed `head` (vanilla only skips
  FP head gear when PartName == "head"; `GetPathForSlotData` checks the *static* empty ignoredParts, not the FP
  list). Gloves/sleeves too bulky in FP -> gloves loose 8 mm, sleeves 15 mm, no glove thickening. Reinstalled.
- 2026-10-11 hand-fitting workflow: `tools/make_fitting_blend.py` -> fitting/VisibleClothing_Fitting.blend
  (faces -Y), `tools/rebuild_from_fitting.sh [items] [--raw] [--install]`. Round trip verified.
- 2026-10-11 user feedback round 2: shirts hem -> waist (Hips+0.03), no chest allowance, loose 2 cm / arms 1.2 cm;
  gloves loose 4 mm, no thickening (T3 tactical: 1 cm, padded); head items refit per sex, except T3 balaclava
  (male fit carried to female) with `clear_face`: lower mask front moved forward as one piece to clear nose/lips,
  face excluded from unclip. Rebuilt + reinstalled, fitting .blend regenerated (old copy in _work/).
- 2026-10-11 pants (user Tripo models from my GPT-image prompts): kind 'pants' (waist Hips+0.05, hem at ankle, hip-width fit, per-leg centre-line slide below crotch); merged into ClothingOutfitT# prefabs at pack time (2 submeshes). Bundle 100 MB. Installed; fitting .blend regenerated with pants.
- 2026-10-11 round 3: hats/gloves/socks textures 1K (bundle 100 -> 67 MB). Armpit web on T2/T3 fixed: `_tight`
  zone (sleeve/torso blend + within pit_radius of the body armpit) conformed to 6 mm. T1 pants drawstrings:
  separate islands kept unconformed (`_free`), exported as part "strings" -> child SMR `bodyVC_strings` with a Unity
  Cloth (coefficients by height: pinned under the knot, up to 7 cm swing). Stitch() remaps child SMR bones and wires
  Cloth capsule colliders itself; FP view disables cloth. Bundle verified: 2 Cloth, 15 textures. Installed.
- 2026-10-11 round 4 (in-game feedback): beanie T1 black patches = inner fold layer pushed through outer -> spread() makes stacked layers share the largest push (conform + unclip). Shirt cuffs end cuff_back=3.5 cm before the wrist. Pants collide with feet too, hem +1 cm. All 15 refit, rebuilt, installed. Vanilla gear materials: _Albedo2 + _Normal2 + _RMOT (custom shader); ours: albedo only (Tripo, baked lighting).
- 2026-10-11 drawstrings flickered black in game: the inward face copy (double-siding) gets welded by Cloth and recomputed normals cancel -> cloth parts are no longer doubled (strings are closed tubes).
- 2026-10-11 PBR re-export from Tripo (user cut real holes). Exports arrived as tripo_convert_<id>.fbx/.fbm; mapped by the
  item-named files inside each .fbm and renamed (log: models/references/RENAMED_FROM_TRIPO.txt). Geometry unchanged for 11
  items; changed: FeetT1 (holes + a 1650-vert inner piece -> socks now split by side, not 2 biggest islands), OutfitT3,
  PantsT1, HandsT3 (new upright pose -> tools/frames/ClothingHandsT3.json PCA rotation into the flat glove frame +
  new landmarks). tools/prep_textures.py: albedo / _n normal / _ms (R metal, A smoothness=1-rough, rough floored 0.55;
  metallic maps with mean > 0.25 are bogus for cloth -> zeroed: HeadT1, OutfitT1-3). Standard shader now
  _NORMALMAP + _METALLICGLOSSMAP, aniso 8. Bundle 102 MB (45 textures). Installed.
- 2026-10-11 round 5 (in-game screenshots): (1) shoulder gaps on T2/T3 = torso fabric anchored to torso-only skin ->
  weight anchors now whole-body nearest except arm-region verts (sleeves/gloves). (2) glove fist ballooning/loops ->
  per-finger membership from repose: finger verts weighted from *their own* finger's skin (nearest_bones), palm/cuff
  only non-finger bones, blend zone unfiltered, smooth=1. (3) nose through balaclava on other faces -> head envelope
  over all 16 heads/sex (tools/head_envelope.py, up to 22 mm) used for all hat fitting. (4) FP shirt obstructing view ->
  vertex colour r=1 within 17 cm of / above the neck + Harmony postfix on SDCSUtils.Stitch calling the game's
  RemoveFPViewObstructingGearPolygons (vanilla only does it for _ClipFPV materials). (5) "No GearBoneMap" -> stub
  unity/Assets/Scripts/GearBoneMap.cs (resolves to Assembly-CSharp class), filled per prefab. Verified with
  tools/pose_test.py (LBS posing: aim/arms_up/fist/head_turn; VC_HEAD=<variant json>).
- 2026-10-11 critique (max-effort subagent; evidence previews/critique_evidence.png). Harmony/Stitch/GearBoneMap verified correct.
  Open issues, by priority: (1) unity project is Gamma + D3D-only -> Standard shader too shiny/bright, magenta on Vulkan/GL;
  switch to Linear + add Vulkan/GLCore, or use game shader Game/CharacterPlayerOutfit. (2) head mesh pokes through shirt
  collars (outfits conform vs body only) -> add head_env to collision. (3) from_fitting_blend.py still uses old weighting.
  (4) T1 glove has no finger landmarks -> 47% verts on Hand only; finger_bone() counts Hand*0/_00_palm as finger.
  (5) no layering: shirt hem vs pants, balaclava vs shirt, pants vs vanilla boots. (6) whole-body anchors: hems follow
  thighs, torso follows arms, pants cross-leg weights. (7) patches should degrade (Prepare/try-catch) on game update.
  (8) live slot array mutation visible to net writer thread. (9) FP stripped mesh copies leak (~6 MB each).
- 2026-10-11 round 6 (critique items 1-6). Installed: DLL f7b8f7d9, bundle 1c8cefd5.
  1 shader: DLL StitchPatch prefix copies vanilla nomad Game/Character (cloth: Game/CharacterCloth) material for every
    "VC_*" material, plugging in _Albedo (_MainTex), _Normal (_BumpMap), _RMOE (_DetailMask). RMOE = R rough, G metal,
    B AO 1, A emission 0 (tools/prep_textures.py; roughness floor 0.5). Vanilla Stitch then does FP clipping itself
    (_ClipFPV); our postfix only runs if a material lacks _ClipFPV. Unity project Linear + DX11/DX12/Vulkan/GLCore
    (ProjectSettings.asset.bak_gamma = old). Patches got Prepare() + try/catch.
  2 collars: shirts collide with head_env (all 16 heads). tools/layer_check.py (ray test) -> 0 head verts through.
  3 shared stage: geo_garment.finish()/garment_weights() used by geo_garment main AND from_fitting_blend (layer order
    Feet,Hands,Pants,Outfit,Head; VC_FIT_OUT=dir for dry runs).
  4 gloves: finger membership from skin when no repose (T1); Hand*0/_00_palm/Thumb1 = palm (base) bones. 0% verts
    bound only to Hand (was 47% on T1).
  5 layering: fit.py over=[...] (collide: T1/T2 shirts over their pants), under=[...] (pull_under ray test: T3 shirt
    tucked under T3 pants, balaclava under all shirts). Pants unclip against every vanilla boot (_work/vanilla_boots_*,
    tools/dump_boots.py; shorter of feet/feet_A) + our shoes; DLL BootVariantPatch asks GearVariantMatrixSO for feet_A
    when our outfit is drawn and feet_A is the shorter shaft (female biker: feet_A is the TALL one). tools/boot_check.py.
  6 weights: shirts drop leg bones; torso anchors torso-only except shoulder cap + 8 cm armpit (whole body); pants drop
    other-leg bones below hips (residual only on centre seam); spatial weight smoothing 1.5 cm across panel seams.
  T2 shirt = 86 panels: re-posed sleeves opened a hole at the front armhole. close_seams() + seam_lining() (body strip
    2.5 mm under inter-panel seams, own JSON part "lining", skipped by make_fitting_blend). join_seams() exists but
    breaks sleeve membership (1517 hole rays) - don't use. pose_test: stride/crouch poses, VC_GREEN / VC_NOBODY.
- 2026-10-11 T2 beanie shiny in game (Tripo roughness map ~0.5 + metal speckles). prep_textures OVERRIDE: knit hats
  rough >= 0.85, no metal; global roughness floor 0.7. Bundle 1ca29545 installed. fitting/README updated (layering).
- 2026-10-11 from_fitting_blend: welds UV-seam splits of raw imports (female transfer maps back via widx); with two objects for one item the visible one wins.
- 2026-10-11 hand-fit gloves: unclip reach 8 mm (3 cm stretched the T1 thumb hole into a fin). PowerShell 'bash' = WSL (no /f paths): rebuild silently did nothing -> run from Git Bash, or tools/rebuild_from_fitting.cmd. Python text-mode edits on Windows turn .sh into CRLF: write with newline='\n'.
- 2026-10-11 hand-fit gloves now keep the modelled shape: only verts inside the skin step out (0.6 mm, no smoothing, no unclip). T1 user glove: median move 0 mm, 99% 5 mm (was 1.8 / 14 mm). Installed.
- 2026-10-11 FP gloves deformed (T2 thumb base dragged): FP rig/animations only drive main bones (vanilla FP_ARM uses no _sup_/palm bones); wrist helpers hang off ForeArmRoll4. geo_garment.fp_safe_weights(): gloves -> FP-safe bones only (helpers/palm -> nearest FP-safe ancestor, wrist helpers 50/50 Hand+ForeArmRoll4); other garments: wrist helpers only. Rebuilt T1 (fit), T2 (fit --raw), T3 + outfits (auto). Installed.
- 2026-10-11 T2/T3 gloves: SDCS Excludes=hands (XML 'Excludes' -> SlotData.BaseToTurnOff; vanilla gloves do the same; T2 closed shell, T3 two 5 mm holes). Gloves: fist_clearance() after weights (LBS fist; skin rays start 4 mm under skin, only fabric within 2 cm at rest; push away from hand, 5 passes). Installed.
- 2026-10-11 T1 drawstrings still flickered: they are flat closed tubes; Cloth moves both sides independently. pack_unity.single_sheet(): keep only forward-facing faces (236/450); Game/CharacterCloth is Cull Off (checked shader state) so the sheet shows both sides. Installed.
- 2026-10-11 T3 balaclava tightened: loose 8 mm, gap 3 mm, wide/deep 1.0, face_clear 4 mm, rigid mask move capped at 8 mm (was 24 mm: biggest nose of 16 faces), face unclip re-enabled with 15 mm reach (unclip_reach in CFG). Pokes 147/22.5k male verts (16 heads). Skull gap ~12-15 mm over the default head is mostly the 16-head envelope (~7 mm) + ears.
- 2026-10-11 per-head hat fit: pack_unity.head_shapes() adds one blend shape per head variant (16/sex; delta = head - envelope at 6 nearest head verts, faded 2-4.5 cm from the head) to every hat; DLL StitchPatch.FitToHead sets weight 100 on (tmpArchetype.Race+Variant:00).ToLower(), e.g. white01. Male T3: skull gap 13-21 mm -> ~11 mm on every head. Installed.
- 2026-10-11 hats now fitted + morphed relative to a REAL head, vc_blender.REF_HEAD = white04 (load_body(sex, head='ref') for kind head; shirts keep the envelope). Fitting file shows White 04 (old envelope head kept hidden as '<sex>_head (all 16 faces combined)'); backup fitting/VisibleClothing_Fitting.before_white04.blend. White 04 blend shape = 0, so a White 04 character shows the hat exactly as in Blender. Rebuilt T1-T3 hats from fitting; built, install pending (game running).
- 2026-10-11 T3 hand-fit tightened on rebuild: fit.py handfit_loose=6 mm (from_fitting conforms 4 passes), but the face front (in front of the ears, blended over 4 cm) keeps the hand-fitted mask; neck_gap 3 mm; close_seams now also for hats (mask/neck seam opened at the throat).
- 2026-10-11 T3 mask edge covered the left eye in game: weighted to LeftEyelidBot (animated blinks). fp_safe_weights(): hats fold facial bones (eyes/eyelids) into Head; keep Head/Neck/Jaw.
- 2026-10-11 the in-game T3 mismatch was MY non-raw rebuild (handfit tightening + hat seam closing snapped the mask's top edge to the hood opening). Removed handfit_loose from T3 and close_seams for hats; user builds hats with --raw; rebuilt T1-T3 --raw (eyelid weight fix kept: raw path uses garment_weights too). Installed.
- 2026-10-11 RELEASE 1.0.0: zip My Mods/Nexus Upload Safe/VisibleClothing_v1.0.0.zip (um publish check PASS vs Data + 7DaysToDie_Data); Nexus BBCode release/VisibleClothing_v1.0.0_Nexus.bbcode; public repo https://github.com/Relentless757/VisibleClothing (source/tools/docs only; .gitignore excludes _work, fitting blends+textures, unity/Assets/VC, models, binaries).
- 2026-10-11 1.1.0 FRAMEWORK: clothing packs = add-on mods (XML + bundle, no DLL) built by the same pipeline.
  tools/vc_pack.py (VC_PACK=<pack folder>, pack.json drives items/kinds/paths; no VC_PACK = base mod, output verified
  identical), tools/vcpack.sh new|fitting|build|install, tools/make_mod.py (ModInfo, items.xml new/replace, Localization),
  BuildClothing.cs -vcRoot/-vcBundle, tools/extract_game_data.sh (one-time _work/ setup from the user's own game,
  reproduces 40 files identically). DLL FitToHead: any mesh with a 'white04' blend shape is a fitted hat (was base
  bundle only). docs/MAKING_CLOTHING.md (routes A XML / B pack tools / C conventions), examples/XmlOnlyExample,
  examples/ExamplePack (built end to end; models/build/dist gitignored). NOT tested in game: XML example, example pack.
  Zip My Mods/Nexus Upload Safe/VisibleClothing_v1.1.0.zip (publish check PASS vs Data + 7DaysToDie_Data), BBCode
  release/VisibleClothing_v1.1.0_Nexus.bbcode. DLL + ModInfo installed (1.0.0 copies in _work/backup_installed_1.0.0).
- 2026-10-11 T2/T3 shirt sleeves clipped through the gloves (sleeve end reaches 2-4 cm past the wrist, partly inside
  the glove). geo_garment.push_over() (mirror of pull_under: ray along each outward shirt vert normal, outermost glove
  surface within 1.5 cm, push to 2.5 mm outside, capped 15 mm/pass, 5 passes, spread+smoothed) against all 3 gloves
  (+ pack gloves), run last in finish() (CFG over_gloves=False to skip). Female fit starts from the male shape BEFORE
  the push (c["_before_over"]) so nothing else changes: verified only verts within 6 cm of the wrist moved. Outfits are
  built by geo_garment.py (auto fit), NOT from_fitting_blend (that gives different T2/T3 outfits). Using unclip() with
  glove points (like boots) ran away (cuff moved 8-13 cm). tools/glove_check.py: male T2 sleeve verts under gloves
  178/39/212 -> 8/5/8. Bundle installed; 1.1.0 zip rebuilt.
