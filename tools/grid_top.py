"""Label a raw_grid 'top' render with true world X/Y (that camera has image-up = -Y, image-right = -X)."""
import sys
from PIL import Image, ImageDraw
p, size, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
im = Image.open(p).convert("RGB"); W = im.width; d = ImageDraw.Draw(im); px = W / size
for k in range(-12, 13):
    v = round(k * 0.05, 2); col = (255, 80, 80) if k % 2 == 0 else (90, 90, 90)
    x = W / 2 - v * px
    if 0 <= x < W: d.line([(x, 0), (x, W)], fill=col); d.text((x + 2, 2), f"x{v:+.2f}", fill=(255, 255, 0))
    y = W / 2 + v * px
    if 0 <= y < W: d.line([(0, y), (W, y)], fill=col); d.text((2, y + 2), f"y{v:+.2f}", fill=(0, 255, 255))
im.save(out)
