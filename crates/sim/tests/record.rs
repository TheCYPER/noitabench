//! Recording writer: contract section 5 (`cogbench-rec/0`). The reader here is written from the
//! contract text alone, independent of the writer, so it also checks what the web viewer sees.

mod common;
use cogbench_sim::{RecordConfig, Tuning, World};
use common::*;
use flate2::read::ZlibDecoder;
use std::io::Read;
use std::path::Path;

struct Frame {
    frame: u32,
    x0: usize,
    y0: usize,
    w: usize,
    h: usize,
    pixels: Vec<u8>,
}

fn read_frames(path: &Path) -> Vec<Frame> {
    let bytes = std::fs::read(path).expect("frames.bin");
    let mut frames = Vec::new();
    let mut p = 0;
    let u16_at = |p: usize| usize::from(u16::from_le_bytes([bytes[p], bytes[p + 1]]));
    let u32_at = |p: usize| u32::from_le_bytes(bytes[p..p + 4].try_into().unwrap());
    while p < bytes.len() {
        let frame = u32_at(p);
        let (x0, y0, w, h) = (u16_at(p + 4), u16_at(p + 6), u16_at(p + 8), u16_at(p + 10));
        let codec = bytes[p + 12];
        let n = u32_at(p + 13) as usize;
        let payload = &bytes[p + 17..p + 17 + n];
        let pixels = match codec {
            0 => payload.to_vec(),
            1 => {
                let mut out = Vec::new();
                ZlibDecoder::new(payload).read_to_end(&mut out).unwrap();
                out
            }
            other => panic!("unknown codec {other}"),
        };
        assert_eq!(pixels.len(), w * h, "payload is w*h bytes");
        frames.push(Frame {
            frame,
            x0,
            y0,
            w,
            h,
            pixels,
        });
        p += 17 + n;
    }
    assert_eq!(p, bytes.len(), "no trailing bytes");
    frames
}

fn scene_world() -> World {
    let mut w = World::new(70, 50, 12, content(Tuning::default())).unwrap();
    w.fill_rect(0, 40, 70, 10, "rock").unwrap();
    w.paint(20, 10, 5, "water").unwrap();
    w.paint(45, 30, 4, "gunpowder").unwrap();
    w.ignite(45, 30);
    w
}

#[test]
fn rec_meta_frames_and_events_follow_the_contract() {
    let dir = tempfile::tempdir().unwrap();
    let run = dir.path().join("demo-test");
    let mut w = scene_world();
    let mut cfg = RecordConfig::new(&run, 3);
    cfg.created = Some("2026-10-26T00:00:00Z".into());
    cfg.notes = "unit test".into();
    w.start_recording(cfg).unwrap();
    w.step_frames(100).unwrap();
    let summary = w.stop_recording().unwrap();

    let meta: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(run.join("meta.json")).unwrap()).unwrap();
    assert_eq!(meta["format"], "cogbench-rec/0");
    assert_eq!(meta["run_id"], "demo-test");
    assert_eq!(
        meta["world"],
        serde_json::json!({"width": 70, "height": 50})
    );
    assert_eq!(meta["materials_format"], "cogbench-materials/0");
    assert_eq!(meta["seed"], 12);
    assert_eq!(meta["frame_stride"], 3);
    assert_eq!(meta["created"], "2026-10-26T00:00:00Z");

    let frames = read_frames(&run.join("frames.bin"));
    // frame 0, then every third frame up to 99, then the final frame 100
    let numbers: Vec<u32> = frames.iter().map(|f| f.frame).collect();
    let mut expected: Vec<u32> = (0..=99).step_by(3).collect();
    expected.push(100);
    assert_eq!(numbers, expected);
    assert_eq!(summary.frames as usize, frames.len());
    let last = frames.last().unwrap();
    assert_eq!((last.x0, last.y0, last.w, last.h), (0, 0, 70, 50));
    assert_eq!(
        last.pixels,
        w.grid_bytes(),
        "the last record is the final state"
    );

    let events = std::fs::read_to_string(run.join("events.jsonl")).unwrap();
    let parsed: Vec<serde_json::Value> = events
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    assert!(
        parsed.iter().any(|e| e["type"] == "explosion"),
        "the gunpowder blast is logged"
    );
    assert!(parsed
        .iter()
        .all(|e| e["frame"].is_u64() && e["type"].is_string()));
}

