//! Network commands implemented natively: login, whoami, job list/status/watch/download,
//! fleet, server status, ledger verify.

use crate::api::Api;
use crate::paths::{self, Credentials};
use anyhow::{bail, Context, Result};
use serde_json::Value;
use std::io::Write;
use std::time::{Duration, Instant};

pub fn api(server_override: Option<&str>) -> Result<Api> {
    let creds = Credentials::load()?;
    let server = match (server_override, &creds) {
        (Some(s), _) => s.to_string(),
        (None, Some(c)) => c.server.clone(),
        (None, None) => bail!("not logged in. Run: plasmon login --server http://<host>:7117"),
    };
    let token = creds
        .filter(|c| c.server.trim_end_matches('/') == server.trim_end_matches('/'))
        .map(|c| c.token);
    if token.is_none() {
        bail!("not logged in to {server}. Run: plasmon login --server {server}");
    }
    Api::new(&server, token)
}

pub fn login(server: &str, no_browser: bool, json: bool) -> Result<()> {
    let api = Api::new(server, None)?;
    api.healthz()?;
    let host = hostname();
    let start = api.post(
        "/v1/auth/device",
        &serde_json::json!({"label": format!("cli on {host}")}),
    )?;
    let url = start["verification_uri_complete"]
        .as_str()
        .unwrap_or("")
        .to_string();
    let code = start["user_code"].as_str().unwrap_or("").to_string();
    eprintln!(
        "Open this address in a browser and confirm the code.\n\n  {url}\n\n  code: {code}\n"
    );
    if !no_browser {
        let _ = open::that(&url);
    }
    let interval = Duration::from_secs(start["interval"].as_u64().unwrap_or(3));
    let deadline =
        Instant::now() + Duration::from_secs(start["expires_in"].as_u64().unwrap_or(600));
    let device_code = start["device_code"].clone();
    while Instant::now() < deadline {
        std::thread::sleep(interval);
        let reply = api.post(
            "/v1/auth/device/token",
            &serde_json::json!({"device_code": device_code}),
        )?;
        if reply.get("status").and_then(Value::as_str) == Some("pending") {
            eprint!(".");
            let _ = std::io::stderr().flush();
            continue;
        }
        eprintln!();
        let creds = Credentials {
            server: server.trim_end_matches('/').to_string(),
            user: reply["user"]["email"].as_str().unwrap_or("").to_string(),
            token: reply["token"]
                .as_str()
                .context("no token in reply")?
                .to_string(),
        };
        creds.save()?;
        if json {
            println!(
                "{}",
                serde_json::json!({"server": creds.server, "user": reply["user"]})
            );
        } else {
            println!(
                "logged in to {} as {} ({})",
                creds.server,
                creds.user,
                reply["user"]["role"].as_str().unwrap_or("")
            );
        }
        return Ok(());
    }
    bail!("code expired; run login again")
}

pub fn logout() -> Result<()> {
    if let Some(c) = Credentials::load()? {
        if let Ok(api) = Api::new(&c.server, Some(c.token)) {
            let _ = api.post("/v1/auth/logout", &Value::Null);
        }
        let _ = std::fs::remove_file(paths::credentials());
    }
    println!("logged out");
    Ok(())
}

pub fn whoami(json: bool) -> Result<()> {
    let key_path = paths::machine_key();
    let node_id = key_path
        .exists()
        .then(|| plasmon_core::identity::Identity::load(&key_path).map(|i| i.node_id()))
        .transpose()?;
    let creds = Credentials::load()?;
    let role = match &creds {
        Some(c) => Api::new(&c.server, Some(c.token.clone()))?
            .get("/v1/auth/me")
            .ok()
            .and_then(|m| m["user"]["role"].as_str().map(str::to_string)),
        None => None,
    };
    if json {
        println!(
            "{}",
            serde_json::json!({"node_id": node_id, "server": creds.as_ref().map(|c| &c.server), "user": creds.as_ref().map(|c| &c.user), "role": role})
        );
        return Ok(());
    }
    match node_id {
        Some(id) => println!("node id: {id}"),
        None => println!("no machine key yet. Run: plasmon init"),
    }
    match creds {
        Some(c) => println!(
            "server:  {}\nuser:    {} ({})",
            c.server,
            c.user,
            role.unwrap_or_else(|| "unknown role".into())
        ),
        None => println!("not logged in. Run: plasmon login --server <url>"),
    }
    Ok(())
}

pub fn job_list(server: Option<&str>, all: bool, json: bool) -> Result<()> {
    let api = api(server)?;
    let jobs = api.get(if all { "/v1/jobs?all=true" } else { "/v1/jobs" })?;
    if json {
        println!("{}", serde_json::to_string_pretty(&jobs)?);
        return Ok(());
    }
    let rows: Vec<Vec<String>> = jobs
        .as_array()
        .map(|a| a.iter().map(job_row).collect())
        .unwrap_or_default();
    if rows.is_empty() {
        println!("no jobs");
    } else {
        print!(
            "{}",
            table(
                &["id", "name", "status", "round", "eval loss", "eval acc"],
                &rows
            )
        );
    }
    Ok(())
}

