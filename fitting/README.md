# Hand-fitting the clothing

Open `VisibleClothing_Fitting.blend` (Blender 5.x). Front view (numpad 1) looks at the character's face.

- **Body Male / Body Female**: the game's own body, hands, feet and head, read from your install.
  Reference only (not selectable). Bones don't matter here: the game uses this exact rest pose (A-pose).
- **Clothing Male**: the 12 items as the auto-fitter left them. Move, scale, sculpt, proportional-edit,
  add modifiers, whatever you like. Keep the object names (`ClothingOutfitT2`, ...).
  - Modifiers and object transforms are applied on export, so you don't need to apply them.
  - Gloves are one object holding both hands; left and right must both be fitted.
  - Keep a few mm between cloth and skin. The rebuild pushes anything that ends up inside the skin back out
    (skip that with `--raw`). It also keeps the layering of the automatic fit (also skipped with `--raw`):
    shirts stay over the head (all 16 face shapes) and T1/T2 shirts over their pants; the T3 shirt stays tucked
    under the T3 pants; the balaclava stays under every shirt; pants stay over vanilla boots and our shoes.
    So rebuild in that order if you change several (the script does: shoes, gloves, pants, shirts, hats).
  - Skin weights are always recalculated (you don't paint them here).
  - The T2 shirt gets a thin lining under its panel seams on rebuild; it isn't in this file, don't add one.
  - You can swap the texture: the first image texture in the object's material is used.
- **Clothing Female**: empty. The female version is made automatically from the male fit. To fit a piece for
  the female body by hand, show "Body Female", copy the item into this collection and keep the
  same name (Blender adds `.001`; that's fine).

Rebuild (from the project folder, Git Bash):

    bash tools/rebuild_from_fitting.sh --install                 # all items
    bash tools/rebuild_from_fitting.sh ClothingOutfitT3 --install  # just one

Then restart the game (or reload the bundle) to see it.
