//! Terminal views: the start-up screen with its animation, and `--watch` tables.
//! Colours follow DESIGN.md: one accent, a semantic status scale.

use crate::api::Api;
use crate::commands::{fleet_rows, job_row, round_row, FLEET_HEADERS};
use anyhow::Result;
use crossterm::event::{self, Event, KeyCode, KeyEventKind};
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use crossterm::ExecutableCommand;
use ratatui::prelude::*;
use ratatui::widgets::{Block, Borders, Cell, Gauge, Paragraph, Row, Sparkline, Table};
use serde_json::Value;
use std::io::{stdout, IsTerminal};
use std::time::{Duration, Instant};

pub const LOGO: [&str; 6] = [
    "██████╗ ██╗      █████╗ ███████╗███╗   ███╗ ██████╗ ███╗   ██╗",
    "██╔══██╗██║     ██╔══██╗██╔════╝████╗ ████║██╔═══██╗████╗  ██║",
    "██████╔╝██║     ███████║███████╗██╔████╔██║██║   ██║██╔██╗ ██║",
    "██╔═══╝ ██║     ██╔══██║╚════██║██║╚██╔╝██║██║   ██║██║╚██╗██║",
    "██║     ███████╗██║  ██║███████║██║ ╚═╝ ██║╚██████╔╝██║ ╚████║",
    "╚═╝     ╚══════╝╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝",
];

const ACCENT: Color = Color::Rgb(94, 234, 212);
const MUTED: Color = Color::Rgb(163, 167, 173);

pub fn animation_enabled() -> bool {
    stdout().is_terminal()
        && std::env::var_os("NO_COLOR").is_none()
        && std::env::var_os("PLASMON_NO_ANIM").is_none()
}

pub fn status_color(status: &str) -> Color {
    match status {
        "training" => Color::Rgb(74, 222, 128),
        "idle" => Color::Rgb(147, 197, 253),
        "paused" => Color::Rgb(250, 204, 21),
        "unavailable" => MUTED,
        "offline" => Color::Rgb(248, 113, 113),
        "error" => Color::Rgb(232, 121, 249),
        _ => Color::Reset,
    }
}

struct Term {
    terminal: Terminal<CrosstermBackend<std::io::Stdout>>,
}

impl Term {
    fn enter() -> Result<Self> {
        enable_raw_mode()?;
        stdout().execute(EnterAlternateScreen)?;
        let terminal = Terminal::new(CrosstermBackend::new(stdout()))?;
        Ok(Self { terminal })
    }
}

impl Drop for Term {
    fn drop(&mut self) {
        let _ = disable_raw_mode();
        let _ = stdout().execute(LeaveAlternateScreen);
    }
}

/// One second of scattered dots that lock into a wave, then the wordmark. Any key skips.
fn intro(term: &mut Term) -> Result<()> {
    let start = Instant::now();
    let total = Duration::from_millis(1100);
    while start.elapsed() < total {
        let t = start.elapsed().as_secs_f64() / total.as_secs_f64();
        term.terminal.draw(|f| {
            let area = f.area();
            let width = area.width.max(1) as usize;
            let mut lines: Vec<Line> = Vec::new();
            let wave_rows = 5usize;
            let mut grid = vec![vec![' '; width]; wave_rows];
            #[allow(clippy::needless_range_loop)]
            for x in 0..width {
                let phase = x as f64 / 6.0;
                let wave_y = ((phase - t * 6.0).sin() * 0.5 + 0.5) * (wave_rows - 1) as f64;
                // Early frames add noise; the noise fades as t grows (dots lock into the wave).
                let noise =
                    (((x * 7919) % 13) as f64 / 13.0 - 0.5) * (1.0 - t) * (wave_rows as f64);
                let y = (wave_y + noise).round().clamp(0.0, (wave_rows - 1) as f64) as usize;
                grid[y][x] = if t > 0.6 { '●' } else { '·' };
            }
            for row in grid {
                lines.push(Line::from(Span::styled(
                    row.into_iter().collect::<String>(),
                    Style::default().fg(ACCENT),
                )));
            }
            lines.push(Line::from(""));
            let revealed = ((t - 0.5).max(0.0) / 0.5 * LOGO[0].chars().count() as f64) as usize;
            for l in LOGO {
                let shown: String = l.chars().take(revealed).collect();
                lines.push(Line::from(Span::styled(
                    format!("  {shown}"),
                    Style::default().fg(ACCENT),
                )));
            }
            f.render_widget(Paragraph::new(lines), area);
        })?;
        if event::poll(Duration::from_millis(33))? {
            if let Event::Key(_) = event::read()? {
                break;
            }
        }
    }
    Ok(())
}

