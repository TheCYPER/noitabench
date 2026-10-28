//! Snapshots of the whole game: the pixel world (the simulation's own snapshot) and everything
//! else as JSON (`serde_json` with `float_roundtrip`, so every float comes back bit for bit).
//!
//! Layout: magic `CGBGAME1`, `u32` length of the world blob, the world blob, the entity state.

use crate::error::Error;
use crate::rng::HashRng;

use super::{Game, State};

const MAGIC: &[u8; 8] = b"CGBGAME1";

impl Game {
    pub fn snapshot(&self) -> Result<Vec<u8>, Error> {
        let world = self.world.snapshot()?;
        let state = serde_json::to_vec(&self.state).map_err(|e| Error::Snapshot(e.to_string()))?;
        let mut out = Vec::with_capacity(12 + world.len() + state.len());
        out.extend_from_slice(MAGIC);
        out.extend_from_slice(&(world.len() as u32).to_le_bytes());
        out.extend_from_slice(&world);
        out.extend_from_slice(&state);
        Ok(out)
    }

    /// Replace the whole game with a snapshot of the same content. On an error the game is left
    /// as it was. Not allowed while recording (frame numbers in a recording never go back).
    pub fn restore(&mut self, blob: &[u8]) -> Result<(), Error> {
        let bad = |m: &str| Error::Snapshot(m.to_string());
        if self.recorder.is_some() {
            return Err(bad("a recording is running: stop it before restoring"));
        }
        let head = blob.get(..12).ok_or_else(|| bad("truncated"))?;
        if &head[..8] != MAGIC {
            return Err(bad("not a game snapshot (bad magic)"));
        }
        let len = u32::from_le_bytes([head[8], head[9], head[10], head[11]]) as usize;
        let end = 12usize.checked_add(len).ok_or_else(|| bad("bad length"))?;
        let world = blob.get(12..end).ok_or_else(|| bad("truncated world"))?;
        let state: State =
            serde_json::from_slice(&blob[end..]).map_err(|e| Error::Snapshot(e.to_string()))?;
        self.world.restore(world)?;
        self.state = state;
        self.ai = HashRng::stream(self.world.seed(), "ai");
        Ok(())
    }
}
