//! File locations. `PLASMON_CONFIG_DIR` overrides the platform default so tests
//! and the Python package agree on one place.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

pub fn config_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("PLASMON_CONFIG_DIR") {
        return PathBuf::from(dir);
    }
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("plasmon")
}

pub fn machine_key() -> PathBuf {
    config_dir().join("machine.key")
}

pub fn credentials() -> PathBuf {
    config_dir().join("credentials.toml")
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Credentials {
    pub server: String,
    pub user: String,
    pub token: String,
}

impl Credentials {
    pub fn load() -> Result<Option<Self>> {
        let path = credentials();
        if !path.exists() {
            return Ok(None);
        }
        let text = std::fs::read_to_string(&path)?;
        Ok(Some(toml::from_str(&text)?))
    }
}
