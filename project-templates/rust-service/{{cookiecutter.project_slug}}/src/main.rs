//! {{cookiecutter.project_name}}: {{cookiecutter.description}}
//!
//! `main` only parses flags, sets up logging and wires the pieces together;
//! the service itself is in `app` (state, router, middleware), `items` (an
//! example resource: SQL and handlers), `auth` (JWT) and `error`.

mod app;
mod auth;
mod db;
mod error;
mod items;

use std::{sync::Arc, time::Duration};

use anyhow::Context;
use clap::{Args, Parser, Subcommand, ValueEnum};
use tokio::signal::unix::{SignalKind, signal};

/// {{cookiecutter.description}}
#[derive(Parser)]
#[command(version)]
struct Cli {
    #[command(subcommand)]
    command: Command,

    /// Log filter: error, warn, info, debug, or a directive like "info,sqlx=warn"
    #[arg(long, env = "LOG_LEVEL", default_value = "warn", global = true)]
    log_level: String,

    /// Log format: json for prod, pretty for dev
    #[arg(long, env = "LOG_FORMAT", value_enum, default_value_t = LogFormat::Json, global = true)]
    log_format: LogFormat,
}

#[derive(Subcommand)]
enum Command {
    /// Run the HTTP server
    Serve(ServeArgs),
    /// Mint a bearer token for the API (JSON on stdout)
    Token(TokenArgs),
}

#[derive(Args)]
struct ServeArgs {
    /// Address to listen on
    #[arg(long, env = "SERVER_ADDR", default_value = "0.0.0.0:{{cookiecutter.default_port}}")]
    addr: String,

    /// SQLite database; the file is created if missing
    #[arg(long, env = "DATABASE_URL", default_value = "sqlite://data/app.db")]
    database_url: String,

    /// HMAC secret for signing and verifying bearer tokens
    #[arg(long, env = "AUTH_SECRET", hide_env_values = true)]
    auth_secret: String,
}

#[derive(Args)]
struct TokenArgs {
    /// Who the token is for; handlers see it as `claims.sub`
    #[arg(long)]
    sub: String,

    /// Lifetime in hours
    #[arg(long, default_value_t = 24)]
    ttl_hours: u64,

    /// Must match the server's AUTH_SECRET
    #[arg(long, env = "AUTH_SECRET", hide_env_values = true)]
    auth_secret: String,
}

#[derive(Clone, ValueEnum)]
enum LogFormat {
    Json,
    Pretty,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    init_tracing(&cli.log_level, &cli.log_format)?;

    match cli.command {
        Command::Serve(args) => serve(args).await,
        Command::Token(args) => {
            let keys = auth::Keys::new(args.auth_secret.as_bytes());
            let ttl = Duration::from_secs(args.ttl_hours * 3600);
            let (token, exp) = keys.mint(&args.sub, ttl).context("signing token")?;
            println!("{}", serde_json::json!({ "token": token, "exp": exp }));
            Ok(())
        }
    }
}

async fn serve(args: ServeArgs) -> anyhow::Result<()> {
    let db = db::connect(&args.database_url)
        .await
        .with_context(|| format!("opening {}", args.database_url))?;
    let state = app::AppState {
        db,
        keys: Arc::new(auth::Keys::new(args.auth_secret.as_bytes())),
        metrics: Arc::new(app::Metrics::new()),
    };

    let listener = tokio::net::TcpListener::bind(&args.addr)
        .await
        .with_context(|| format!("binding {}", args.addr))?;
    tracing::info!(addr = %args.addr, "server started");

    axum::serve(listener, app::app(state))
        .with_graceful_shutdown(shutdown_signal())
        .await
        .context("serving")?;
    tracing::info!("server stopped");
    Ok(())
}

fn init_tracing(level: &str, format: &LogFormat) -> anyhow::Result<()> {
    let filter = tracing_subscriber::EnvFilter::try_new(level)
        .with_context(|| format!("parsing LOG_LEVEL {level:?}"))?;
    let builder = tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(std::io::stderr);
    match format {
        LogFormat::Json => builder.json().init(),
        LogFormat::Pretty => builder.pretty().init(),
    }
    Ok(())
}

/// Resolves on Ctrl-C or SIGTERM; axum then stops accepting and drains. As
/// PID 1 in a container the process gets no default signal handling, so
/// handling SIGTERM here is what makes `docker stop` and pod deletion quick.
async fn shutdown_signal() {
    let mut term = signal(SignalKind::terminate()).expect("installing SIGTERM handler");
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {}
        _ = term.recv() => {}
    }
    tracing::info!("server shutting down");
}
