#!/bin/bash
# Visible Clothing pack tool (run in Git Bash). See docs/MAKING_CLOTHING.md.
#   bash tools/vcpack.sh new      <pack folder> <ModName>    scaffold pack.json, models/, Config/
#   bash tools/vcpack.sh fitting  <pack folder>              create / update <pack>/fitting.blend (adds new items)
#   bash tools/vcpack.sh build    <pack folder> [Item ...] [--raw] [--install]
#                                                            fit + weights, textures, bundle, add-on mod in <pack>/dist
#   bash tools/vcpack.sh install  <pack folder>              copy <pack>/dist/<ModName> into the game's Mods folder
# Tool paths: set BLENDER / UNITY / GAME_DIR in the environment to override the defaults below.
set -e
cd "$(dirname "$0")/.."
if grep -qi microsoft /proc/version 2>/dev/null; then
  echo "!! This is WSL bash: run it from Git Bash (the tools use Windows paths)."; exit 1
fi
BL="${BLENDER:-/f/Game Related Programs/Creation Stuff/Blender Foundation/blender.exe}"
UNITY="${UNITY:-/c/Program Files/Unity/Hub/Editor/2022.3.62f2/Editor/Unity.exe}"
GAME_DIR="${GAME_DIR:-/f/SteamLibrary/steamapps/common/7 Days To Die}"
cmd="$1"; shift || true
pack="$1"; shift || true
[ -n "$cmd" ] && [ -n "$pack" ] || { sed -n 2,8p "$0"; exit 1; }

if [ "$cmd" = new ]; then
  name="${1:-VisibleClothing_MyPack}"
  [ -e "$pack/pack.json" ] && { echo "$pack/pack.json exists"; exit 1; }
  mkdir -p "$pack/models" "$pack/Config"
  cat > "$pack/pack.json" <<EOF
{
  "name": "$name",
  "display_name": "${name#VisibleClothing_} (Visible Clothing pack)",
  "author": "",
  "version": "1.0.0",
  "description": "",
  "items": [
    {
      "id": "MyHat",
      "kind": "head",
      "model": "models/MyHat.fbx",
      "game_item": "clothingHeadMyHat",
      "new_item": {"extends": "clothingHeadT1", "name": "My Hat", "description": "A hat."},
      "hair_mask": "Hat",
      "facial_hair_mask": "Full"
    }
  ]
}
EOF
  echo "created $pack: put models/MyHat.fbx (+ models/MyHat.fbm/ textures) there, edit pack.json, then:"
  echo "  bash tools/vcpack.sh fitting \"$pack\""
  exit 0
fi

export VC_PACK="$(cd "$pack" && { pwd -W 2>/dev/null || pwd; })"
[ -f "$VC_PACK/pack.json" ] || { echo "no pack.json in $pack"; exit 1; }
py() { python -c "import sys; sys.path.insert(0, 'tools'); import vc_pack; print($1)"; }
NAME="$(py vc_pack.NAME)"
game_running() { tasklist //FI "IMAGENAME eq 7DaysToDie.exe" 2>/dev/null | grep -qi 7DaysToDie; }
install() {
  if game_running; then echo "!! 7 Days to Die is running (mod files locked): close it, then: bash tools/vcpack.sh install \"$pack\""; exit 2; fi
  mkdir -p "$GAME_DIR/Mods/$NAME"
  cp -r "$VC_PACK/dist/$NAME/." "$GAME_DIR/Mods/$NAME/" && echo "installed -> $GAME_DIR/Mods/$NAME"
}

case "$cmd" in
  fitting)
    "$BL" -b --factory-startup -P tools/make_fitting_blend.py 2>&1 | grep -E "placed|SAVED|added|nothing added|Error|Traceback" || true
    echo "open $VC_PACK/fitting.blend: fit each item in 'Clothing Male' onto the body, save, then build" ;;
  build)
    args=(); inst=0
    for a in "$@"; do [ "$a" = --install ] && inst=1 || args+=("$a"); done
    "$BL" -b --factory-startup -P tools/from_fitting_blend.py -- "${args[@]}" 2>&1 | grep -E "verts$|DONE|skipped|one glove|Error|Traceback"
    python tools/prep_textures.py
    python tools/pack_unity.py > /dev/null
    "$UNITY" -batchmode -quit -nographics -projectPath "$PWD/unity" -executeMethod BuildClothing.Build \
      -vcRoot "$(py vc_pack.UNITY_ROOT)" -vcBundle "$(py vc_pack.BUNDLE)" -logFile "$VC_PACK/build/unity_build.log" || true
    grep -E "\[VC\] built" "$VC_PACK/build/unity_build.log" || { grep -E "error|Exception" "$VC_PACK/build/unity_build.log" | head; exit 1; }
    python tools/make_mod.py
    [ $inst = 1 ] && install || echo "built: $VC_PACK/dist/$NAME (add --install, or: bash tools/vcpack.sh install \"$pack\")" ;;
  install) install ;;
  *) sed -n 2,8p "$0"; exit 1 ;;
esac
