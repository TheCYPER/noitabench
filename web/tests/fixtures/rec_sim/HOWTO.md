# rec_sim: a recording written by the real simulation

`meta.json`, `frames.bin` and `events.jsonl` were written by `cogbench_sim::World::start_recording`
(crate `cogbench-sim`, `crates/sim/src/record.rs`, 2026-10-26, week 1). Nothing was edited by hand.
The scenario was a 96x64 world with a rock floor and walls, a ground block, a wooden shelf, a ball each of
sand, water and lava falling, a pocket of oil on the shelf that was ignited at frame 120.
It exercises what the synthetic fixtures cannot: u64 seeds above 2^53 in `meta.json`, the extra `rect`,
`frame_count`, `first_frame`, `last_frame` fields, and the real `events.jsonl` lines (`reaction`,
`ignite`, `extinguish` with `x`, `y`, `bx`, `by`).

To regenerate it, run a small program in a scratch cargo project (not part of the repo) next to the
repository, depending on `cogbench-sim` by path:

```rust
use cogbench_sim::{Content, RecordConfig, World};
use std::sync::Arc;

fn main() {
    let out = std::env::args().nth(1).unwrap();
    let content = Arc::new(Content::embedded().unwrap());
    let (w, h) = (96, 64);
    let mut world = World::new(w, h, 0xDEAD_BEEF_CAFE_BABE, content).unwrap();
    world.set_rule_seed(0xFEED_FACE_0123_4567);
    world.fill_rect(0, h - 6, w, 6, "rock").unwrap();
    world.fill_rect(0, 0, 2, h, "rock").unwrap();
    world.fill_rect(w - 2, 0, 2, h, "rock").unwrap();
    world.fill_rect(10, h - 16, 18, 10, "ground").unwrap();
    world.fill_rect(40, h - 26, 26, 3, "wood").unwrap();
    world.paint(22, 10, 5, "sand").unwrap();
    world.paint(48, 14, 6, "water").unwrap();
    world.paint(76, 14, 4, "lava").unwrap();
    world.paint(52, h - 29, 2, "oil").unwrap();
    let mut cfg = RecordConfig::new(&out, 6);
    cfg.created = Some("2026-10-26T00:00:00Z".into());
    cfg.notes = "produced by cogbench-sim World::start_recording (see HOWTO.md)".into();
    world.start_recording(cfg).unwrap();
    world.step_frames(120).unwrap();
    world.ignite(52, h - 30);
    world.step_frames(120).unwrap();
    world.stop_recording().unwrap();
}
```

Replace these files whenever the recording format or the simulation's event lines change, then run
`.venv/bin/python web/tests/make_sim_expected.py` to rebuild `expected.json` (hashes decoded by Python, not by
the viewer), and `node --test web/tests/`.
