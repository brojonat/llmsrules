use std::{sync::Arc, time::Instant};

use axum::{
    Json, Router,
    extract::{MatchedPath, Request, State},
    http::{StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::get,
};
use clap::{Parser, ValueEnum};
use prometheus_client::{
    encoding::{EncodeLabelSet, text::encode},
    metrics::{counter::Counter, family::Family},
    registry::Registry,
};
use tokio::signal::unix::{SignalKind, signal};

/// {{cookiecutter.description}}
#[derive(Parser)]
#[command(version)]
struct Cli {
    /// Address to listen on
    #[arg(long, env = "SERVER_ADDR", default_value = "0.0.0.0:{{cookiecutter.default_port}}")]
    addr: String,

    /// Log filter: error, warn, info, debug, or a directive like "info,hyper=warn"
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

/// Shared by every handler via `State`. Add a DB pool, config, etc. here
/// rather than reaching for globals.
#[derive(Clone)]
struct AppState {
    metrics: Arc<Metrics>,
}

struct Metrics {
    registry: Registry,
    requests: Family<RequestLabels, Counter>,
}

#[derive(Clone, Debug, Hash, PartialEq, Eq, EncodeLabelSet)]
struct RequestLabels {
    method: String,
    route: String,
    status: u16,
}

impl Metrics {
    fn new() -> Self {
        let mut registry = Registry::default();
        let requests = Family::<RequestLabels, Counter>::default();
        registry.register("http_requests", "HTTP requests served", requests.clone());
        Self { registry, requests }
    }
}

fn app(state: AppState) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/healthz", get(healthz))
        .route("/metrics", get(metrics))
        .layer(middleware::from_fn_with_state(state.clone(), observe))
        .with_state(state)
}

/// Middleware: count every request by route template (not raw path, to keep
/// label cardinality bounded) and log it.
async fn observe(State(state): State<AppState>, req: Request, next: Next) -> Response {
    let start = Instant::now();
    let method = req.method().to_string();
    let route = req
        .extensions()
        .get::<MatchedPath>()
        .map_or("unmatched", |p| p.as_str())
        .to_owned();

    let res = next.run(req).await;

    let labels = RequestLabels {
        method,
        route,
        status: res.status().as_u16(),
    };
    tracing::info!(
        method = %labels.method,
        route = %labels.route,
        status = labels.status,
        elapsed_ms = start.elapsed().as_millis() as u64,
        "request"
    );
    state.metrics.requests.get_or_create(&labels).inc();
    res
}

async fn index() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "name": env!("CARGO_PKG_NAME"),
        "version": env!("CARGO_PKG_VERSION"),
    }))
}

async fn healthz() -> &'static str {
    "ok"
}

async fn metrics(State(state): State<AppState>) -> Response {
    let mut body = String::new();
    if let Err(err) = encode(&mut body, &state.metrics.registry) {
        tracing::error!(%err, "encoding metrics");
        return StatusCode::INTERNAL_SERVER_ERROR.into_response();
    }
    let content_type = "application/openmetrics-text; version=1.0.0; charset=utf-8";
    ([(header::CONTENT_TYPE, content_type)], body).into_response()
}

fn init_tracing(level: &str, format: &LogFormat) -> Result<(), Box<dyn std::error::Error>> {
    let filter = tracing_subscriber::EnvFilter::try_new(level)
        .map_err(|e| format!("parsing LOG_LEVEL {level:?}: {e}"))?;
    let builder = tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(std::io::stderr);
    match format {
        LogFormat::Json => builder.json().init(),
        LogFormat::Pretty => builder.pretty().init(),
    }
    Ok(())
}

/// Resolves on Ctrl-C or SIGTERM; axum then stops accepting and drains.
async fn shutdown_signal() {
    let mut term = signal(SignalKind::terminate()).expect("installing SIGTERM handler");
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {}
        _ = term.recv() => {}
    }
    tracing::info!("server shutting down");
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();
    init_tracing(&cli.log_level, &cli.log_format)?;

    let state = AppState {
        metrics: Arc::new(Metrics::new()),
    };

    let listener = tokio::net::TcpListener::bind(&cli.addr)
        .await
        .map_err(|e| format!("binding {}: {e}", cli.addr))?;
    tracing::info!(addr = %cli.addr, "server started");

    axum::serve(listener, app(state))
        .with_graceful_shutdown(shutdown_signal())
        .await?;
    tracing::info!("server stopped");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::{Body, to_bytes},
        http,
    };
    use tower::ServiceExt;

    fn test_app() -> Router {
        app(AppState {
            metrics: Arc::new(Metrics::new()),
        })
    }

    async fn fetch(app: &Router, uri: &str) -> (StatusCode, String) {
        let req = http::Request::builder()
            .uri(uri)
            .body(Body::empty())
            .unwrap();
        let res = app.clone().oneshot(req).await.unwrap();
        let status = res.status();
        let body = to_bytes(res.into_body(), usize::MAX).await.unwrap();
        (status, String::from_utf8(body.to_vec()).unwrap())
    }

    #[tokio::test]
    async fn healthz_is_ok() {
        let (status, body) = fetch(&test_app(), "/healthz").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body, "ok");
    }

    #[tokio::test]
    async fn requests_are_counted_by_route() {
        let app = test_app();
        fetch(&app, "/healthz").await;
        fetch(&app, "/nope").await;
        let (_, body) = fetch(&app, "/metrics").await;
        let healthz = r#"http_requests_total{method="GET",route="/healthz",status="200"} 1"#;
        let missing = r#"http_requests_total{method="GET",route="unmatched",status="404"} 1"#;
        assert!(body.contains(healthz), "{body}");
        assert!(body.contains(missing), "{body}");
    }
}
