//! State, router and middleware.

use std::{sync::Arc, time::Instant};

use axum::{
    Json, Router,
    extract::{MatchedPath, Request, State},
    http::{StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::get,
};
use prometheus_client::{
    encoding::{EncodeLabelSet, text::encode},
    metrics::{
        counter::Counter,
        family::Family,
        histogram::{Histogram, exponential_buckets},
    },
    registry::Registry,
};
use sqlx::SqlitePool;
use tower_http::request_id::{MakeRequestUuid, PropagateRequestIdLayer, SetRequestIdLayer};
use tracing::Instrument;

use crate::{auth::Keys, items};

/// Shared by every handler via `State`. axum clones it per request, so every
/// field is a cheap handle: the pool is reference-counted internally, the rest
/// sit behind `Arc`. Add clients and config here, not in globals.
#[derive(Clone)]
pub struct AppState {
    pub db: SqlitePool,
    pub keys: Arc<Keys>,
    pub metrics: Arc<Metrics>,
}

pub struct Metrics {
    registry: Registry,
    requests: Family<RequestLabels, Counter>,
    duration: Family<RouteLabels, Histogram, fn() -> Histogram>,
}

#[derive(Clone, Debug, Hash, PartialEq, Eq, EncodeLabelSet)]
struct RequestLabels {
    method: String,
    route: String,
    status: u16,
}

#[derive(Clone, Debug, Hash, PartialEq, Eq, EncodeLabelSet)]
struct RouteLabels {
    method: String,
    route: String,
}

impl Metrics {
    pub fn new() -> Self {
        let mut registry = Registry::default();
        let requests = Family::<RequestLabels, Counter>::default();
        registry.register("http_requests", "HTTP requests served", requests.clone());
        // 1 ms to ~4 s, doubling.
        let duration =
            Family::<RouteLabels, Histogram, fn() -> Histogram>::new_with_constructor(|| {
                Histogram::new(exponential_buckets(0.001, 2.0, 13))
            });
        registry.register(
            "http_request_duration_seconds",
            "Time to produce a response",
            duration.clone(),
        );
        Self {
            registry,
            requests,
            duration,
        }
    }
}

pub fn app(state: AppState) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/healthz", get(healthz))
        .route("/metrics", get(metrics))
        .merge(items::routes())
        // Layers wrap what was added before them, so the last one runs first:
        // assign an id (or keep the caller's), copy it onto the response,
        // then log and measure the request with the id in its span.
        .layer(middleware::from_fn_with_state(state.clone(), observe))
        .layer(PropagateRequestIdLayer::x_request_id())
        .layer(SetRequestIdLayer::x_request_id(MakeRequestUuid))
        .with_state(state)
}

/// Middleware: run the request inside a span carrying its id, then count and
/// time it by route template (not raw path, to keep label cardinality bounded).
async fn observe(State(state): State<AppState>, req: Request, next: Next) -> Response {
    let start = Instant::now();
    let method = req.method().to_string();
    let route = req
        .extensions()
        .get::<MatchedPath>()
        .map_or("unmatched", |p| p.as_str())
        .to_owned();
    let request_id = req
        .headers()
        .get("x-request-id")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("-")
        .to_owned();

    let span = tracing::info_span!("request", %request_id, %method, %route);
    let res = next.run(req).instrument(span.clone()).await;

    let elapsed = start.elapsed();
    let status = res.status().as_u16();
    span.in_scope(|| {
        tracing::info!(status, elapsed_ms = elapsed.as_millis() as u64, "request");
    });
    let m = &state.metrics;
    m.duration
        .get_or_create(&RouteLabels {
            method: method.clone(),
            route: route.clone(),
        })
        .observe(elapsed.as_secs_f64());
    m.requests
        .get_or_create(&RequestLabels {
            method,
            route,
            status,
        })
        .inc();
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

#[cfg(test)]
pub mod tests {
    use super::*;
    use axum::{
        body::{Body, to_bytes},
        http::{HeaderMap, Request},
    };
    use tower::ServiceExt;

    pub async fn test_state() -> AppState {
        AppState {
            db: crate::db::test_pool().await,
            keys: Arc::new(Keys::new(b"test-secret")),
            metrics: Arc::new(Metrics::new()),
        }
    }

    /// Drive the router in-process: no socket, no server.
    pub async fn send(state: &AppState, req: Request<Body>) -> (StatusCode, HeaderMap, String) {
        let res = app(state.clone()).oneshot(req).await.unwrap();
        let (parts, body) = res.into_parts();
        let body = to_bytes(body, usize::MAX).await.unwrap();
        (
            parts.status,
            parts.headers,
            String::from_utf8(body.to_vec()).unwrap(),
        )
    }

    fn get(uri: &str) -> Request<Body> {
        Request::get(uri).body(Body::empty()).unwrap()
    }

    #[tokio::test]
    async fn healthz_is_ok() {
        let (status, _, body) = send(&test_state().await, get("/healthz")).await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body, "ok");
    }

    #[tokio::test]
    async fn requests_are_counted_and_timed_by_route() {
        let state = test_state().await;
        send(&state, get("/healthz")).await;
        send(&state, get("/nope")).await;
        let (_, _, body) = send(&state, get("/metrics")).await;
        for want in [
            r#"http_requests_total{method="GET",route="/healthz",status="200"} 1"#,
            r#"http_requests_total{method="GET",route="unmatched",status="404"} 1"#,
            r#"http_request_duration_seconds_count{method="GET",route="/healthz"} 1"#,
        ] {
            assert!(body.contains(want), "missing {want}\n{body}");
        }
    }

    #[tokio::test]
    async fn every_response_carries_a_request_id() {
        let state = test_state().await;
        let (_, headers, _) = send(&state, get("/healthz")).await;
        assert_eq!(headers["x-request-id"].len(), 36, "a fresh UUID");

        let req = Request::get("/healthz")
            .header("x-request-id", "from-the-caller")
            .body(Body::empty())
            .unwrap();
        let (_, headers, _) = send(&state, req).await;
        assert_eq!(headers["x-request-id"], "from-the-caller");
    }
}
