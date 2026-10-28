# Component Guidelines

- One shared renderer (`js/render/`) draws a material-index buffer to a `<canvas>` with the colours from `materials.json`, nearest-neighbour scaling and integer zoom; every page reuses it.
- Overlays (entities, projectiles, event markers, encounter trigger boxes, the main path) are separate draw passes on top of the material layer.
- Pages are thin: they load files, own a playback state object and call the renderer.
- Keep each module under about 300 lines; no framework.
