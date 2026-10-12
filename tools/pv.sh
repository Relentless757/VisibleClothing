#!/bin/bash
# pv.sh <name> <items...> : EEVEE preview of exported JSONs, male | female side by side -> <name>.png in _work
cd "$(dirname "$0")/.."
BL="/f/Game Related Programs/Creation Stuff/Blender Foundation/blender.exe"
name=$1; shift
for sex in male female; do
  "$BL" -b --factory-startup -P tools/preview_json.py -- $sex _work/pv_${name}_$sex "$@" > _work/pv_log.txt 2>&1 || grep -E "Error|Traceback" _work/pv_log.txt
  python tools/grid_sheet.py _work/pv_${name}_$sex.txt _work/pv_${name}_$sex.png
done
python - "$name" <<'PY'
import sys
from PIL import Image
n=sys.argv[1]; a=Image.open(f'_work/pv_{n}_male.png'); b=Image.open(f'_work/pv_{n}_female.png')
s=Image.new('RGB',(a.width+b.width+20,max(a.height,b.height)),(40,40,40)); s.paste(a,(0,0)); s.paste(b,(a.width+20,0)); s.save(f'_work/{n}.png')
PY
