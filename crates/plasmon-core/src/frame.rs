//! Header parsing for Δ frames. The CLI only needs the header; the trainer
//! and coordinator (Python) read the tensors.

use crate::{Error, Result};
use serde::Deserialize;

pub const MAGIC: &[u8; 4] = b"PLSM";
pub const VERSION: u8 = 1;
const PREFIX_LEN: usize = 4 + 1 + 1 + 2 + 8;

#[derive(Debug, Deserialize)]
pub struct TensorHeader {
    pub name: String,
    pub shape: Vec<u64>,
    pub numel: u64,
    pub val_offset: u64,
    pub val_len: u64,
    pub idx_offset: Option<u64>,
    pub idx_len: Option<u64>,
}

#[derive(Debug, Deserialize)]
pub struct FrameHeader {
    pub job: String,
    pub round: u64,
    pub node: String,
    pub theta: String,
    pub samples: u64,
    #[serde(default)]
    pub meta: serde_json::Value,
    pub tensors: Vec<TensorHeader>,
}

pub struct Parsed {
    pub kind: u8,
    pub header: FrameHeader,
    pub payload_len: usize,
}

pub fn parse_header(data: &[u8]) -> Result<Parsed> {
    if data.len() < PREFIX_LEN {
        return Err(Error::Frame("frame too short".into()));
    }
    if &data[..4] != MAGIC {
        return Err(Error::Frame("bad magic".into()));
    }
    if data[4] != VERSION {
        return Err(Error::Frame(format!(
            "unsupported frame version {}",
            data[4]
        )));
    }
    let kind = data[5];
    let header_len = u64::from_le_bytes(data[8..16].try_into().unwrap()) as usize;
    let end = PREFIX_LEN + header_len;
    if end > data.len() {
        return Err(Error::Frame("header length exceeds frame".into()));
    }
    let header: FrameHeader = serde_json::from_slice(&data[PREFIX_LEN..end])?;
    Ok(Parsed {
        kind,
        header,
        payload_len: data.len() - end,
    })
}
