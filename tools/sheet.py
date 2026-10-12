import sys
from PIL import Image
out, *ins = sys.argv[1:]
ims = [Image.open(p) for p in ins]
W = sum(i.width for i in ims); H = max(i.height for i in ims)
s = Image.new("RGB", (W, H)); x = 0
for i in ims: s.paste(i, (x, 0)); x += i.width
s.save(out)
