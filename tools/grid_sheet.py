import sys
from PIL import Image
txt, out = sys.argv[1], sys.argv[2]
rows = [l.split("	") for l in open(txt).read().splitlines() if l.strip()]
ims = [[Image.open(p) for p in r] for r in rows]
W = sum(i.width for i in ims[0]); H = sum(r[0].height for r in ims)
s = Image.new("RGB", (W, H)); y = 0
for r in ims:
    x = 0
    for i in r: s.paste(i, (x, y)); x += i.width
    y += r[0].height
s.save(out)
