# State Management

- Each page holds one plain state object (loaded run, current frame index, playing, speed, zoom, selected decision) and re-renders from it; no hidden state in the DOM.
- Frames are decoded lazily and cached in a bounded LRU (for example 256 frames) so long runs do not exhaust memory.
- Playback speed 0.25×–8×; seeking jumps to the nearest stored frame at or before the target.
- URL hash may hold a bare token (selected tab); everything else stays in memory.
