//! `plasmon`: the fast front end. Native commands talk to the coordinator directly;
//! `job submit`, `trainer` and `server` run through the Python engine.

mod api;
mod commands;
mod paths;
mod python;
mod tui;

use anyhow::{Context, Result};
use clap::{CommandFactory, Parser, Subcommand};
use plasmon_core::identity::Identity;
use std::time::Duration;

#[derive(Parser)]
#[command(
    name = "plasmon",
    version,
    about = "Train models on a fleet of volunteer GPUs"
)]
struct Cli {
    /// Print machine-readable JSON instead of text.
    #[arg(long, global = true)]
    json: bool,
    /// Coordinator URL. Default: the one you logged in to.
    #[arg(long, global = true)]
    server: Option<String>,
    /// Plain text, no animation, no alternate screen.
    #[arg(long, global = true)]
    plain: bool,
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// Create this machine's Ed25519 key.
    Init {
        #[arg(long)]
        force: bool,
    },
    /// Log in to a coordinator with a device code confirmed in the browser.
    Login {
        #[arg(long)]
        server: String,
        #[arg(long)]
        no_browser: bool,
    },
    /// Forget the saved login.
    Logout,
    /// Show the local identity, the server and the user.
    Whoami,
    /// Submit and follow jobs.
    Job {
        #[command(subcommand)]
        cmd: JobCmd,
    },
    /// Offer this machine to the network.
    Trainer {
        #[command(subcommand)]
        cmd: TrainerCmd,
    },
    /// Run and manage a coordinator.
    Server {
        #[command(subcommand)]
        cmd: ServerCmd,
    },
    /// Machines you can see.
    Fleet {
        #[arg(long)]
        status: Option<String>,
        /// Live table, refreshed every two seconds.
        #[arg(short, long)]
        watch: bool,
    },
    /// The hash-chained ledger.
    Ledger {
        #[command(subcommand)]
        cmd: LedgerCmd,
    },
    /// Print shell completions.
    Completions {
        #[arg(value_enum)]
        shell: clap_complete::Shell,
    },
}

#[derive(Subcommand)]
enum JobCmd {
    /// Validate a job.yaml, upload what the server lacks, create the job.
    Submit {
        file: String,
    },
    List {
        /// Every job in the org (operator role).
        #[arg(long)]
        all: bool,
    },
    Status {
        id: String,
    },
    /// Follow a job: loss, rounds, trainers.
    Watch {
        id: String,
        #[arg(long, default_value_t = 2.0)]
        interval: f64,
    },
    /// Save the latest weights as a safetensors file.
    Download {
        id: String,
        #[arg(short, long)]
        output: Option<String>,
    },
    Cancel {
        id: String,
    },
}

#[derive(Subcommand)]
enum TrainerCmd {
    /// Enrol this machine and train rounds until stopped.
    Start {
        #[arg(long)]
        name: Option<String>,
        #[arg(long, default_value = "any")]
        device: String,
        #[arg(long)]
        max_hours: Option<f64>,
    },
}

#[derive(Subcommand)]
enum ServerCmd {
    /// Write plasmon-server.yaml.
    Init {
        #[arg(long, default_value = "home")]
        mode: String,
        #[arg(long, default_value_t = 7117)]
        port: u16,
        #[arg(long, default_value = "home")]
        org: String,
        #[arg(long)]
        public_url: Option<String>,
    },
    /// Start the coordinator.
    Start,
    /// Create the owner account on an empty server.
    Bootstrap {
        #[arg(long)]
        owner: String,
        #[arg(long)]
        password: Option<String>,
    },
    /// Coordinator health (operator role).
    Status,
}

#[derive(Subcommand)]
enum LedgerCmd {
    /// Recompute the hash chain and check every signature.
    Verify,
}

fn main() {
    let code = match run() {
        Ok(code) => code,
        Err(e) => {
            eprintln!("error: {e:#}");
            1
        }
    };
    std::process::exit(code);
}