#[test]
fn rec_rect_records_only_that_part_of_the_world() {
    let dir = tempfile::tempdir().unwrap();
    let run = dir.path().join("rect");
    let mut w = scene_world();
    let mut cfg = RecordConfig::new(&run, 10);
    cfg.rect = Some((10, 5, 30, 20));
    w.start_recording(cfg).unwrap();
    w.step_frames(20).unwrap();
    w.stop_recording().unwrap();
    let frames = read_frames(&run.join("frames.bin"));
    assert_eq!(frames.len(), 3);
    for f in &frames {
        assert_eq!((f.x0, f.y0, f.w, f.h), (10, 5, 30, 20));
    }
    let world = w.grid_bytes();
    let last = frames.last().unwrap();
    for y in 0..20 {
        for x in 0..30 {
            assert_eq!(last.pixels[y * 30 + x], world[(5 + y) * 70 + 10 + x]);
        }
    }
}

#[test]
fn rec_same_seed_same_bytes_except_the_creation_time() {
    let make = |name: &str| {
        let dir = tempfile::tempdir().unwrap();
        let run = dir.path().join(name);
        let mut w = scene_world();
        let mut cfg = RecordConfig::new(&run, 2);
        cfg.created = Some("fixed".into());
        w.start_recording(cfg).unwrap();
        w.step_frames(60).unwrap();
        w.stop_recording().unwrap();
        let read = |f: &str| std::fs::read(run.join(f)).unwrap();
        (
            read("meta.json"),
            read("frames.bin"),
            read("events.jsonl"),
            dir,
        )
    };
    let (a, b) = (make("same"), make("same"));
    assert_eq!((&a.0, &a.1, &a.2), (&b.0, &b.1, &b.2));
}

#[test]
fn rec_errors_are_reported() {
    let dir = tempfile::tempdir().unwrap();
    let mut w = scene_world();
    assert!(w
        .start_recording(RecordConfig::new(dir.path().join("a"), 0))
        .is_err());
    let mut cfg = RecordConfig::new(dir.path().join("b"), 1);
    cfg.rect = Some((60, 40, 20, 20));
    assert!(w
        .start_recording(cfg)
        .unwrap_err()
        .to_string()
        .contains("must lie inside"));
    assert!(w.stop_recording().is_err(), "nothing is recording");
    w.start_recording(RecordConfig::new(dir.path().join("c"), 1))
        .unwrap();
    assert!(w
        .start_recording(RecordConfig::new(dir.path().join("d"), 1))
        .is_err());
    // A file where the directory should be.
    let file = dir.path().join("file");
    std::fs::write(&file, "x").unwrap();
    let mut w2 = scene_world();
    assert!(w2
        .start_recording(RecordConfig::new(file.join("run"), 1))
        .is_err());
}

#[test]
fn rec_restore_is_refused_while_recording() {
    // Frame numbers in a recording never decrease, so time may not run backwards under it.
    let dir = tempfile::tempdir().unwrap();
    let mut w = scene_world();
    let blob = w.snapshot().unwrap();
    w.start_recording(RecordConfig::new(dir.path().join("r"), 1))
        .unwrap();
    w.step_frames(3).unwrap();
    assert!(w
        .restore(&blob)
        .unwrap_err()
        .to_string()
        .contains("stop it"));
    w.stop_recording().unwrap();
    w.restore(&blob).unwrap();
}

#[test]
fn rec_rect_arguments_cannot_overflow() {
    let dir = tempfile::tempdir().unwrap();
    let mut w = scene_world();
    for rect in [
        (i32::MAX, 0, 10, 10),
        (0, 0, i32::MAX, 5),
        (5, 5, i32::MAX, i32::MAX),
        (-1, 0, 5, 5),
    ] {
        let mut cfg = RecordConfig::new(dir.path().join("r"), 1);
        cfg.rect = Some(rect);
        let err = w.start_recording(cfg).unwrap_err().to_string();
        assert!(err.contains("must lie inside"), "{rect:?}: {err}");
    }
}
