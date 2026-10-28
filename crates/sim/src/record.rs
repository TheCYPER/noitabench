//! Recording writer for `runs/<run_id>/` (contract section 5, `cogbench-rec/0`).
//!
//! `meta.json`, `frames.bin` (frame records with zlib-compressed rectangles of material indices)
//! and `events.jsonl`. Write errors are remembered and reported by `check`/`finish`, so the hot
//! loop stays infallible.

use crate::error::{Error, Result};
use crate::grid::{Cell, Grid};
use crate::material::MATERIALS_FORMAT;
use flate2::write::ZlibEncoder;
use flate2::Compression;
use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};

pub const RECORDING_FORMAT: &str = "cogbench-rec/0";

/// How to record.
#[derive(Clone, Debug)]
pub struct RecordConfig {
    pub dir: PathBuf,
    /// Write a frame record every this many simulated frames (the first one at the start).
    pub frame_stride: u32,
    /// `(x, y, w, h)` of the part of the world to record; `None` = the whole world.
    pub rect: Option<(i32, i32, i32, i32)>,
    /// Defaults to the directory name.
    pub run_id: Option<String>,
    /// ISO-8601 UTC timestamp for `meta.json`; defaults to the wall clock. It is the only field
    /// of a recording that differs between two otherwise identical runs.
    pub created: Option<String>,
    pub notes: String,
}

impl RecordConfig {
    pub fn new(dir: impl Into<PathBuf>, frame_stride: u32) -> Self {
        RecordConfig {
            dir: dir.into(),
            frame_stride,
            rect: None,
            run_id: None,
            created: None,
            notes: String::new(),
        }
    }
}

/// What a finished recording contains.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecordSummary {
    pub dir: PathBuf,
    pub frames: u64,
    pub first_frame: u64,
    pub last_frame: u64,
}

pub(crate) struct Recorder {
    dir: PathBuf,
    meta: serde_json::Map<String, serde_json::Value>,
    frames: BufWriter<File>,
    events: BufWriter<File>,
    stride: u32,
    rect: (i32, i32, i32, i32),
    count: u64,
    first: Option<u64>,
    last: Option<u64>,
    error: Option<io::Error>,
    scratch: Vec<u8>,
}

fn open(path: &Path) -> Result<BufWriter<File>> {
    File::create(path)
        .map(BufWriter::new)
        .map_err(|e| Error::io(format!("creating {}", path.display()), e))
}

/// `2026-10-26T18:47:03Z` from the system clock (no calendar crate needed).
fn utc_now() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs() as i64);
    let (days, rem) = (secs.div_euclid(86_400), secs.rem_euclid(86_400));
    // Civil-from-days (Howard Hinnant).
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rem / 3600,
        rem % 3600 / 60,
        rem % 60
    )
}

/// The `meta.json` fields known when a recording starts.
fn build_meta(
    cfg: &RecordConfig,
    rect: (i32, i32, i32, i32),
    (width, height): (i32, i32),
    (seed, rule_seed): (u64, u64),
) -> serde_json::Map<String, serde_json::Value> {
    let run_id = cfg.run_id.clone().unwrap_or_else(|| {
        cfg.dir
            .file_name()
            .map_or_else(|| "run".to_string(), |n| n.to_string_lossy().into_owned())
    });
    let (x, y, w, h) = rect;
    let mut meta = serde_json::Map::new();
    let mut put = |k: &str, v: serde_json::Value| {
        meta.insert(k.to_string(), v);
    };
    put("format", RECORDING_FORMAT.into());
    put("run_id", run_id.into());
    put(
        "created",
        cfg.created.clone().unwrap_or_else(utc_now).into(),
    );
    put(
        "world",
        serde_json::json!({ "width": width, "height": height }),
    );
    put("materials_format", MATERIALS_FORMAT.into());
    put("seed", seed.into());
    put("rule_seed", rule_seed.into());
    put("frame_stride", cfg.frame_stride.into());
    put("rect", serde_json::json!([x, y, w, h]));
    put("notes", cfg.notes.clone().into());
    meta
}

