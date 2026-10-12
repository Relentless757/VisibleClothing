// Stub of 7 Days to Die's GearBoneMap (Assembly-CSharp). Only the serialized layout matters: prefabs built here
// reference "Assembly-CSharp / GearBoneMap", which the game resolves to its real class when the bundle loads.
using System;
using System.Collections.Generic;
using UnityEngine;

[DisallowMultipleComponent]
public class GearBoneMap : MonoBehaviour
{
    [Serializable]
    public class PartBones
    {
        public string partName;
        public List<Transform> bones = new List<Transform>();
    }

    public List<PartBones> parts = new List<PartBones>();
}