pub struct Home {
    pub me: Value,
    pub jobs: Value,
    pub summary: Value,
}

pub fn fetch_home(api: &Api) -> Result<Home> {
    Ok(Home {
        me: api.get("/v1/auth/me")?,
        jobs: api.get("/v1/jobs")?,
        summary: api.get("/v1/fleet/summary")?,
    })
}

/// The bare `plasmon` command: intro, then one status screen until a key is pressed.
pub fn home(api: &Api, animate: bool) -> Result<()> {
    let mut term = Term::enter()?;
    if animate {
        intro(&mut term)?;
    }
    let home = fetch_home(api)?;
    loop {
        term.terminal.draw(|f| draw_home(f, &home, api.base()))?;
        if event::poll(Duration::from_millis(250))? {
            if let Event::Key(k) = event::read()? {
                if k.kind == KeyEventKind::Press
                    && matches!(k.code, KeyCode::Char('q') | KeyCode::Esc | KeyCode::Enter)
                {
                    break;
                }
            }
        }
    }
    Ok(())
}

fn draw_home(f: &mut Frame, home: &Home, server: &str) {
    let chunks = Layout::vertical([
        Constraint::Length(8),
        Constraint::Length(2),
        Constraint::Min(5),
        Constraint::Length(1),
    ])
    .split(f.area());
    let mut logo: Vec<Line> = LOGO
        .iter()
        .map(|l| Line::from(Span::styled(format!("  {l}"), Style::default().fg(ACCENT))))
        .collect();
    logo.push(Line::from(Span::styled(
        "  thousands of GPUs, one wave",
        Style::default().fg(MUTED),
    )));
    f.render_widget(Paragraph::new(logo), chunks[0]);
    let user = home.me["user"]["email"].as_str().unwrap_or("?");
    let role = home.me["user"]["role"].as_str().unwrap_or("");
    let s = &home.summary;
    let status = Line::from(vec![
        Span::styled("  ◆ ", Style::default().fg(ACCENT)),
        Span::raw(format!("{user} ({role})")),
        Span::styled("    ◆ ", Style::default().fg(ACCENT)),
        Span::raw(format!(
            "{} of {} machines online",
            s["online"], s["machines"]
        )),
        Span::styled("    ◆ ", Style::default().fg(ACCENT)),
        Span::raw(format!("{} jobs running", s["jobs_running"])),
        Span::styled("    ◆ ", Style::default().fg(ACCENT)),
        Span::styled(server.to_string(), Style::default().fg(MUTED)),
    ]);
    f.render_widget(Paragraph::new(status), chunks[1]);
    let rows: Vec<Row> = home
        .jobs
        .as_array()
        .into_iter()
        .flatten()
        .map(|j| Row::new(job_row(j).into_iter().map(Cell::from)))
        .collect();
    let table = Table::new(
        rows,
        [
            Constraint::Length(18),
            Constraint::Min(16),
            Constraint::Length(10),
            Constraint::Length(8),
            Constraint::Length(10),
            Constraint::Length(9),
        ],
    )
    .header(
        Row::new(["job", "name", "state", "round", "eval loss", "eval acc"])
            .style(Style::default().fg(MUTED)),
    )
    .block(
        Block::default()
            .borders(Borders::TOP)
            .title(" your jobs ")
            .border_style(Style::default().fg(MUTED)),
    );
    f.render_widget(table, chunks[2]);
    f.render_widget(Paragraph::new(Span::styled("  q quit   ·   plasmon job watch <id>   ·   plasmon fleet --watch   ·   plasmon trainer start", Style::default().fg(MUTED))), chunks[3]);
}

