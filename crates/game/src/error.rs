//! One error type for the crate (see `.trellis/spec/backend/error-handling.md`).

use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// A content file is malformed or inconsistent. `field` is a path such as
    /// `spells[3] (BULLET).mana`; it is empty for whole-file problems.
    #[error("{file}: {}{message}", field_prefix(.field))]
    Content {
        file: String,
        field: String,
        message: String,
    },
    #[error("reading {path}: {source}")]
    Io {
        path: PathBuf,
        source: std::io::Error,
    },
    /// A wand was built or edited with values the game does not allow.
    #[error("invalid wand: {0}")]
    Wand(String),
    /// A cast was requested while the wand is still in cast delay or recharge.
    #[error("the wand is not ready for another {remaining} frames")]
    NotReady { remaining: u32 },
    /// A caller passed a bad argument (unknown entity kind, position outside the world, ...).
    #[error("{0}")]
    Arg(String),
    /// A game snapshot is corrupt or belongs to other content.
    #[error("snapshot: {0}")]
    Snapshot(String),
    /// The pixel simulation reported an error.
    #[error(transparent)]
    Sim(#[from] cogbench_sim::Error),
    /// The recipes of a rule seed could not be drawn.
    #[error(transparent)]
    Rules(#[from] cogbench_rules::Error),
}

fn field_prefix(field: &str) -> String {
    if field.is_empty() {
        String::new()
    } else {
        format!("{field}: ")
    }
}

impl Error {
    pub fn arg(message: impl Into<String>) -> Self {
        Error::Arg(message.into())
    }

    pub fn content(file: &str, field: impl Into<String>, message: impl Into<String>) -> Self {
        Error::Content {
            file: file.to_string(),
            field: field.into(),
            message: message.into(),
        }
    }
}
