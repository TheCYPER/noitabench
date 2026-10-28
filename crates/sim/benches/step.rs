//! How fast does the simulation run? A 768 x 1664 world (the size of the real game world,
//! `world-design.md` section 2.1) in three states. Criterion reports elements per second, one
//! element being one simulated frame, so the figure is frames per second (the game needs 60 for
//! real time; the agent runs want as many as possible).
//!
//! Run with `cargo bench -p cogbench-sim`.

use cogbench_sim::rng::Stream;
use cogbench_sim::{Content, Tuning, World};
use criterion::{criterion_group, criterion_main, BatchSize, Criterion, Throughput};
use std::sync::Arc;

const W: i32 = 768;
const H: i32 = 1664;
const FRAMES: u32 = 60;

/// A cave level: ground with random caves, rock bands, pools, powder, some wood and gunpowder.
fn level(content: &Arc<Content>) -> World {
    let mut w = World::new(W, H, 42, Arc::clone(content)).expect("world");
    let mut rng = Stream::new(42, "bench-level");
    w.fill_rect(0, 120, W, H - 120, "ground").unwrap();
    for band in 0..12 {
        w.fill_rect(0, 200 + band * 130, W, 14, "rock").unwrap();
    }
    for _ in 0..260 {
        let (x, y) = (
            rng.below(W as u32) as i32,
            130 + rng.below((H - 160) as u32) as i32,
        );
        let r = 6 + rng.below(18) as i32;
        w.paint(x, y, r, "air").unwrap();
        // Fill the lower cap of the cave with a pool or a pile: full rows, so it can settle.
        let key = [
            "water",
            "water",
            "water",
            "oil",
            "sand",
            "coal",
            "lava",
            "toxic_sludge",
        ][rng.below(8) as usize];
        for dy in r / 3..=r {
            let half = f64::from(r * r - dy * dy).sqrt() as i32;
            w.fill_rect(x - half, y + dy, 2 * half + 1, 1, key).unwrap();
        }
        if rng.below(5) == 0 {
            w.fill_rect(x - 2, y - r, 4, r, "wood").unwrap();
        }
        if rng.below(12) == 0 {
            w.paint(x, y + r / 2, 3, "gunpowder").unwrap();
        }
    }
    w
}

/// Typical play: liquids pouring, a fire burning, nothing exploding.
fn typical(content: &Arc<Content>) -> Vec<u8> {
    let mut w = level(content);
    w.fill_rect(300, 100, 40, 20, "water").unwrap();
    w.fill_rect(500, 100, 40, 12, "oil").unwrap();
    w.step_frames(2).unwrap();
    for (x, y) in [(120, 400), (460, 700), (600, 1000)] {
        w.paint(x, y, 4, "fire").unwrap();
    }
    w.step_frames(90).unwrap();
    w.snapshot().expect("snapshot")
}

/// The same level after it has had time to settle.
fn quiet(content: &Arc<Content>) -> Vec<u8> {
    let mut w = level(content);
    w.step_frames(1500).unwrap();
    w.snapshot().expect("snapshot")
}

/// Everything at once: a big water pour onto lava, fire everywhere, several blasts.
fn heavy(content: &Arc<Content>) -> Vec<u8> {
    let mut w = level(content);
    w.fill_rect(100, 100, 560, 30, "water").unwrap();
    w.fill_rect(100, 60, 560, 30, "sand").unwrap();
    for (x, y) in [(150, 500), (400, 800), (650, 1100), (300, 1400)] {
        w.paint(x, y, 40, "lava").unwrap();
        w.paint(x + 60, y, 30, "gunpowder").unwrap();
        w.paint(x + 60, y - 8, 3, "fire").unwrap();
    }
    w.step_frames(60).unwrap();
    w.snapshot().expect("snapshot")
}

/// Awake chunks and the cells inside their dirty rectangles: what one frame has to visit.
fn activity(world: &World) -> (usize, i64) {
    let (cw, ch) = world.grid().chunk_dims();
    let mut chunks = 0;
    let mut cells = 0;
    for cy in 0..ch {
        for cx in 0..cw {
            let r = world.grid().dirty_rect(cx, cy);
            if !r.is_empty() {
                chunks += 1;
                cells += i64::from(r.x1 - r.x0 + 1) * i64::from(r.y1 - r.y0 + 1);
            }
        }
    }
    (chunks, cells)
}

fn bench_scenario(c: &mut Criterion, name: &str, content: &Arc<Content>, blob: &[u8]) {
    let mut probe = World::new(8, 8, 0, Arc::clone(content)).expect("world");
    probe.restore(blob).expect("restore");
    let (chunks, cells) = activity(&probe);
    eprintln!(
        "{name}: {chunks} of 312 chunks awake, {cells} of {} cells in dirty rectangles",
        W * H
    );
    let mut group = c.benchmark_group("step_768x1664");
    group.throughput(Throughput::Elements(u64::from(FRAMES)));
    group.sample_size(10);
    group.bench_function(name, |b| {
        b.iter_batched_ref(
            || {
                let mut w = World::new(8, 8, 0, Arc::clone(content)).expect("world");
                w.restore(blob).expect("restore");
                w
            },
            |w| w.step_frames(FRAMES).unwrap(),
            BatchSize::LargeInput,
        );
    });
    group.finish();
}

fn benches(c: &mut Criterion) {
    let content = Arc::new(Content::embedded_with(Tuning::default()).expect("content"));
    bench_scenario(c, "quiet", &content, &quiet(&content));
    bench_scenario(c, "typical", &content, &typical(&content));
    bench_scenario(c, "heavy", &content, &heavy(&content));
}

criterion_group!(step, benches);
criterion_main!(step);