/// `plasmon fleet --watch`: the fleet table, refreshed every two seconds.
pub fn fleet_watch(api: &Api, interval: Duration) -> Result<()> {
    let mut term = Term::enter()?;
    let mut last = Instant::now() - interval;
    let mut machines = Value::Array(vec![]);
    let mut summary = Value::Null;
    let mut error: Option<String> = None;
    loop {
        if last.elapsed() >= interval {
            match (api.get("/v1/fleet"), api.get("/v1/fleet/summary")) {
                (Ok(m), Ok(s)) => {
                    machines = m;
                    summary = s;
                    error = None;
                }
                (Err(e), _) | (_, Err(e)) => error = Some(e.to_string()),
            }
            last = Instant::now();
        }
        term.terminal.draw(|f| {
            let chunks = Layout::vertical([
                Constraint::Length(2),
                Constraint::Min(3),
                Constraint::Length(1),
            ])
            .split(f.area());
            let by = &summary["by_status"];
            let head = Line::from(vec![
                Span::styled(
                    "FLEET ",
                    Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
                ),
                Span::raw(format!("online {}  ", summary["online"])),
                Span::styled(
                    format!("training {}  ", by["training"].as_u64().unwrap_or(0)),
                    Style::default().fg(status_color("training")),
                ),
                Span::styled(
                    format!("idle {}  ", by["idle"].as_u64().unwrap_or(0)),
                    Style::default().fg(status_color("idle")),
                ),
                Span::styled(
                    format!("paused {}  ", by["paused"].as_u64().unwrap_or(0)),
                    Style::default().fg(status_color("paused")),
                ),
                Span::styled(
                    format!("offline {}  ", by["offline"].as_u64().unwrap_or(0)),
                    Style::default().fg(status_color("offline")),
                ),
                Span::styled(
                    format!("error {}", by["error"].as_u64().unwrap_or(0)),
                    Style::default().fg(status_color("error")),
                ),
                Span::styled(
                    format!(
                        "    rounds/h {}    ↻ {} s",
                        summary["rounds_last_hour"],
                        interval.as_secs()
                    ),
                    Style::default().fg(MUTED),
                ),
            ]);
            f.render_widget(Paragraph::new(head), chunks[0]);
            let rows: Vec<Row> = fleet_rows(&machines)
                .into_iter()
                .map(|r| {
                    let color = status_color(&r[2]);
                    Row::new(r.into_iter().enumerate().map(|(i, c)| {
                        if i == 2 {
                            Cell::from(format!("● {c}")).style(Style::default().fg(color))
                        } else {
                            Cell::from(c)
                        }
                    }))
                })
                .collect();
            let widths = [
                Constraint::Length(16),
                Constraint::Length(18),
                Constraint::Length(13),
                Constraint::Length(18),
                Constraint::Length(5),
                Constraint::Length(5),
                Constraint::Length(5),
                Constraint::Min(16),
                Constraint::Length(7),
                Constraint::Length(6),
            ];
            let table = Table::new(rows, widths)
                .header(Row::new(FLEET_HEADERS).style(Style::default().fg(MUTED)));
            f.render_widget(table, chunks[1]);
            let foot = match &error {
                Some(e) => Span::styled(
                    format!("  {e}"),
                    Style::default().fg(status_color("offline")),
                ),
                None => Span::styled("  q quit", Style::default().fg(MUTED)),
            };
            f.render_widget(Paragraph::new(foot), chunks[2]);
        })?;
        if poll_quit(Duration::from_millis(250))? {
            break;
        }
    }
    Ok(())
}