pub fn job_row(j: &Value) -> Vec<String> {
    vec![
        s(&j["id"]),
        s(&j["name"]),
        s(&j["status"]),
        format!("{}/{}", j["round"], j["total_rounds"]),
        j["eval_loss"]
            .as_f64()
            .map(|v| format!("{v:.3}"))
            .unwrap_or_default(),
        j["eval_acc"]
            .as_f64()
            .map(|v| format!("{:.1} %", v * 100.0))
            .unwrap_or_default(),
    ]
}

pub fn job_status(server: Option<&str>, id: &str, json: bool) -> Result<()> {
    let api = api(server)?;
    let job = api.get(&format!("/v1/jobs/{id}"))?;
    if json {
        println!("{}", serde_json::to_string_pretty(&job)?);
        return Ok(());
    }
    println!(
        "{} ({})  {}  round {}/{}  params {}",
        s(&job["name"]),
        s(&job["id"]),
        s(&job["status"]),
        job["round"],
        job["total_rounds"],
        job["param_count"]
    );
    let rows: Vec<Vec<String>> = job["rounds"]
        .as_array()
        .map(|a| a.iter().map(round_row).collect())
        .unwrap_or_default();
    print!(
        "{}",
        table(
            &[
                "round",
                "status",
                "trainers",
                "eval loss",
                "eval acc",
                "bytes in"
            ],
            &rows
        )
    );
    Ok(())
}

pub fn round_row(r: &Value) -> Vec<String> {
    vec![
        r["index"].to_string(),
        s(&r["status"]),
        r["accepted"].to_string(),
        r["eval_loss"]
            .as_f64()
            .map(|v| format!("{v:.4}"))
            .unwrap_or_default(),
        r["eval_acc"]
            .as_f64()
            .map(|v| format!("{:.1} %", v * 100.0))
            .unwrap_or_default(),
        r["bytes_in"]
            .as_u64()
            .map(|v| v.to_string())
            .unwrap_or_default(),
    ]
}

pub fn job_watch_plain(server: Option<&str>, id: &str, interval: f64) -> Result<i32> {
    let api = api(server)?;
    let mut seen: i64 = -1;
    loop {
        let job = api.get(&format!("/v1/jobs/{id}"))?;
        for r in job["rounds"].as_array().into_iter().flatten() {
            let idx = r["index"].as_i64().unwrap_or(0);
            if r["status"] == "closed" && idx > seen {
                seen = idx;
                println!(
                    "round {idx:>4}  trainers {:>3}  eval loss {:.4}  acc {:.1} %  {} B in",
                    r["accepted"],
                    r["eval_loss"].as_f64().unwrap_or(0.0),
                    r["eval_acc"].as_f64().unwrap_or(0.0) * 100.0,
                    r["bytes_in"]
                );
            }
        }
        if job["status"] != "running" {
            println!("job {}", s(&job["status"]));
            return Ok(if job["status"] == "completed" { 0 } else { 1 });
        }
        std::thread::sleep(Duration::from_secs_f64(interval));
    }
}

pub fn job_download(server: Option<&str>, id: &str, output: Option<&str>) -> Result<()> {
    let api = api(server)?;
    let job = api.get(&format!("/v1/jobs/{id}"))?;
    let theta = job["theta"].as_str().context("job has no weights yet")?;
    let bytes = api.get_bytes(&format!("/v1/blobs/{theta}"))?;
    if plasmon_core::hashing::digest(&bytes) != theta {
        bail!("downloaded blob does not match its id");
    }
    let path = output
        .map(str::to_string)
        .unwrap_or_else(|| format!("{}.safetensors", s(&job["name"])));
    std::fs::write(&path, &bytes)?;
    println!(
        "wrote {path} ({} bytes, weights after round {}, blob {}…)",
        bytes.len(),
        job["round"],
        &theta[..12]
    );
    Ok(())
}

pub fn job_cancel(server: Option<&str>, id: &str) -> Result<()> {
    let api = api(server)?;
    let job = api.post(&format!("/v1/jobs/{id}/cancel"), &Value::Null)?;
    println!("job {} {}", s(&job["id"]), s(&job["status"]));
    Ok(())
}

pub fn fleet_rows(machines: &Value) -> Vec<Vec<String>> {
    machines
        .as_array()
        .map(|a| {
            a.iter()
                .map(|m| {
                    let met = &m["metrics"];
                    let gpu = &m["hardware"]["gpu"];
                    let gpu_name = if gpu["kind"].as_str().unwrap_or("none") == "none" {
                        "none".to_string()
                    } else {
                        s(&gpu["name"])
                    };
                    let job = match (m["current_job_id"].as_str(), m["current_round"].as_i64()) {
                        (Some(j), Some(r)) => format!("{j} r{r}"),
                        (Some(j), None) => j.to_string(),
                        _ => String::new(),
                    };
                    vec![
                        s(&m["name"]),
                        s(&m["owner"]),
                        s(&m["status"]),
                        gpu_name,
                        num(&met["gpu_pct"]),
                        num(&met["cpu_pct"]),
                        num(&met["ram_pct"]),
                        job,
                        m["honesty"]
                            .as_f64()
                            .map(|v| format!("{v:.2}"))
                            .unwrap_or_default(),
                        ago(&m["last_seen_at"]),
                    ]
                })
                .collect()
        })
        .unwrap_or_default()
}