impl Recorder {
    pub(crate) fn start(
        cfg: RecordConfig,
        width: i32,
        height: i32,
        seed: u64,
        rule_seed: u64,
    ) -> Result<Recorder> {
        if cfg.frame_stride == 0 {
            return Err(Error::arg("frame_stride must be >= 1"));
        }
        let rect = cfg.rect.unwrap_or((0, 0, width, height));
        let (x, y, w, h) = rect;
        let (x64, y64, w64, h64) = (i64::from(x), i64::from(y), i64::from(w), i64::from(h));
        if w <= 0
            || h <= 0
            || x < 0
            || y < 0
            || x64 + w64 > i64::from(width)
            || y64 + h64 > i64::from(height)
        {
            return Err(Error::arg(format!(
                "recording rect {rect:?} must lie inside the {width}x{height} world"
            )));
        }
        std::fs::create_dir_all(&cfg.dir)
            .map_err(|e| Error::io(format!("creating {}", cfg.dir.display()), e))?;
        let meta = build_meta(&cfg, rect, (width, height), (seed, rule_seed));
        let rec = Recorder {
            frames: open(&cfg.dir.join("frames.bin"))?,
            events: open(&cfg.dir.join("events.jsonl"))?,
            dir: cfg.dir,
            meta,
            stride: cfg.frame_stride,
            rect,
            count: 0,
            first: None,
            last: None,
            error: None,
            scratch: Vec::new(),
        };
        rec.write_meta()?;
        Ok(rec)
    }

    fn write_meta(&self) -> Result<()> {
        let path = self.dir.join("meta.json");
        let text =
            serde_json::to_string_pretty(&self.meta).map_err(|e| Error::arg(e.to_string()))?;
        std::fs::write(&path, text + "\n")
            .map_err(|e| Error::io(format!("writing {}", path.display()), e))
    }

    pub(crate) fn stride(&self) -> u32 {
        self.stride
    }

    pub(crate) fn last_frame(&self) -> Option<u64> {
        self.last
    }

    fn remember(&mut self, r: io::Result<()>) {
        if let Err(e) = r {
            self.error.get_or_insert(e);
        }
    }

    /// Append one frame record (`u32 frame | u16 x0 y0 w h | u8 codec | u32 nbytes | payload`).
    pub(crate) fn write_frame(&mut self, frame: u64, grid: &Grid) {
        let (x0, y0, w, h) = self.rect;
        self.scratch.clear();
        for y in y0..y0 + h {
            let row = grid.idx(x0, y);
            self.scratch.extend(
                grid.cells()[row..row + w as usize]
                    .iter()
                    .map(|c: &Cell| c.mat),
            );
        }
        let (codec, payload) = match compress(&self.scratch) {
            Ok(z) if z.len() < self.scratch.len() => (1u8, z),
            _ => (0u8, self.scratch.clone()),
        };
        let mut head = Vec::with_capacity(19);
        head.extend_from_slice(&(frame as u32).to_le_bytes());
        for v in [x0, y0, w, h] {
            head.extend_from_slice(&(v as u16).to_le_bytes());
        }
        head.push(codec);
        head.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        let r = self
            .frames
            .write_all(&head)
            .and_then(|()| self.frames.write_all(&payload));
        self.remember(r);
        self.count += 1;
        self.first.get_or_insert(frame);
        self.last = Some(frame);
    }

    pub(crate) fn write_event(&mut self, line: &str) {
        let r = self
            .events
            .write_all(line.as_bytes())
            .and_then(|()| self.events.write_all(b"\n"));
        self.remember(r);
    }

    /// Report the first write error, if any.
    pub(crate) fn check(&mut self) -> Result<()> {
        match self.error.take() {
            Some(e) => Err(Error::io(format!("recording to {}", self.dir.display()), e)),
            None => Ok(()),
        }
    }

    pub(crate) fn finish(mut self) -> Result<RecordSummary> {
        let flushed = self.frames.flush().and_then(|()| self.events.flush());
        self.remember(flushed);
        self.check()?;
        self.meta.insert("frame_count".into(), self.count.into());
        self.meta
            .insert("first_frame".into(), self.first.unwrap_or(0).into());
        self.meta
            .insert("last_frame".into(), self.last.unwrap_or(0).into());
        self.write_meta()?;
        Ok(RecordSummary {
            dir: self.dir,
            frames: self.count,
            first_frame: self.first.unwrap_or(0),
            last_frame: self.last.unwrap_or(0),
        })
    }
}

fn compress(data: &[u8]) -> io::Result<Vec<u8>> {
    let mut enc = ZlibEncoder::new(Vec::new(), Compression::fast());
    enc.write_all(data)?;
    enc.finish()
}