/// `plasmon job watch <id>`: loss sparkline, rounds and trainers, live.
pub fn job_watch(api: &Api, id: &str, interval: Duration) -> Result<()> {
    let mut term = Term::enter()?;
    let mut last = Instant::now() - interval;
    let mut job = Value::Null;
    let mut updates = Value::Array(vec![]);
    let mut error: Option<String> = None;
    loop {
        if last.elapsed() >= interval {
            match api.get(&format!("/v1/jobs/{id}")) {
                Ok(j) => {
                    job = j;
                    error = None;
                }
                Err(e) => error = Some(e.to_string()),
            }
            if let Ok(u) = api.get(&format!("/v1/jobs/{id}/updates")) {
                updates = u;
            }
            last = Instant::now();
        }
        term.terminal.draw(|f| {
            let chunks = Layout::vertical([
                Constraint::Length(2),
                Constraint::Length(6),
                Constraint::Percentage(45),
                Constraint::Min(3),
                Constraint::Length(1),
            ])
            .split(f.area());
            let title = Line::from(vec![
                Span::styled(
                    format!("{} ", job["name"].as_str().unwrap_or(id)),
                    Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
                ),
                Span::raw(format!(
                    "{}  round {}/{}  eval loss {}  acc {}",
                    job["status"].as_str().unwrap_or(""),
                    job["round"],
                    job["total_rounds"],
                    job["eval_loss"]
                        .as_f64()
                        .map(|v| format!("{v:.4}"))
                        .unwrap_or_default(),
                    job["eval_acc"]
                        .as_f64()
                        .map(|v| format!("{:.1} %", v * 100.0))
                        .unwrap_or_default()
                )),
            ]);
            f.render_widget(Paragraph::new(title), chunks[0]);
            let losses: Vec<u64> = job["rounds"]
                .as_array()
                .into_iter()
                .flatten()
                .filter(|r| r["status"] == "closed")
                .filter_map(|r| r["eval_loss"].as_f64())
                .map(|v| (v * 1000.0) as u64)
                .collect();
            let spark = Sparkline::default()
                .data(&losses)
                .style(Style::default().fg(ACCENT))
                .block(
                    Block::default()
                        .borders(Borders::TOP)
                        .title(" eval loss per round ")
                        .border_style(Style::default().fg(MUTED)),
                );
            f.render_widget(spark, chunks[1]);
            let rows: Vec<Row> = job["rounds"]
                .as_array()
                .into_iter()
                .flatten()
                .rev()
                .map(|r| Row::new(round_row(r).into_iter().map(Cell::from)))
                .collect();
            let table = Table::new(
                rows,
                [
                    Constraint::Length(6),
                    Constraint::Length(12),
                    Constraint::Length(9),
                    Constraint::Length(10),
                    Constraint::Length(9),
                    Constraint::Min(10),
                ],
            )
            .header(
                Row::new([
                    "round",
                    "status",
                    "trainers",
                    "eval loss",
                    "eval acc",
                    "bytes in",
                ])
                .style(Style::default().fg(MUTED)),
            )
            .block(
                Block::default()
                    .borders(Borders::TOP)
                    .title(" rounds ")
                    .border_style(Style::default().fg(MUTED)),
            );
            f.render_widget(table, chunks[2]);
            let urows: Vec<Row> = updates
                .as_array()
                .into_iter()
                .flatten()
                .take(40)
                .map(|u| {
                    Row::new(vec![
                        u["round"].to_string(),
                        u["machine"].as_str().unwrap_or("").to_string(),
                        u["shard"].to_string(),
                        u["status"].as_str().unwrap_or("").to_string(),
                        u["samples"].to_string(),
                        u["loss_end"]
                            .as_f64()
                            .map(|v| format!("{v:.3}"))
                            .unwrap_or_default(),
                        u["frame_bytes"].to_string(),
                    ])
                })
                .collect();
            let utable = Table::new(
                urows,
                [
                    Constraint::Length(6),
                    Constraint::Length(18),
                    Constraint::Length(6),
                    Constraint::Length(10),
                    Constraint::Length(8),
                    Constraint::Length(9),
                    Constraint::Min(8),
                ],
            )
            .header(
                Row::new([
                    "round", "machine", "shard", "status", "samples", "loss end", "bytes",
                ])
                .style(Style::default().fg(MUTED)),
            )
            .block(
                Block::default()
                    .borders(Borders::TOP)
                    .title(" trainers ")
                    .border_style(Style::default().fg(MUTED)),
            );
            f.render_widget(utable, chunks[3]);
            let foot = match &error {
                Some(e) => Span::styled(
                    format!("  {e}"),
                    Style::default().fg(status_color("offline")),
                ),
                None => Span::styled(
                    format!("  q quit   ↻ {} s", interval.as_secs()),
                    Style::default().fg(MUTED),
                ),
            };
            f.render_widget(Paragraph::new(foot), chunks[4]);
        })?;
        if poll_quit(Duration::from_millis(250))? {
            break;
        }
    }
    Ok(())
}

