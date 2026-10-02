//! `plasmon`: the fast front end. Network and TUI commands arrive in later milestones;
//! this milestone ships identity, configuration and the start-up budget.

mod paths;

use anyhow::{Context, Result};
use clap::{CommandFactory, Parser, Subcommand};
use plasmon_core::identity::Identity;

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
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Subcommand)]
enum Command {
    /// Create this machine's Ed25519 key.
    Init {
        /// Replace an existing key.
        #[arg(long)]
        force: bool,
    },
    /// Show the local identity and the configured server.
    Whoami,
    /// Print shell completions.
    Completions {
        #[arg(value_enum)]
        shell: clap_complete::Shell,
    },
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        None => {
            Cli::command().print_help()?;
            Ok(())
        }
        Some(Command::Init { force }) => init(force, cli.json),
        Some(Command::Whoami) => whoami(cli.json),
        Some(Command::Completions { shell }) => {
            clap_complete::generate(
                shell,
                &mut Cli::command(),
                "plasmon",
                &mut std::io::stdout(),
            );
            Ok(())
        }
    }
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

fn whoami(json: bool) -> Result<()> {
    let key_path = paths::machine_key();
    let node_id = if key_path.exists() {
        Some(Identity::load(&key_path)?.node_id())
    } else {
        None
    };
    let creds = paths::Credentials::load()?;
    if json {
        println!(
            "{}",
            serde_json::json!({
                "node_id": node_id,
                "server": creds.as_ref().map(|c| c.server.clone()),
                "user": creds.as_ref().map(|c| c.user.clone()),
            })
        );
        return Ok(());
    }
    match node_id {
        Some(id) => println!("node id: {id}"),
        None => println!("no machine key yet. Run: plasmon init"),
    }
    match creds {
        Some(c) => println!("server:  {}\nuser:    {}", c.server, c.user),
        None => println!("not logged in. Run: plasmon login --server <url>"),
    }
    Ok(())
}
