//! Loading a world file pair (contract section 4): an 8-bit indexed PNG whose pixel values are
//! material indices, plus a JSON side file with sizes and seeds.

use crate::error::{Error, Result};
use serde::Deserialize;
use std::fs::File;
use std::io::BufReader;
use std::path::Path;

pub const WORLD_FORMAT: &str = "cogbench-world/0";

/// The parts of the world JSON the simulation needs; markers belong to later weeks.
#[derive(Deserialize, Debug, Clone)]
pub struct WorldMeta {
    pub format: String,
    #[serde(default)]
    pub seed: u64,
    #[serde(default)]
    pub rule_seed: u64,
    pub width: i32,
    pub height: i32,
}

/// Decoded world: size, material indices (row-major) and the side file's metadata.
#[derive(Debug)]
pub struct WorldFile {
    pub meta: WorldMeta,
    pub indices: Vec<u8>,
}

pub fn load_world_files(png_path: &Path, json_path: &Path) -> Result<WorldFile> {
    let json_name = json_path.display().to_string();
    let text = std::fs::read_to_string(json_path)
        .map_err(|e| Error::io(format!("reading {json_name}"), e))?;
    let meta: WorldMeta = serde_json::from_str(&text)
        .map_err(|e| Error::content(&json_name, "(json)", e.to_string()))?;
    if meta.format != WORLD_FORMAT {
        return Err(Error::content(
            &json_name,
            "format",
            format!("expected `{WORLD_FORMAT}`, found `{}`", meta.format),
        ));
    }
    let (w, h, indices) = read_indexed_png(png_path)?;
    if (w, h) != (meta.width as u32, meta.height as u32) {
        return Err(Error::content(
            &json_name,
            "width/height",
            format!(
                "{}x{} does not match the PNG's {w}x{h}",
                meta.width, meta.height
            ),
        ));
    }
    Ok(WorldFile { meta, indices })
}

fn read_indexed_png(path: &Path) -> Result<(u32, u32, Vec<u8>)> {
    let name = path.display().to_string();
    let img_err = |msg: String| Error::Image {
        file: name.clone(),
        msg,
    };
    let file = File::open(path).map_err(|e| Error::io(format!("opening {name}"), e))?;
    let mut decoder = png::Decoder::new(BufReader::new(file));
    decoder.set_transformations(png::Transformations::IDENTITY);
    let mut reader = decoder.read_info().map_err(|e| img_err(e.to_string()))?;
    let info = reader.info();
    if info.color_type != png::ColorType::Indexed || info.bit_depth != png::BitDepth::Eight {
        return Err(img_err(format!(
            "must be an 8-bit indexed PNG, found {:?} {:?}",
            info.color_type, info.bit_depth
        )));
    }
    let mut buf = vec![
        0;
        reader
            .output_buffer_size()
            .ok_or_else(|| img_err("image too large".into()))?
    ];
    let frame = reader
        .next_frame(&mut buf)
        .map_err(|e| img_err(e.to_string()))?;
    buf.truncate(frame.buffer_size());
    Ok((frame.width, frame.height, buf))
}