fn poll_quit(timeout: Duration) -> Result<bool> {
    if event::poll(timeout)? {
        if let Event::Key(k) = event::read()? {
            if k.kind == KeyEventKind::Press && matches!(k.code, KeyCode::Char('q') | KeyCode::Esc)
            {
                return Ok(true);
            }
        }
    }
    Ok(false)
}

/// `plasmon fleet show <node> --watch`: one machine, live.
pub fn machine_watch(api: &Api, node: &str, interval: Duration) -> Result<()> {
    let mut term = Term::enter()?;
    let mut last = Instant::now() - interval;
    let mut m = Value::Null;
    let mut logs = Value::Array(vec![]);
    let mut error: Option<String> = None;
    loop {
        if last.elapsed() >= interval {
            match api.get(&format!("/v1/fleet/{node}")) {
                Ok(v) => {
                    m = v;
                    error = None;
                }
                Err(e) => error = Some(e.to_string()),
            }
            if let Ok(l) = api.get(&format!("/v1/fleet/{node}/logs?limit=30")) {
                logs = l;
            }
            last = Instant::now();
        }
        term.terminal.draw(|f| {
            let chunks = Layout::vertical([
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Length(4),
                Constraint::Min(5),
                Constraint::Length(1),
            ])
            .split(f.area());
            let status = m["status"].as_str().unwrap_or("");
            let head = Line::from(vec![
                Span::styled(
                    format!("{} ", m["name"].as_str().unwrap_or(node)),
                    Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
                ),
                Span::styled(
                    format!("● {status} "),
                    Style::default().fg(status_color(status)),
                ),
                Span::raw(m["status_detail"].as_str().unwrap_or("").to_string()),
                Span::styled(
                    format!(
                        "   job {} round {}   seen {} ago",
                        crate::commands::s(&m["current_job_id"]),
                        crate::commands::s(&m["current_round"]),
                        crate::commands::ago(&m["last_seen_at"])
                    ),
                    Style::default().fg(MUTED),
                ),
            ]);
            f.render_widget(
                Paragraph::new(vec![
                    head,
                    Line::from(Span::styled(
                        format!(
                            "owner {}   rounds served {}   samples verified {}   honesty {}",
                            crate::commands::s(&m["owner"]),
                            m["rounds_served"],
                            m["samples_verified"],
                            m["honesty"]
                        ),
                        Style::default().fg(MUTED),
                    )),
                ]),
                chunks[0],
            );
            let met = &m["metrics"];
            let cols = Layout::horizontal([
                Constraint::Percentage(33),
                Constraint::Percentage(33),
                Constraint::Percentage(34),
            ])
            .split(chunks[1]);
            for (i, (label, key)) in [("cpu", "cpu_pct"), ("ram", "ram_pct"), ("gpu", "gpu_pct")]
                .iter()
                .enumerate()
            {
                let pct = met[*key].as_f64().unwrap_or(0.0).clamp(0.0, 100.0);
                let g = Gauge::default()
                    .block(
                        Block::default()
                            .title(format!(" {label} "))
                            .borders(Borders::ALL)
                            .border_style(Style::default().fg(MUTED)),
                    )
                    .gauge_style(Style::default().fg(ACCENT))
                    .percent(pct as u16);
                f.render_widget(g, cols[i]);
            }
            let hist: Vec<u64> = m["history"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|h| h["metrics"]["cpu_pct"].as_f64())
                .map(|v| v as u64)
                .collect();
            let spark = Sparkline::default()
                .data(&hist)
                .style(Style::default().fg(MUTED))
                .block(
                    Block::default()
                        .borders(Borders::TOP)
                        .title(" cpu, last hour ")
                        .border_style(Style::default().fg(MUTED)),
                );
            f.render_widget(spark, chunks[2]);
            let lines: Vec<Line> = logs
                .as_array()
                .into_iter()
                .flatten()
                .map(|l| {
                    let at = crate::commands::s(&l["at"]);
                    Line::from(vec![
                        Span::styled(
                            format!("{} ", at.get(11..19).unwrap_or(&at)),
                            Style::default().fg(MUTED),
                        ),
                        Span::raw(crate::commands::s(&l["message"])),
                    ])
                })
                .collect();
            f.render_widget(
                Paragraph::new(lines).block(
                    Block::default()
                        .borders(Borders::TOP)
                        .title(" log ")
                        .border_style(Style::default().fg(MUTED)),
                ),
                chunks[3],
            );
            let foot = match &error {
                Some(e) => Span::styled(
                    format!("  {e}"),
                    Style::default().fg(status_color("offline")),
                ),
                None => Span::styled(
                    format!("  q quit   ↻ {} s", interval.as_secs()),
                    Style::default().fg(MUTED),
                ),
            };
            f.render_widget(Paragraph::new(foot), chunks[4]);
        })?;
        if poll_quit(Duration::from_millis(250))? {
            break;
        }
    }
    Ok(())
}