fn run() -> Result<i32> {
    let cli = Cli::parse();
    let server = cli.server.as_deref();
    let plain = cli.plain || !tui::animation_enabled();
    match cli.command {
        None => {
            if paths::Credentials::load()?.is_none() {
                Cli::command().print_help()?;
                println!("\nStart with: plasmon login --server http://<host>:7117");
                return Ok(0);
            }
            let api = commands::api(server)?;
            if plain {
                let home = tui::fetch_home(&api)?;
                println!(
                    "{} · {} of {} machines online · {} jobs running",
                    home.me["user"]["email"].as_str().unwrap_or(""),
                    home.summary["online"],
                    home.summary["machines"],
                    home.summary["jobs_running"]
                );
                commands::job_list(server, false, false)?;
            } else {
                tui::home(&api, true)?;
            }
            Ok(0)
        }
        Some(Command::Init { force }) => init(force, cli.json).map(|_| 0),
        Some(Command::Login { server, no_browser }) => {
            commands::login(&server, no_browser, cli.json).map(|_| 0)
        }
        Some(Command::Logout) => commands::logout().map(|_| 0),
        Some(Command::Whoami) => commands::whoami(cli.json).map(|_| 0),
        Some(Command::Job { cmd }) => match cmd {
            JobCmd::Submit { file } => {
                python::run(&with_server(server, &["job", "submit", &file], cli.json))
            }
            JobCmd::List { all } => commands::job_list(server, all, cli.json).map(|_| 0),
            JobCmd::Status { id } => commands::job_status(server, &id, cli.json).map(|_| 0),
            JobCmd::Watch { id, interval } => {
                if plain || cli.json {
                    commands::job_watch_plain(server, &id, interval)
                } else {
                    tui::job_watch(
                        &commands::api(server)?,
                        &id,
                        Duration::from_secs_f64(interval),
                    )
                    .map(|_| 0)
                }
            }
            JobCmd::Download { id, output } => {
                commands::job_download(server, &id, output.as_deref()).map(|_| 0)
            }
            JobCmd::Cancel { id } => commands::job_cancel(server, &id).map(|_| 0),
        },
        Some(Command::Trainer { cmd }) => match cmd {
            TrainerCmd::Start {
                name,
                device,
                max_hours,
            } => {
                let mut args = vec![
                    "trainer".to_string(),
                    "start".to_string(),
                    "--device".to_string(),
                    device,
                ];
                if let Some(n) = name {
                    args.extend(["--name".to_string(), n]);
                }
                if let Some(h) = max_hours {
                    args.extend(["--max-hours".to_string(), h.to_string()]);
                }
                python::run(&with_server_vec(server, args, false))
            }
        },
        Some(Command::Server { cmd }) => match cmd {
            ServerCmd::Init {
                mode,
                port,
                org,
                public_url,
            } => {
                let mut args = vec![
                    "server".into(),
                    "init".into(),
                    "--mode".into(),
                    mode,
                    "--port".into(),
                    port.to_string(),
                    "--org".into(),
                    org,
                ];
                if let Some(u) = public_url {
                    args.extend(["--public-url".to_string(), u]);
                }
                python::run(&args)
            }
            ServerCmd::Start => python::run(&["server".to_string(), "start".to_string()]),
            ServerCmd::Bootstrap { owner, password } => {
                let mut args = vec![
                    "server".to_string(),
                    "bootstrap".to_string(),
                    "--owner".to_string(),
                    owner,
                ];
                if let Some(p) = password {
                    args.extend(["--password".to_string(), p]);
                }
                python::run(&args)
            }
            ServerCmd::Status => commands::server_status(server, cli.json).map(|_| 0),
        },
        Some(Command::Fleet { status, watch }) => {
            if watch && !plain && !cli.json {
                tui::fleet_watch(&commands::api(server)?, Duration::from_secs(2)).map(|_| 0)
            } else {
                commands::fleet(server, status.as_deref(), cli.json).map(|_| 0)
            }
        }
        Some(Command::Ledger { cmd }) => match cmd {
            LedgerCmd::Verify => commands::ledger_verify(server, cli.json),
        },
        Some(Command::Completions { shell }) => {
            clap_complete::generate(
                shell,
                &mut Cli::command(),
                "plasmon",
                &mut std::io::stdout(),
            );
            Ok(0)
        }
    }
}

fn with_server(server: Option<&str>, args: &[&str], json: bool) -> Vec<String> {
    with_server_vec(server, args.iter().map(|s| s.to_string()).collect(), json)
}

fn with_server_vec(server: Option<&str>, args: Vec<String>, json: bool) -> Vec<String> {
    let mut out = Vec::new();
    if json {
        out.push("--json".to_string());
    }
    if let Some(s) = server {
        out.extend(["--server".to_string(), s.to_string()]);
    }
    out.extend(args);
    out
}

fn init(force: bool, json: bool) -> Result<()> {
    let path = paths::machine_key();
    let (created, ident) = if path.exists() && !force {
        (
            false,
            Identity::load(&path).with_context(|| format!("reading {}", path.display()))?,
        )
    } else {
        let ident = Identity::generate();
        ident
            .save(&path)
            .with_context(|| format!("writing {}", path.display()))?;
        (true, ident)
    };
    if json {
        println!(
            "{}",
            serde_json::json!({"node_id": ident.node_id(), "path": path, "created": created})
        );
    } else if created {
        println!(
            "created machine key: {}\nnode id: {}",
            path.display(),
            ident.node_id()
        );
    } else {
        println!(
            "machine key exists: {}\nnode id: {}",
            path.display(),
            ident.node_id()
        );
    }
    Ok(())
}
