//! {{cookiecutter.project_name}}: {{cookiecutter.description}}
//!
//! Every live view is rendered by one tick loop (`frames`), never by a
//! request: writes mark views dirty, each tick renders the dirty ones once,
//! and every open stream gets the newest frame. Features are vertical slices
//! (`todos`, `monitor`, `counter`); `app` holds what they share.

mod app;
mod counter;
mod db;
mod frames;
mod monitor;
mod stream;
mod todos;

use std::{sync::Arc, time::Duration};

use anyhow::Context;
use clap::{Parser, ValueEnum};
use prometheus_client::registry::Registry;
use tokio::signal::unix::{SignalKind, signal};
use tokio_util::sync::CancellationToken;

pub const TITLE: &str = "{{cookiecutter.project_name}}";

/// {{cookiecutter.description}}
#[derive(Parser)]
#[command(version)]
struct Cli {
    /// Address to listen on
    #[arg(long, env = "SERVER_ADDR", default_value = "0.0.0.0:{{cookiecutter.default_port}}")]
    addr: String,

    /// SQLite database; the file is created if missing
    #[arg(long, env = "DATABASE_URL", default_value = "sqlite://data/app.db")]
    database_url: String,

    /// Render budget per tick, in milliseconds: the most often a view can change on screen
    #[arg(long, env = "FRAME_TICK_MS", default_value_t = 100)]
    frame_tick_ms: u64,

    /// Log filter: error, warn, info, debug, or a directive like "info,sqlx=warn"
    #[arg(long, env = "LOG_LEVEL", default_value = "warn")]
    log_level: String,

    /// Log format: json for prod, pretty for dev
    #[arg(long, env = "LOG_FORMAT", value_enum, default_value_t = LogFormat::Json)]
    log_format: LogFormat,
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

    let db = db::connect(&cli.database_url)
        .await
        .with_context(|| format!("opening {}", cli.database_url))?;

    let mut registry = Registry::default();
    let renderer = frames::Renderer::new(Duration::from_millis(cli.frame_tick_ms), &mut registry);
    todos::register(&renderer, db.clone());
    monitor::register(&renderer, Duration::from_millis(500))?;
    let http = Arc::new(app::HttpMetrics::new(&mut registry));

    let shutdown = CancellationToken::new();
    let ticker = tokio::spawn(renderer.clone().run(shutdown.clone()));
    let state = app::AppState {
        db,
        renderer,
        registry: Arc::new(registry),
        http,
        shutdown: shutdown.clone(),
    };

    let listener = tokio::net::TcpListener::bind(&cli.addr)
        .await
        .with_context(|| format!("binding {}", cli.addr))?;
    tracing::info!(addr = %cli.addr, tick_ms = cli.frame_tick_ms, "server started");

    // On SIGTERM: cancel the token, which ends every open stream and the tick
    // loop, so graceful shutdown has nothing left to wait for.
    let signal_token = shutdown.clone();
    let served = axum::serve(listener, app::app(state))
        .with_graceful_shutdown(async move {
            shutdown_signal().await;
            signal_token.cancel();
        })
        .await;
    shutdown.cancel(); // also when serve failed, so the tick loop stops
    ticker.await.context("tick loop")?;
    served.context("serving")?;
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

/// Resolves on Ctrl-C or SIGTERM. As PID 1 in a container the process gets no
/// default signal handling, so handling SIGTERM here is what makes pod
/// deletion quick.
async fn shutdown_signal() {
    let mut term = signal(SignalKind::terminate()).expect("installing SIGTERM handler");
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {}
        _ = term.recv() => {}
    }
    tracing::info!("server shutting down");
}
