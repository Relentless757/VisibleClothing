#!/bin/bash
# Rebuild the mod from fitting/VisibleClothing_Fitting.blend.
#   bash tools/rebuild_from_fitting.sh [Item ...] [--raw] [--install]
#   bash tools/rebuild_from_fitting.sh --install-only      (copy the last build into the game; game must be closed)
#   no items = all 12; --raw = no automatic clipping clean-up; --install = also copy into the game's Mods folder
cd "$(dirname "$0")/.."
if grep -qi microsoft /proc/version 2>/dev/null; then   # "bash" typed in PowerShell is WSL: no Windows paths there
  echo "!! This is WSL bash. From PowerShell run:  tools\rebuild_from_fitting.cmd $*"; exit 1
fi
BL="/f/Game Related Programs/Creation Stuff/Blender Foundation/blender.exe"
UNITY="/c/Program Files/Unity/Hub/Editor/2022.3.62f2/Editor/Unity.exe"
GAME_MOD="/f/SteamLibrary/steamapps/common/7 Days To Die/Mods/VisibleClothing"
args=(); install=0; only_install=0
for a in "$@"; do
  case "$a" in --install) install=1 ;; --install-only) install=1; only_install=1 ;; *) args+=("$a") ;; esac
done
game_running() { tasklist //FI "IMAGENAME eq 7DaysToDie.exe" 2>/dev/null | grep -qi 7DaysToDie; }
do_install() {
  if game_running; then
    echo "!! 7 Days to Die is running, so its mod files are locked: NOT installed."
    echo "!! Close the game, then run:  bash tools/rebuild_from_fitting.sh --install-only"
    exit 2
  fi
  cp -r Mod/VisibleClothing/. "$GAME_MOD/" && echo "installed -> $GAME_MOD"
}
if [ $only_install = 1 ]; then do_install; exit 0; fi
"$BL" -b --factory-startup -P tools/from_fitting_blend.py -- "${args[@]}" 2>&1 | grep -E "verts|DONE|Error|Traceback" || exit 1
python tools/pack_unity.py > /dev/null || exit 1
"$UNITY" -batchmode -quit -nographics -projectPath "$PWD/unity" -executeMethod BuildClothing.Build -logFile _work/unity_build.log
grep -E "\[VC\]" _work/unity_build.log || { grep -E "error|Exception" _work/unity_build.log | head; exit 1; }
cp unity/BundleOut/visibleclothing.unity3d Mod/VisibleClothing/Resources/VisibleClothing.unity3d
if [ $install = 1 ]; then do_install; else echo "built (not installed: add --install)"; fi