pub const FLEET_HEADERS: [&str; 10] = [
    "machine",
    "owner",
    "status",
    "gpu",
    "gpu%",
    "cpu%",
    "ram%",
    "job / round",
    "honesty",
    "seen",
];

pub fn fleet(server: Option<&str>, status: Option<&str>, json: bool) -> Result<()> {
    let api = api(server)?;
    let path = match status {
        Some(st) => format!("/v1/fleet?status={st}"),
        None => "/v1/fleet".to_string(),
    };
    let machines = api.get(&path)?;
    if json {
        println!("{}", serde_json::to_string_pretty(&machines)?);
        return Ok(());
    }
    let rows = fleet_rows(&machines);
    if rows.is_empty() {
        println!("no machines");
    } else {
        print!("{}", table(&FLEET_HEADERS, &rows));
    }
    Ok(())
}

pub fn server_status(server: Option<&str>, json: bool) -> Result<()> {
    let api = api(server)?;
    let st = api.get("/v1/server/status")?;
    if json {
        println!("{}", serde_json::to_string_pretty(&st)?);
        return Ok(());
    }
    println!(
        "version {}  mode {}  uptime {} s\ndb {} ({} ms)\nblobs {} B at {}\nscheduler running: {}  sse clients: {}\nledger entries {}  head {}…\nusers {}  machines {}  jobs {} ({} running)",
        s(&st["version"]), s(&st["mode"]), st["uptime_s"], s(&st["db"]["url"]), st["db"]["ping_ms"], st["blobs"]["bytes"], s(&st["blobs"]["path"]),
        st["scheduler"]["running"], st["sse_clients"], st["ledger"]["entries"], &s(&st["ledger"]["head"])[..16.min(s(&st["ledger"]["head"]).len())],
        st["counts"]["users"], st["counts"]["machines"], st["counts"]["jobs"], st["counts"]["jobs_running"]
    );
    Ok(())
}

pub fn ledger_verify(server: Option<&str>, json: bool) -> Result<i32> {
    let api = api(server)?;
    let out = api.get("/v1/ledger/verify")?;
    if json {
        println!("{}", serde_json::to_string_pretty(&out)?);
    } else {
        println!(
            "ledger ok: {}  entries: {}{}",
            out["ok"],
            out["entries"],
            out["problem"]
                .as_str()
                .filter(|p| !p.is_empty())
                .map(|p| format!("  problem: {p}"))
                .unwrap_or_default()
        );
    }
    Ok(if out["ok"] == true { 0 } else { 1 })
}

// ----- formatting helpers ---------------------------------------------------------

pub fn s(v: &Value) -> String {
    match v {
        Value::String(x) => x.clone(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

pub fn num(v: &Value) -> String {
    match v {
        Value::Number(n) => n
            .as_f64()
            .map(|f| {
                if f.fract() == 0.0 {
                    format!("{f:.0}")
                } else {
                    format!("{f:.1}")
                }
            })
            .unwrap_or_default(),
        _ => String::new(),
    }
}

pub fn ago(v: &Value) -> String {
    let Some(text) = v.as_str() else {
        return "never".into();
    };
    let parsed =
        chrono::NaiveDateTime::parse_from_str(&text[..19.min(text.len())], "%Y-%m-%dT%H:%M:%S");
    match parsed {
        Ok(t) => {
            let secs = (chrono::Utc::now().naive_utc() - t).num_seconds().max(0);
            if secs < 60 {
                format!("{secs} s")
            } else if secs < 3600 {
                format!("{} min", secs / 60)
            } else if secs < 86400 {
                format!("{} h", secs / 3600)
            } else {
                format!("{} d", secs / 86400)
            }
        }
        Err(_) => text.to_string(),
    }
}

pub fn table(headers: &[&str], rows: &[Vec<String>]) -> String {
    let mut widths: Vec<usize> = headers.iter().map(|h| h.chars().count()).collect();
    for r in rows {
        for (i, c) in r.iter().enumerate() {
            widths[i] = widths[i].max(c.chars().count());
        }
    }
    let line = |cells: Vec<String>| {
        cells
            .iter()
            .enumerate()
            .map(|(i, c)| format!("{:<w$}", c, w = widths[i]))
            .collect::<Vec<_>>()
            .join("  ")
            .trim_end()
            .to_string()
            + "\n"
    };
    let mut out = line(headers.iter().map(|h| h.to_string()).collect());
    for r in rows {
        out += &line(r.clone());
    }
    out
}

pub fn hostname() -> String {
    std::env::var("HOSTNAME")
        .ok()
        .or_else(|| std::env::var("COMPUTERNAME").ok())
        .unwrap_or_else(|| "machine".into())
}
