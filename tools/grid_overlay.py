import sys
from PIL import Image, ImageDraw
# img, cx, cz (world centre of the view, horizontal & vertical), size (ortho), horiz axis sign, out
p, cx, cz, size, sgn, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), sys.argv[6]
im = Image.open(p).convert("RGB"); W = im.width; d = ImageDraw.Draw(im)
px = W / size
import math
for k in range(-12, 13):
    v = round(k * 0.05, 2)
    x = W / 2 + sgn * (v - cx) * px; y = W / 2 - (v - cz) * px
    col = (255, 80, 80) if k % 2 == 0 else (90, 90, 90)
    if 0 <= x < W: d.line([(x, 0), (x, W)], fill=col, width=1); d.text((x + 2, 2), f"{v:+.2f}", fill=(255, 255, 0))
    vz = round(cz + k * 0.05 - (cz % 0.05), 2); y = W / 2 - (vz - cz) * px
    if 0 <= y < W: d.line([(0, y), (W, y)], fill=(90, 90, 90) if round(vz/0.05) % 2 else (255, 80, 80), width=1); d.text((2, y + 2), f"z{vz:.2f}", fill=(0, 255, 255))
im.save(out)
