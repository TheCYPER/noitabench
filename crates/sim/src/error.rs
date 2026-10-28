//! Error type for the simulation crate.

use std::io;

/// Everything that can go wrong outside the simulation step itself.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// A content file (materials, reactions, world) is malformed.
    #[error("{file}: field `{field}`: {msg}")]
    Content {
        file: String,
        field: String,
        msg: String,
    },
    /// A caller passed a bad argument (unknown material key, out-of-range size, ...).
    #[error("{0}")]
    InvalidArgument(String),
    /// A snapshot blob is corrupt or does not belong to this world.
    #[error("snapshot: {0}")]
    Snapshot(String),
    /// File-system trouble while loading or recording.
    #[error("{context}: {source}")]
    Io {
        context: String,
        #[source]
        source: io::Error,
    },
    /// A PNG world file could not be decoded.
    #[error("{file}: {msg}")]
    Image { file: String, msg: String },
}

pub type Result<T> = std::result::Result<T, Error>;

impl Error {
    pub(crate) fn content(file: &str, field: impl Into<String>, msg: impl Into<String>) -> Self {
        Error::Content {
            file: file.to_string(),
            field: field.into(),
            msg: msg.into(),
        }
    }

    pub(crate) fn io(context: impl Into<String>, source: io::Error) -> Self {
        Error::Io {
            context: context.into(),
            source,
        }
    }

    pub(crate) fn arg(msg: impl Into<String>) -> Self {
        Error::InvalidArgument(msg.into())
    }
}
