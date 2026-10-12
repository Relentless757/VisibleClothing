// Builds the Visible Clothing gear prefabs from <root>/Data/*.json and packs them into one AssetBundle.
// Batch:  Unity.exe -batchmode -quit -projectPath <unity> -executeMethod BuildClothing.Build
//         [-vcRoot Assets/VC/Packs/<name>] [-vcBundle <name>.unity3d]      (clothing packs; default: the base mod)
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEngine;

public static class BuildClothing
{
    static string Root = "Assets/VC";
    static string BundleName = "visibleclothing.unity3d";

    static string Arg(string name, string fallback)
    {
        var a = Environment.GetCommandLineArgs();
        int i = Array.IndexOf(a, name);
        return i >= 0 && i + 1 < a.Length ? a[i + 1] : fallback;
    }

    [Serializable] class Sub { public string texture; public int[] tris; }

    [Serializable]
    class MeshData
    {
        public float[] verts, normals, uv, boneW;
        public float[] clip;  // optional: 1 = vertex removed in first person (game reads vertex colour r)
        public string[] shapeNames;   // optional (hats): one blend shape per head variant, e.g. "asian02"
        public float[] shapeDeltas;   // shapeNames.Length * vertexCount * 3
        public int[] boneIdx;
        public Sub[] subs;
    }

    [Serializable]
    class Child : MeshData { public string name; }

    [Serializable]
    class Garment : MeshData
    {
        public string prefab, part, sex;
        public string[] boneNames;
        public Child child;   // optional cloth-simulated piece (drawstrings)
    }

    [Serializable]
    class Skeleton
    {
        public string[] names;
        public int[] parents;
        public float[] pos, rot, scl;
    }