/// `plasmon server status --watch`.
pub fn server_watch(api: &Api, interval: Duration) -> Result<()> {
    let mut term = Term::enter()?;
    let mut last = Instant::now() - interval;
    let mut st = Value::Null;
    let mut error: Option<String> = None;
    loop {
        if last.elapsed() >= interval {
            match api.get("/v1/server/status") {
                Ok(v) => {
                    st = v;
                    error = None;
                }
                Err(e) => error = Some(e.to_string()),
            }
            last = Instant::now();
        }
        term.terminal.draw(|f| {
            let chunks = Layout::vertical([
                Constraint::Length(8),
                Constraint::Min(3),
                Constraint::Length(1),
            ])
            .split(f.area());
            let running = st["scheduler"]["running"] == true;
            let lines = vec![
                Line::from(vec![
                    Span::styled(
                        "SERVER ",
                        Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
                    ),
                    Span::raw(format!(
                        "version {}  mode {}  uptime {} s",
                        crate::commands::s(&st["version"]),
                        crate::commands::s(&st["mode"]),
                        st["uptime_s"]
                    )),
                ]),
                Line::from(vec![
                    Span::raw("scheduler "),
                    Span::styled(
                        if running {
                            "● running"
                        } else {
                            "✖ stopped"
                        },
                        Style::default().fg(status_color(if running {
                            "training"
                        } else {
                            "error"
                        })),
                    ),
                ]),
                Line::from(format!(
                    "db {} ({} ms)",
                    crate::commands::s(&st["db"]["url"]),
                    st["db"]["ping_ms"]
                )),
                Line::from(format!(
                    "blobs {} B at {}",
                    st["blobs"]["bytes"],
                    crate::commands::s(&st["blobs"]["path"])
                )),
                Line::from(format!(
                    "ledger entries {}  head {}…",
                    st["ledger"]["entries"],
                    crate::commands::s(&st["ledger"]["head"])
                        .chars()
                        .take(16)
                        .collect::<String>()
                )),
                Line::from(format!(
                    "users {}  machines {}  jobs {} ({} running)  sse clients {}",
                    st["counts"]["users"],
                    st["counts"]["machines"],
                    st["counts"]["jobs"],
                    st["counts"]["jobs_running"],
                    st["sse_clients"]
                )),
            ];
            f.render_widget(Paragraph::new(lines), chunks[0]);
            let rows: Vec<Row> = st["round_timings"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|t| {
                    Row::new(vec![
                        crate::commands::s(&t["job"]),
                        t["round"].to_string(),
                        t["aggregate_s"].to_string(),
                        t["eval_s"].to_string(),
                    ])
                })
                .collect();
            let table = Table::new(
                rows,
                [
                    Constraint::Length(18),
                    Constraint::Length(7),
                    Constraint::Length(12),
                    Constraint::Length(8),
                ],
            )
            .header(
                Row::new(["job", "round", "aggregate s", "eval s"])
                    .style(Style::default().fg(MUTED)),
            )
            .block(
                Block::default()
                    .borders(Borders::TOP)
                    .title(" recent round timings ")
                    .border_style(Style::default().fg(MUTED)),
            );
            f.render_widget(table, chunks[1]);
            let foot = match &error {
                Some(e) => Span::styled(
                    format!("  {e}"),
                    Style::default().fg(status_color("offline")),
                ),
                None => Span::styled(
                    format!("  q quit   ↻ {} s", interval.as_secs()),
                    Style::default().fg(MUTED),
                ),
            };
            f.render_widget(Paragraph::new(foot), chunks[2]);
        })?;
        if poll_quit(Duration::from_millis(250))? {
            break;
        }
    }
    Ok(())
}
