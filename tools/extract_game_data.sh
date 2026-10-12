#!/bin/bash
# One-time setup: read the vanilla player bodies, the 32 heads and the boots from YOUR game install into _work/
# (local only, never shipped or committed). Run in Git Bash from the repository folder.
#   bash tools/extract_game_data.sh            (GAME_DIR overrides the game folder)
set -e
cd "$(dirname "$0")/.."
GAME_DIR="${GAME_DIR:-/f/SteamLibrary/steamapps/common/7 Days To Die}"
A="$GAME_DIR/Data/Addressables/Standalone/player_assets_entities/player"
[ -d "$A" ] || { echo "not found: $A (set GAME_DIR)"; exit 1; }
mkdir -p _work/heads _work/out
for sex in male female; do
  Sex=${sex^}
  echo "== $sex body"
  python -I tools/extract_body.py "$A/$sex/common.bundle" "player$Sex.fbx" "_work/body_$sex.json" | tail -1
  for race in asian black native white; do
    for n in 01 02 03 04; do
      python -I tools/extract_body.py "$A/$sex/heads/$race/$n.bundle" "player$Sex${race^}$n.fbx" "_work/heads/${sex}_$race$n.json" > /dev/null
    done
  done
  cp "_work/heads/${sex}_white01.json" "_work/head_$sex.json"      # the default head
  echo "== $sex boots"
  python tools/dump_boots.py "_work/vanilla_boots_$sex.json" "$A/$sex/gear/"*.bundle > /dev/null
done
python tools/head_envelope.py
echo "done: _work/ has the bodies, 32 heads, head envelopes and boots"
