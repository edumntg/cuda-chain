//! Protocol primitives shared by the CLI and (later) the daemon.
//!
//! The Python package `plasmon.core` is the reference implementation. The test
//! vectors in `python/tests/vectors/v1.json` keep the two in step.

pub mod assignment;
pub mod canonical;
pub mod frame;
pub mod hashing;
pub mod identity;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("canonical json: {0}")]
    Canonical(String),
    #[error("identity: {0}")]
    Identity(String),
    #[error("frame: {0}")]
    Frame(String),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, Error>;
