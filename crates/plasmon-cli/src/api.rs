//! Blocking HTTP client for the coordinator. Commands stay synchronous: no async
//! runtime starts before a network call.

use anyhow::{anyhow, bail, Context, Result};
use serde_json::Value;
use std::time::Duration;

pub struct Api {
    base: String,
    token: Option<String>,
    http: reqwest::blocking::Client,
}

impl Api {
    pub fn new(server: &str, token: Option<String>) -> Result<Self> {
        let http = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(60))
            .user_agent(concat!("plasmon/", env!("CARGO_PKG_VERSION")))
            .build()?;
        Ok(Self {
            base: server.trim_end_matches('/').to_string(),
            token,
            http,
        })
    }

    pub fn base(&self) -> &str {
        &self.base
    }

    fn send(&self, req: reqwest::blocking::RequestBuilder) -> Result<Value> {
        let req = match &self.token {
            Some(t) => req.bearer_auth(t),
            None => req,
        };
        let resp = req.send().context("request failed")?;
        let status = resp.status();
        if status.as_u16() == 428 {
            return Ok(serde_json::json!({"status": "pending"}));
        }
        let body: Value = resp.json().unwrap_or(Value::Null);
        if !status.is_success() {
            let detail = body
                .get("detail")
                .map(|d| {
                    d.as_str()
                        .map(str::to_string)
                        .unwrap_or_else(|| d.to_string())
                })
                .unwrap_or_else(|| status.to_string());
            if status.as_u16() == 401 {
                bail!("{detail}. Run: plasmon login --server {}", self.base);
            }
            bail!("{detail}");
        }
        Ok(body)
    }

    pub fn get(&self, path: &str) -> Result<Value> {
        self.send(self.http.get(format!("{}{}", self.base, path)))
    }

    pub fn post(&self, path: &str, body: &Value) -> Result<Value> {
        self.send(self.http.post(format!("{}{}", self.base, path)).json(body))
    }

    pub fn get_bytes(&self, path: &str) -> Result<Vec<u8>> {
        let mut req = self.http.get(format!("{}{}", self.base, path));
        if let Some(t) = &self.token {
            req = req.bearer_auth(t);
        }
        let resp = req.send()?;
        if !resp.status().is_success() {
            bail!("{} for {}", resp.status(), path);
        }
        Ok(resp.bytes()?.to_vec())
    }

    pub fn healthz(&self) -> Result<Value> {
        self.get("/v1/healthz")
            .map_err(|e| anyhow!("cannot reach {}: {e}", self.base))
    }
}
