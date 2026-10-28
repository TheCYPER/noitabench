//! Recordings with entities (contract section 5): the pixel recording of the simulation plus an
//! `entities.jsonl` with one line per recorded frame, written on the same frames.

use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use cogbench_sim::{RecordConfig, RecordSummary};
use serde_json::json;

use crate::error::Error;

use super::Game;

pub(crate) struct EntityRecorder {
    out: BufWriter<File>,
    path: PathBuf,
    stride: u32,
    last: Option<u64>,
}

fn io_error(path: &std::path::Path, source: std::io::Error) -> Error {
    Error::Io {
        path: path.to_path_buf(),
        source,
    }
}

impl Game {
    /// Start recording the world and its entities into `config.dir`.
    pub fn start_recording(&mut self, config: RecordConfig) -> Result<(), Error> {
        let dir = config.dir.clone();
        let stride = config.frame_stride;
        self.world.start_recording(config)?;
        let path = dir.join("entities.jsonl");
        let file = match File::create(&path) {
            Ok(file) => file,
            Err(e) => {
                // Do not leave the pixel recording running without its entity file.
                let _ = self.world.stop_recording();
                return Err(io_error(&path, e));
            }
        };
        self.recorder = Some(EntityRecorder {
            out: BufWriter::new(file),
            path,
            stride,
            last: None,
        });
        self.write_entity_line()
    }

    /// Finish the recording; returns the summary of the pixel frames.
    pub fn stop_recording(&mut self) -> Result<RecordSummary, Error> {
        let frame = self.world.frame();
        if self
            .recorder
            .as_ref()
            .is_some_and(|r| r.last != Some(frame))
        {
            self.write_entity_line()?;
        }
        if let Some(mut r) = self.recorder.take() {
            r.out.flush().map_err(|e| io_error(&r.path, e))?;
        }
        Ok(self.world.stop_recording()?)
    }

    pub fn is_recording(&self) -> bool {
        self.recorder.is_some()
    }

    /// After a world step: write a line when this frame is a recorded one.
    pub(crate) fn record_entities(&mut self) -> Result<(), Error> {
        let frame = self.world.frame();
        match &self.recorder {
            Some(r) if frame.is_multiple_of(u64::from(r.stride)) => self.write_entity_line(),
            _ => Ok(()),
        }
    }

    fn write_entity_line(&mut self) -> Result<(), Error> {
        let frame = self.world.frame();
        let entities: Vec<serde_json::Value> = self
            .entities()
            .into_iter()
            .map(|e| {
                let mut v = json!({
                    "id": e.id, "kind": e.kind,
                    "x": e.x, "y": e.y, "w": e.w, "h": e.h,
                    "hp": e.hp, "hp_max": e.hp_max,
                });
                if !e.detail.is_empty() {
                    v["detail"] = json!(e.detail);
                }
                if !e.statuses.is_empty() {
                    let names: Vec<&str> = e.statuses.iter().map(|(s, _)| s.as_str()).collect();
                    v["status"] = json!(names);
                }
                v
            })
            .collect();
        let line = json!({ "frame": frame, "entities": entities }).to_string();
        let Some(r) = self.recorder.as_mut() else {
            return Ok(());
        };
        r.out
            .write_all(line.as_bytes())
            .and_then(|()| r.out.write_all(b"\n"))
            .map_err(|e| io_error(&r.path, e))?;
        r.last = Some(frame);
        Ok(())
    }
}
