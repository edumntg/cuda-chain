//! Delegation to the Python engine for the steps that need PyTorch.
//! `PLASMON_PYTHON` wins; otherwise the first interpreter on PATH that imports `plasmon`.

use anyhow::{bail, Result};
use std::process::{Command, Stdio};

pub fn find_python() -> Result<String> {
    if let Ok(p) = std::env::var("PLASMON_PYTHON") {
        return Ok(p);
    }
    let candidates: &[&[&str]] = &[&["python3"], &["python"], &["py", "-3"]];
    for c in candidates {
        let ok = Command::new(c[0])
            .args(&c[1..])
            .args(["-c", "import plasmon"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
        if ok {
            return Ok(c.join(" "));
        }
    }
    bail!(
        "the plasmon Python package was not found. Install it with:\n  python -m pip install \"plasmon[engine] @ git+https://github.com/edumntg/plasmon.git\"\nor set PLASMON_PYTHON to an interpreter that has it."
    )
}

/// Runs `python -m plasmon <args>` with inherited stdio and returns its exit code.
pub fn run(args: &[String]) -> Result<i32> {
    let python = find_python()?;
    let mut parts = python.split_whitespace();
    let exe = parts.next().unwrap();
    let status = Command::new(exe)
        .args(parts)
        .args(["-m", "plasmon"])
        .args(args)
        .status()?;
    Ok(status.code().unwrap_or(1))
}
