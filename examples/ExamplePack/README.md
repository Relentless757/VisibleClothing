# Example clothing pack

A pack made with the Visible Clothing pack tools (see [docs/MAKING_CLOTHING.md](../../docs/MAKING_CLOTHING.md)):
two **new** clothing items, a beanie (head slot, based on the Patchwork Cap Liner) and fingerless hand wraps
(hands slot, based on the Tattered Glove Liners).

The models are not in the repository. To build it yourself, copy two of Visible Clothing's source models (or any
models of your own) into `models/`:

```
models/ExampleBeanie.fbx   models/ExampleBeanie.fbm/   (textures)
models/ExampleWraps.fbx    models/ExampleWraps.fbm/    (one glove is enough: the other hand is mirrored)
```

then, in Git Bash from the repository folder:

```bash
bash tools/vcpack.sh fitting examples/ExamplePack      # makes examples/ExamplePack/fitting.blend: fit the items
bash tools/vcpack.sh build examples/ExamplePack --raw --install
```

The add-on is written to `dist/VisibleClothing_Example/` and needs the VisibleClothing mod installed. The new items
are in the creative menu (give them recipes or loot with your own XML in `Config/`).
