//! Canonical JSON: sorted keys, no whitespace, UTF-8, no floats.

use crate::{Error, Result};
use serde_json::Value;
use std::fmt::Write;

pub fn dumps(value: &Value) -> Result<Vec<u8>> {
    let mut out = String::new();
    write_value(value, &mut out, "$")?;
    Ok(out.into_bytes())
}

fn write_value(value: &Value, out: &mut String, path: &str) -> Result<()> {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                write!(out, "{i}").unwrap();
            } else {
                return Err(Error::Canonical(format!(
                    "{path}: floats are not allowed in signed payloads"
                )));
            }
        }
        Value::String(s) => write_string(s, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_value(item, out, &format!("{path}[{i}]"))?;
            }
            out.push(']');
        }
        Value::Object(map) => {
            // serde_json::Map iterates in insertion order unless the
            // `preserve_order` feature is off, so sort explicitly.
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push('{');
            for (i, key) in keys.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_string(key, out);
                out.push(':');
                write_value(&map[*key], out, &format!("{path}.{key}"))?;
            }
            out.push('}');
        }
    }
    Ok(())
}

/// Matches Python's json.dumps(ensure_ascii=False): only `"`, `\` and control
/// characters are escaped, and control characters use \uXXXX except the short forms.
fn write_string(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => write!(out, "\\u{:04x}", c as u32).unwrap(),
            c => out.push(c),
        }
    }
    out.push('"');
}
