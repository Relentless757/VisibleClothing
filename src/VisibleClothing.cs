using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace VisibleClothing
{
    public class VisibleClothingModApi : IModApi
    {
        public void InitMod(Mod _modInstance)
        {
            try
            {
                new Harmony("elisk.visibleclothing").PatchAll(Assembly.GetExecutingAssembly());
                Log.Out("[VisibleClothing] patched SDCSUtils.setupEquipment / Stitch");
            }
            catch (Exception e)
            {
                Log.Error("[VisibleClothing] patching failed, clothing will draw on top of armor: " + e);
            }
        }
    }

    /// <summary>
    /// The clothing items carry SDCS data (Config/items.xml), so vanilla's setupEquipment would draw them
    /// in addition to armor. While it runs, blank out each clothing slot whose matching armor slot is
    /// actually drawn; an empty armor slot, or one set to Hidden in the cosmetic menu, lets clothing show.
    /// </summary>
    [HarmonyPatch]
    public static class SetupEquipmentPatch
    {
        // armor slot k (Head, Chest, Hands, Feet) pairs with clothing slot k + ClothingOffset
        const int ClothingOffset = (int)EquipmentSlots.ClothingHead;
        const int Pairs = 4;

        /// <summary>True while setupEquipment builds a character whose Visible Clothing outfit is drawn.</summary>
        public static bool OutfitDrawn;

        public struct State
        {
            public ItemValue[] Slots;
            public ItemValue[] Saved;
        }

        static MethodBase Target() => AccessTools.Method(typeof(SDCSUtils), "setupEquipment", new[]
        {
            typeof(GameObject), typeof(SDCSUtils.TransformCatalog), typeof(string[]), typeof(EntityAlive),
            typeof(bool), typeof(bool), typeof(bool)
        });

        // skip the patch (clothing then draws on top of armor) instead of failing every character build
        static bool Prepare()
        {
            if (Target() != null)
                return true;
            Log.Error("[VisibleClothing] SDCSUtils.setupEquipment(entity overload) not found - game version changed?");
            return false;
        }

        static MethodBase TargetMethod() => Target();

        static bool ArmorDrawn(Equipment eq, ItemValue[] slots, int k, bool ignoreDlc, bool useTempCosmetics)
        {
            // mirrors the slot test in SDCSUtils.setupEquipment
            ItemClass cosmetic = eq.GetCosmeticSlot(k, useTempCosmetics);
            if (cosmetic == ItemClass.MissingItem)
                return false; // "Hidden"
            bool armor = slots[k]?.ItemClass?.SDCSData != null;
            bool cos = cosmetic != null && (useTempCosmetics || (armor && (ignoreDlc || eq.HasCosmeticUnlocked(cosmetic).isUnlocked)));
            return armor || cos;
        }

        static void Prefix(EntityAlive entity, bool _ignoreDlcEntitlements, bool useTempCosmetics, out State __state)
        {
            __state = default;
            try
            {
                Equipment eq = entity?.equipment;
                if (eq == null)
                    return;
                ItemValue[] slots = eq.GetItems(); // the live array; restored in the finalizer
                if (slots == null || slots.Length < ClothingOffset + Pairs)
                    return;
                int chest = (int)EquipmentSlots.Chest;
                OutfitDrawn = slots[ClothingOffset + chest]?.ItemClass?.SDCSData != null
                              && !ArmorDrawn(eq, slots, chest, _ignoreDlcEntitlements, useTempCosmetics);
                for (int k = 0; k < Pairs; k++)
                {
                    int c = ClothingOffset + k;
                    if (slots[c]?.ItemClass?.SDCSData == null || !ArmorDrawn(eq, slots, k, _ignoreDlcEntitlements, useTempCosmetics))
                        continue;
                    if (__state.Saved == null)
                    {
                        __state.Slots = slots;
                        __state.Saved = new ItemValue[Pairs];
                    }
                    __state.Saved[k] = slots[c];
                    slots[c] = null;
                }
            }
            catch (Exception e)
            {
                Log.Warning("[VisibleClothing] slot check failed: " + e.Message);
            }
        }

        static void Postfix(EntityAlive entity, State __state)
        {
            try
            {
                ApplyHairMask(entity, __state);
            }
            catch (Exception e)
            {
                Log.Warning("[VisibleClothing] hair mask failed: " + e.Message);
            }
        }

        static void ApplyHairMask(EntityAlive entity, State __state)
        {
            // vanilla only takes hair masks from Head armor; a visible clothing hat needs them too
            if (!(entity?.emodel is EModelSDCS emodel))
                return;
            ItemValue[] slots = entity.equipment?.GetItems();
            int c = ClothingOffset + (int)EquipmentSlots.Head;
            if (slots == null || slots.Length <= c || (__state.Saved != null && __state.Saved[0] != null))
                return;
            SDCSUtils.SlotData sd = slots[c]?.ItemClass?.SDCSData;
            if (sd == null)
                return;
            if (sd.HairMaskType > emodel.HairMaskType)
                emodel.HairMaskType = sd.HairMaskType;
            if (sd.FacialHairMaskType > emodel.FacialHairMaskType)
                emodel.FacialHairMaskType = sd.FacialHairMaskType;
        }

        static Exception Finalizer(Exception __exception, State __state)
        {
            OutfitDrawn = false;
            if (__state.Saved != null)
                for (int k = 0; k < Pairs; k++)
                    if (__state.Saved[k] != null)
                        __state.Slots[ClothingOffset + k] = __state.Saved[k];
            return __exception;
        }
    }

    /// <summary>
    /// The bundle's materials are Unity Standard (a fallback that renders anywhere). Before a Visible Clothing part is
    /// stitched, give its materials the game's own character shader by copying a vanilla gear material and plugging
    /// our textures in, so the clothing gets the game's lighting, every graphics API, and vanilla's first-person
    /// clipping (Stitch strips the collar polygons for any material with _ClipFPV).
    /// Our materials are named "VC_*"; the RMOE map (roughness, metallic, occlusion, emission) rides in _DetailMask.
    /// </summary>
    public static class GameShader
    {
        const string TemplatePrefab = "@:Entities/Player/Male/Gear/Nomad/gearMaleNomadPrefab.prefab";
        static Material character, cloth;
        static bool resolved;
        static readonly Dictionary<Material, Material> converted = new Dictionary<Material, Material>();

        static void Resolve()
        {
            if (resolved)
                return;
            resolved = true;
            var go = DataLoader.LoadAsset<GameObject>(TemplatePrefab);
            if (go != null)
                foreach (var r in go.GetComponentsInChildren<Renderer>(true))
                    foreach (var m in r.sharedMaterials)
                    {
                        if (m == null || m.shader == null)
                            continue;
                        if (m.shader.name == "Game/Character" && m.HasProperty("_RMOE") && (character == null || m.name.Contains("Body")))
                            character = m;
                        else if (m.shader.name == "Game/CharacterCloth" && m.HasProperty("_RMOE") && cloth == null)
                            cloth = m;
                    }
            if (character == null)
                Log.Warning("[VisibleClothing] game character shader not found (" + TemplatePrefab + "); clothing keeps the Standard shader");
            else
                Log.Out("[VisibleClothing] using game shader " + character.shader.name + (cloth != null ? " / " + cloth.shader.name : ""));
        }

        public static void Convert(GameObject part)
        {
            if (part == null)
                return;
            foreach (var r in part.GetComponentsInChildren<Renderer>(true))
            {
                Material[] mats = r.sharedMaterials;
                bool changed = false;
                for (int i = 0; i < mats.Length; i++)
                {
                    Material m = mats[i];
                    if (m == null || !m.name.StartsWith("VC_"))
                        continue;
                    if (!converted.TryGetValue(m, out Material g))
                    {
                        Resolve();
                        Material tmpl = r.GetComponent<Cloth>() != null && cloth != null ? cloth : character;
                        if (tmpl == null)
                            return;
                        g = new Material(tmpl) { name = m.name };
                        g.SetTexture("_Albedo", m.GetTexture("_MainTex"));
                        g.SetTexture("_Normal", m.GetTexture("_BumpMap"));
                        g.SetTexture("_RMOE", m.GetTexture("_DetailMask"));
                        if (g.HasProperty("_Cull"))
                            g.SetFloat("_Cull", 2f);   // garments are built double-sided where needed
                        if (g.HasProperty("_EmissiveColor"))
                            g.SetColor("_EmissiveColor", Color.black);
                        converted[m] = g;
                        converted[g] = g;
                    }
                    if (g != m)
                    {
                        mats[i] = g;
                        changed = true;
                    }
                }
                if (changed)
                    r.sharedMaterials = mats;
            }
        }
    }

    [HarmonyPatch(typeof(SDCSUtils), nameof(SDCSUtils.Stitch))]
    public static class StitchPatch
    {
        static void Prefix(GameObject sourceObj)
        {
            try
            {
                GameShader.Convert(sourceObj);
            }
            catch (Exception e)
            {
                Log.Warning("[VisibleClothing] shader swap failed: " + e.Message);
            }
        }

        /// <summary>
        /// Fallback when the shader swap did not happen: vanilla only strips first-person collar polygons for
        /// materials with _ClipFPV, so do it for our Standard-shader outfit (same vertex-colour marking, r = 1).
        /// </summary>
        /// <summary>
        /// Hats carry one blend shape per head variant (see tools/pack_unity.py head_shapes): fitted around the
        /// largest head, the shape of the character's own head pulls the hat in to sit as snug on it.
        /// </summary>
        const string ReferenceHead = "white04";

        static void FitToHead(GameObject part)
        {
            Archetype arch = SDCSUtils.tmpArchetype;
            if (arch == null || part == null)
                return;
            string key = (arch.Race + arch.Variant.ToString("00")).ToLowerInvariant();
            foreach (var smr in part.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                Mesh m = smr.sharedMesh;
                // any hat built for Visible Clothing (this mod or a clothing pack) carries one shape per head,
                // named race + variant ("white04"); the reference head's shape is always there
                if (m == null || m.blendShapeCount == 0 || m.GetBlendShapeIndex(ReferenceHead) < 0)
                    continue;
                int idx = m.GetBlendShapeIndex(key);
                for (int i = 0; i < m.blendShapeCount; i++)
                    smr.SetBlendShapeWeight(i, i == idx ? 100f : 0f);
            }
        }

        static void Postfix(GameObject __result, bool isFPV, bool isUI, bool isGear)
        {
            try
            {
                if (isGear)
                    FitToHead(__result);
            }
            catch (Exception e)
            {
                Log.Warning("[VisibleClothing] head fit failed: " + e.Message);
            }
            try
            {
                if (!isFPV || isUI || !isGear || __result == null || __result.name != "bodyVC")
                    return;
                foreach (var smr in __result.GetComponentsInChildren<SkinnedMeshRenderer>(true))
                    if (!smr.sharedMaterials.Any(m => m != null && m.HasProperty("_ClipFPV")))
                        SDCSUtils.RemoveFPViewObstructingGearPolygons(smr);
            }
            catch (Exception e)
            {
                Log.Warning("[VisibleClothing] first-person clip failed: " + e.Message);
            }
        }
    }

    /// <summary>
    /// Our outfit's pants go over the boots. Vanilla handles that combination with a boot variant (feet_A, usually a
    /// short shaft) picked from GearVariantMatrix for vanilla outfits; for ours, ask for whichever of feet / feet_A
    /// has the shorter shaft.
    /// The pants are fitted to clear every vanilla boot (feet_A where it exists) and our clothing shoes.
    /// </summary>
    [HarmonyPatch]
    public static class BootVariantPatch
    {
        static readonly Dictionary<string, bool> hasShortShaft = new Dictionary<string, bool>();

        static MethodBase Target() => AccessTools.Method(typeof(GearVariants.GearVariantMatrixSO), "GetVariantOrEmpty",
            new[] { typeof(string), typeof(string), typeof(string), typeof(string) });

        static bool Prepare()
        {
            if (Target() != null)
                return true;
            Log.Warning("[VisibleClothing] GearVariantMatrixSO.GetVariantOrEmpty not found; boots keep their tall shafts under our pants");
            return false;
        }

        static MethodBase TargetMethod() => Target();

        static float Top(GameObject prefab, string part)
        {
            Transform t = prefab != null ? SDCSUtils.getClothingPartWithName(prefab, part) : null;
            Mesh m = t != null ? t.GetComponentInChildren<SkinnedMeshRenderer>(true)?.sharedMesh : null;
            return m != null ? m.bounds.max.y : float.MaxValue;
        }

        static void Postfix(string part, string sourceGearPath, ref string __result)
        {
            try
            {
                if (!SetupEquipmentPatch.OutfitDrawn || !string.IsNullOrEmpty(__result) || string.IsNullOrEmpty(sourceGearPath)
                    || !string.Equals(part, "feet", StringComparison.OrdinalIgnoreCase))
                    return;
                if (!hasShortShaft.TryGetValue(sourceGearPath, out bool a))
                {
                    // the "_A" boot is not always the shorter one (female biker: feet_A is the tall shaft)
                    var go = DataLoader.LoadAsset<GameObject>(sourceGearPath);
                    float top = Top(go, "feet"), topA = Top(go, "feet_A");
                    a = topA < top;
                    hasShortShaft[sourceGearPath] = a;
                }
                if (a)
                    __result = "A";
            }
            catch (Exception e)
            {
                Log.Warning("[VisibleClothing] boot variant check failed: " + e.Message);
            }
        }
    }
}
