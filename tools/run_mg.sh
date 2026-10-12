#!/bin/bash
# run_mg.sh <sex> <items...> : make garment + preview, stacked into _work/review.png
cd "$(dirname "$0")/.."
BL="/f/Game Related Programs/Creation Stuff/Blender Foundation/blender.exe"
sex=$1; shift; rows=()
for it in "$@"; do
  "$BL" -b --factory-startup -P tools/make_garment.py -- $it $sex --render > _work/log_${it}_$sex.txt 2>&1
  grep -E "^(part|  baked|outfit|Traceback|Error)|Error:|rror" _work/log_${it}_$sex.txt | head -12
  python tools/sheet.py _work/s_${it}_$sex.png _work/mg_${it}_${sex}_0.png _work/mg_${it}_${sex}_90.png _work/mg_${it}_${sex}_180.png && rows+=(_work/s_${it}_$sex.png)
done
python - "${rows[@]}" <<'PY'
import sys
from PIL import Image
ims=[Image.open(p) for p in sys.argv[1:]]
s=Image.new('RGB',(max(i.width for i in ims),sum(i.height for i in ims)));y=0
for i in ims: s.paste(i,(0,y)); y+=i.height
s.save('_work/review.png')
PY