    [MenuItem("Visible Clothing/Build")]
    public static void Build()
    {
        Root = Arg("-vcRoot", "Assets/VC");
        BundleName = Arg("-vcBundle", "visibleclothing.unity3d");
        Directory.CreateDirectory(Root + "/Gen");
        ImportTextures();
        var skel = new Dictionary<string, Skeleton>();
        foreach (var sex in new[] { "male", "female" })
            skel[sex] = JsonUtility.FromJson<Skeleton>(File.ReadAllText($"{Root}/Data/skeleton_{sex}.json"));

        var prefabs = new List<string>();
        foreach (var file in Directory.GetFiles(Root + "/Data", "*.json"))
        {
            string fn = Path.GetFileName(file);
            if (fn.StartsWith("skeleton_") || fn.StartsWith("_"))
                continue;
            var g = JsonUtility.FromJson<Garment>(File.ReadAllText(file));
            prefabs.Add(MakePrefab(g, skel[g.sex.ToLowerInvariant()]));
        }
        AssetDatabase.SaveAssets();

        foreach (var p in prefabs)
            AssetImporter.GetAtPath(p).SetAssetBundleNameAndVariant(BundleName, "");
        var outDir = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "BundleOut"));
        Directory.CreateDirectory(outDir);
        // only this bundle (the project may hold the base mod and several clothing packs)
        var build = new AssetBundleBuild { assetBundleName = BundleName, assetNames = prefabs.ToArray() };
        BuildPipeline.BuildAssetBundles(outDir, new[] { build },
            BuildAssetBundleOptions.ChunkBasedCompression | BuildAssetBundleOptions.StrictMode, BuildTarget.StandaloneWindows64);
        Debug.Log($"[VC] built {prefabs.Count} prefabs -> {outDir}/{BundleName}");
    }

    static void ImportTextures()
    {
        AssetDatabase.Refresh();
        // max size per texture from tools/pack_unity.py (small-on-screen items 1K); no hint: 2048, RMOE 1024
        var sizes = new Dictionary<string, int>();
        var hint = Root + "/Data/_textures.json";
        if (File.Exists(hint))
            foreach (Match m in Regex.Matches(File.ReadAllText(hint), @"""([^""]+)""\s*:\s*(\d+)"))
                sizes[m.Groups[1].Value] = int.Parse(m.Groups[2].Value);
        if (!Directory.Exists(Root + "/Textures"))
            return;
        foreach (var path in Directory.GetFiles(Root + "/Textures", "*.png"))
        {
            var ti = (TextureImporter)AssetImporter.GetAtPath(path.Replace('\\', '/'));
            string fn = Path.GetFileNameWithoutExtension(path);
            bool normal = fn.EndsWith("_n"), rmoe = fn.EndsWith("_rmoe");
            // hats, gloves and socks are small on screen: 1K is plenty; roughness/metal/occlusion is low frequency
            int max = sizes.TryGetValue(fn, out int sz) ? sz : (rmoe ? 1024 : 2048);
            var type = normal ? TextureImporterType.NormalMap : TextureImporterType.Default;
            if (ti.textureType == type && ti.maxTextureSize == max && ti.anisoLevel == 8 && !ti.alphaIsTransparency
                && ti.textureCompression == TextureImporterCompression.CompressedHQ && ti.sRGBTexture == !(normal || rmoe))
                continue;
            ti.textureType = type;
            ti.sRGBTexture = !(normal || rmoe);
            ti.alphaSource = rmoe ? TextureImporterAlphaSource.FromInput : TextureImporterAlphaSource.None;
            ti.alphaIsTransparency = false;
            ti.mipmapEnabled = true;
            ti.anisoLevel = 8;                       // fabric seen at grazing angles stays sharp
            ti.maxTextureSize = max;
            ti.textureCompression = TextureImporterCompression.CompressedHQ;
            ti.SaveAndReimport();
        }
    }

    /// <summary>
    /// Unity Standard material named "VC_*". It is only the fallback: at runtime the mod DLL copies a vanilla
    /// Game/Character (or Game/CharacterCloth) material and plugs these textures in (_MainTex -> _Albedo,
    /// _BumpMap -> _Normal, _DetailMask -> _RMOE). _DetailMask is unused by Standard without detail maps.
    /// </summary>
    static Material GetMaterial(string texName, string variant = "")
    {
        var path = $"{Root}/Gen/VC_{texName}{variant}.mat";
        var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (mat == null)
        {
            mat = new Material(Shader.Find("Standard"));
            AssetDatabase.CreateAsset(mat, path);
        }
        mat.SetTexture("_MainTex", AssetDatabase.LoadAssetAtPath<Texture2D>($"{Root}/Textures/{texName}.png"));
        var nrm = AssetDatabase.LoadAssetAtPath<Texture2D>($"{Root}/Textures/{texName}_n.png");
        mat.SetTexture("_BumpMap", nrm);
        mat.SetFloat("_BumpScale", 1f);
        if (nrm) mat.EnableKeyword("_NORMALMAP"); else mat.DisableKeyword("_NORMALMAP");
        mat.SetTexture("_DetailMask", AssetDatabase.LoadAssetAtPath<Texture2D>($"{Root}/Textures/{texName}_rmoe.png"));
        mat.SetTexture("_MetallicGlossMap", null);
        mat.DisableKeyword("_METALLICGLOSSMAP");
        // opaque: the garment geometry itself carries the shape (holes, straps, cuffs)
        mat.SetFloat("_Mode", 0f);
        mat.SetOverrideTag("RenderType", "Opaque");
        mat.DisableKeyword("_ALPHATEST_ON");
        mat.renderQueue = -1;
        mat.SetFloat("_Glossiness", 0.2f);
        mat.SetFloat("_Metallic", 0f);
        EditorUtility.SetDirty(mat);
        return mat;
    }

    static SkinnedMeshRenderer AddSkinned(GameObject go, MeshData g, string meshName, Transform[] smrBones, Transform rootBone,
        string matVariant = "")
    {
        int n = g.verts.Length / 3;
        var mesh = new Mesh { name = meshName };
        if (n > 65000) mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
        var v = new Vector3[n]; var nr = new Vector3[n]; var uv = new Vector2[n]; var bw = new BoneWeight[n];
        for (int i = 0; i < n; i++)
        {
            v[i] = new Vector3(g.verts[i * 3], g.verts[i * 3 + 1], g.verts[i * 3 + 2]);
            nr[i] = new Vector3(g.normals[i * 3], g.normals[i * 3 + 1], g.normals[i * 3 + 2]);
            uv[i] = new Vector2(g.uv[i * 2], g.uv[i * 2 + 1]);
            int o = i * 4;
            bw[i] = new BoneWeight
            {
                boneIndex0 = g.boneIdx[o], weight0 = g.boneW[o],
                boneIndex1 = g.boneIdx[o + 1], weight1 = g.boneW[o + 1],
                boneIndex2 = g.boneIdx[o + 2], weight2 = g.boneW[o + 2],
                boneIndex3 = g.boneIdx[o + 3], weight3 = g.boneW[o + 3],
            };
        }
        mesh.vertices = v; mesh.normals = nr; mesh.uv = uv; mesh.boneWeights = bw;
        if (g.clip != null && g.clip.Length == n)
            mesh.colors = g.clip.Select(c => new Color(c, 0f, 0f, 1f)).ToArray();
        mesh.subMeshCount = g.subs.Length;
        for (int i = 0; i < g.subs.Length; i++) mesh.SetTriangles(g.subs[i].tris, i);
        mesh.RecalculateTangents();
        mesh.RecalculateBounds();
        if (g.shapeNames != null && g.shapeDeltas != null && g.shapeDeltas.Length == g.shapeNames.Length * n * 3)
            for (int s = 0; s < g.shapeNames.Length; s++)
            {
                var dv = new Vector3[n];
                for (int i = 0; i < n; i++)
                {
                    int o = (s * n + i) * 3;
                    dv[i] = new Vector3(g.shapeDeltas[o], g.shapeDeltas[o + 1], g.shapeDeltas[o + 2]);
                }
                mesh.AddBlendShapeFrame(g.shapeNames[s], 100f, dv, null, null);
            }
        // bind pose = current pose of the freshly built skeleton (it is the vanilla bind pose)
        mesh.bindposes = smrBones.Select(b => b.worldToLocalMatrix * go.transform.localToWorldMatrix).ToArray();
        AssetDatabase.CreateAsset(mesh, $"{Root}/Gen/{meshName}.asset");

        var smr = go.AddComponent<SkinnedMeshRenderer>();
        smr.sharedMesh = mesh;
        smr.bones = smrBones;
        smr.rootBone = rootBone;
        smr.sharedMaterials = g.subs.Select(x => GetMaterial(x.texture, matVariant)).ToArray();
        smr.updateWhenOffscreen = true;
        return smr;
    }

    /// <summary>Drawstrings: pinned where they leave the waistband, free to swing toward the tips.</summary>
    static void AddCloth(GameObject go, Mesh mesh)
    {
        var cloth = go.AddComponent<Cloth>();
        cloth.stretchingStiffness = 0.95f;
        cloth.bendingStiffness = 0.25f;
        cloth.damping = 0.25f;
        cloth.useGravity = true;
        cloth.friction = 0.5f;
        cloth.worldVelocityScale = 0.6f;
        cloth.worldAccelerationScale = 0.9f;
        cloth.useTethers = true;
        cloth.sleepThreshold = 0.001f;

        // cloth particles = mesh vertices welded by position, in first-seen order
        var uniq = new List<Vector3>();
        var seen = new Dictionary<Vector3, int>();
        foreach (var p in mesh.vertices)
            if (!seen.ContainsKey(p)) { seen[p] = uniq.Count; uniq.Add(p); }
        var co = cloth.coefficients;
        var pos = cloth.vertices != null && cloth.vertices.Length == co.Length ? cloth.vertices : uniq.ToArray();
        if (pos.Length != co.Length)
            Debug.LogWarning($"[VC] cloth {go.name}: {co.Length} coefficients vs {pos.Length} positions; mapping by index");
        float top = pos.Max(p => p.y);
        for (int i = 0; i < co.Length; i++)
        {
            float y = i < pos.Length ? pos[i].y : top;
            float t = Mathf.Clamp01((top - y - 0.012f) / 0.10f);   // first ~1 cm under the knot stays put
            co[i].maxDistance = t * t * 0.07f;
            co[i].collisionSphereDistance = 0.005f;
        }
        cloth.coefficients = co;
        Debug.Log($"[VC] cloth {go.name}: {co.Length} particles, {co.Count(c => c.maxDistance == 0)} pinned");
    }

    static string MakePrefab(Garment g, Skeleton s)
    {
        var root = new GameObject(g.prefab);
        // skeleton: Origin and below, in the vanilla bind pose
        var bones = new Transform[s.names.Length];
        for (int i = 0; i < s.names.Length; i++)
        {
            var t = new GameObject(s.names[i]).transform;
            t.SetParent(s.parents[i] < 0 ? root.transform : bones[s.parents[i]], false);
            t.localPosition = new Vector3(s.pos[i * 3], s.pos[i * 3 + 1], s.pos[i * 3 + 2]);
            t.localRotation = new Quaternion(s.rot[i * 4], s.rot[i * 4 + 1], s.rot[i * 4 + 2], s.rot[i * 4 + 3]);
            t.localScale = new Vector3(s.scl[i * 3], s.scl[i * 3 + 1], s.scl[i * 3 + 2]);
            bones[i] = t;
        }
        var byName = new Dictionary<string, Transform>();
        foreach (var b in bones) byName[b.name] = b;

        var partGo = new GameObject(g.part);
        partGo.transform.SetParent(root.transform, false);
        partGo.transform.SetSiblingIndex(0);
        var smrBones = g.boneNames.Select(b =>
        {
            if (!byName.TryGetValue(b, out var t)) throw new Exception($"{g.prefab}: bone {b} not in skeleton");
            return t;
        }).ToArray();
        AddSkinned(partGo, g, g.prefab, smrBones, byName["Hips"]);

        // GearBoneMap: the game's own component (the stub in Assets/Scripts resolves to Assembly-CSharp's class at
        // runtime). Lists the bones this part is skinned to, which silences "No GearBoneMap found" and is what
        // SDCSUtils.CollectRequiredNamesForSlot reads.
        var map = root.AddComponent<GearBoneMap>();
        map.parts.Add(new GearBoneMap.PartBones { partName = g.part, bones = smrBones.Concat(new[] { byName["Hips"] }).Distinct().ToList() });

        if (g.child != null && g.child.verts != null && g.child.verts.Length > 0)
        {
            // Stitch() instantiates the part with its children and remaps every child SMR's bones, and wires
            // any Cloth it finds to the rig's capsule colliders, the same way vanilla gear cloth works.
            var cg = new GameObject(g.part + "_" + g.child.name);
            cg.transform.SetParent(partGo.transform, false);
            var csmr = AddSkinned(cg, g.child, g.prefab + "_" + g.child.name, smrBones, byName["Hips"], "_cloth");
            AddCloth(cg, csmr.sharedMesh);
        }

        var path = $"{Root}/Gen/{g.prefab}.prefab";
        PrefabUtility.SaveAsPrefabAsset(root, path);
        UnityEngine.Object.DestroyImmediate(root);
        return path;
    }
}
