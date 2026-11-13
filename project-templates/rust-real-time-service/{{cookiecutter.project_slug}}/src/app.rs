//! State, router, middleware, the page layout, and the error type.

use std::{sync::Arc, time::Instant};

use axum::{
    Router,
    extract::{MatchedPath, Request, State},
    http::{StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Redirect, Response},
    routing::get,
};
use axum_extra::extract::cookie::{Cookie, CookieJar, SameSite};
use maud::{DOCTYPE, Markup, html};
use prometheus_client::{
    encoding::{EncodeLabelSet, text::encode},
    metrics::{counter::Counter, family::Family},
    registry::Registry,
};
use sqlx::SqlitePool;
use tokio_util::sync::CancellationToken;

use crate::{counter, frames::Renderer, monitor, todos};

/// Shared by every handler via `State`; every field is a cheap handle.
#[derive(Clone)]
pub struct AppState {
    pub db: SqlitePool,
    pub renderer: Arc<Renderer>,
    pub registry: Arc<Registry>,
    pub http: Arc<HttpMetrics>,
    /// Cancelled on shutdown: ends the tick loop and every open stream, which
    /// graceful shutdown would otherwise wait on forever.
    pub shutdown: CancellationToken,
}

pub struct HttpMetrics {
    requests: Family<RequestLabels, Counter>,
}

#[derive(Clone, Debug, Hash, PartialEq, Eq, EncodeLabelSet)]
struct RequestLabels {
    method: String,
    route: String,
    status: u16,
}

impl HttpMetrics {
    pub fn new(registry: &mut Registry) -> Self {
        let requests = Family::<RequestLabels, Counter>::default();
        registry.register("http_requests", "HTTP requests served", requests.clone());
        Self { requests }
    }
}

pub fn app(state: AppState) -> Router {
    Router::new()
        .route("/", get(|| async { Redirect::to("/todos") }))
        .route("/healthz", get(|| async { "ok" }))
        .route("/metrics", get(metrics))
        .route("/static/app.css", get(css))
        .merge(todos::routes())
        .merge(monitor::routes())
        .merge(counter::routes())
        .layer(middleware::from_fn_with_state(state.clone(), observe))
        .layer(middleware::from_fn(session))
        .with_state(state)
}

/// The browser's session: a random id in a cookie, set on first visit.
/// Per-session views are keyed by it. It identifies a tab group, not a user,
/// so it needs no signature: an attacker who guesses one sees someone's todos.
/// Swap in real auth before storing anything that matters.
#[derive(Clone)]
pub struct Session(pub String);

async fn session(jar: CookieJar, mut req: Request, next: Next) -> Response {
    let existing = jar
        .get("sid")
        .map(|c| c.value().to_owned())
        .filter(|v| uuid::Uuid::parse_str(v).is_ok());
    let (jar, id) = match existing {
        Some(id) => (jar, id),
        None => {
            let id = uuid::Uuid::new_v4().to_string();
            let cookie = Cookie::build(("sid", id.clone()))
                .path("/")
                .http_only(true)
                .same_site(SameSite::Lax)
                .permanent();
            (jar.add(cookie), id)
        }
    };
    req.extensions_mut().insert(Session(id));
    (jar, next.run(req).await).into_response()
}

/// Count and log each request by route template. For a stream, the response
/// returned here is the headers: the body keeps flowing after this logs.
async fn observe(State(state): State<AppState>, req: Request, next: Next) -> Response {
    let start = Instant::now();
    let method = req.method().to_string();
    let route = req
        .extensions()
        .get::<MatchedPath>()
        .map_or("unmatched", |p| p.as_str())
        .to_owned();
    let res = next.run(req).await;
    let status = res.status().as_u16();
    tracing::info!(%method, %route, status, elapsed_ms = start.elapsed().as_millis() as u64, "request");
    state
        .http
        .requests
        .get_or_create(&RequestLabels {
            method,
            route,
            status,
        })
        .inc();
    res
}

async fn metrics(State(state): State<AppState>) -> Response {
    let mut body = String::new();
    if let Err(err) = encode(&mut body, &state.registry) {
        tracing::error!(%err, "encoding metrics");
        return StatusCode::INTERNAL_SERVER_ERROR.into_response();
    }
    let content_type = "application/openmetrics-text; version=1.0.0; charset=utf-8";
    ([(header::CONTENT_TYPE, content_type)], body).into_response()
}

async fn css() -> impl IntoResponse {
    (
        [
            (header::CONTENT_TYPE, "text/css; charset=utf-8"),
            (header::CACHE_CONTROL, "no-cache"),
        ],
        include_str!("../static/app.css"),
    )
}

/// The page shell every feature renders into. `active` highlights the nav.
pub fn layout(title: &str, active: &str, body: Markup) -> Markup {
    let nav = [
        ("/todos", "Todos"),
        ("/monitor", "Monitor"),
        ("/counter", "Counter"),
    ];
    html! {
        (DOCTYPE)
        html lang="en" {
            head {
                meta charset="utf-8";
                meta name="viewport" content="width=device-width, initial-scale=1";
                title { (title) " · " (crate::TITLE) }
                link rel="stylesheet" href="/static/app.css";
                script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.2/bundles/datastar.js" {}
            }
            body {
                nav {
                    strong { (crate::TITLE) }
                    @for (href, label) in nav {
                        a href=(href) aria-current=[(label == active).then_some("page")] { (label) }
                    }
                }
                main { (body) }
            }
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("database: {0}")]
    Db(#[from] sqlx::Error),
    #[error("task: {0}")]
    Join(#[from] tokio::task::JoinError),
    #[error(transparent)]
    UnknownView(#[from] crate::frames::UnknownView),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        tracing::error!(error = %self, "request failed");
        StatusCode::INTERNAL_SERVER_ERROR.into_response()
    }
}

#[cfg(test)]
pub mod tests {
    use super::*;
    use crate::frames::Renderer;
    use axum::{
        body::{Body, Bytes, to_bytes},
        http::{HeaderMap, Request},
    };
    use futures_util::StreamExt;
    use std::time::Duration;
    use tower::ServiceExt;

    pub const SID: &str = "00000000-0000-4000-8000-000000000001";

    /// A full app with its tick loop running every 10 ms.
    pub async fn test_state() -> AppState {
        let db = crate::db::test_pool().await;
        let mut registry = Registry::default();
        let renderer = Renderer::new(Duration::from_millis(10), &mut registry);
        todos::register(&renderer, db.clone());
        monitor::register(&renderer, Duration::from_millis(50)).unwrap();
        let http = Arc::new(HttpMetrics::new(&mut registry));
        let shutdown = CancellationToken::new();
        tokio::spawn(renderer.clone().run(shutdown.clone()));
        AppState {
            db,
            renderer,
            registry: Arc::new(registry),
            http,
            shutdown,
        }
    }

    pub fn request(method: &str, uri: &str, body: &str) -> Request<Body> {
        Request::builder()
            .method(method)
            .uri(uri)
            .header(header::COOKIE, format!("sid={SID}"))
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(body.to_owned()))
            .unwrap()
    }

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

    /// Opens a stream and returns its frames as they arrive.
    pub async fn open(state: &AppState, uri: &str) -> impl futures_util::Stream<Item = String> {
        let res = app(state.clone())
            .oneshot(request("GET", uri, ""))
            .await
            .unwrap();
        assert_eq!(res.headers()[header::CONTENT_TYPE], "text/event-stream");
        res.into_body()
            .into_data_stream()
            .map(|chunk: Result<Bytes, _>| String::from_utf8(chunk.unwrap().to_vec()).unwrap())
    }

    #[tokio::test]
    async fn a_new_browser_gets_a_session_cookie() {
        let state = test_state().await;
        let req = Request::get("/healthz").body(Body::empty()).unwrap();
        let (_, headers, _) = send(&state, req).await;
        let cookie = headers[header::SET_COOKIE].to_str().unwrap();
        assert!(
            cookie.starts_with("sid=") && cookie.contains("HttpOnly"),
            "{cookie}"
        );

        // A browser that has one keeps it.
        let (_, headers, _) = send(&state, request("GET", "/healthz", "")).await;
        assert!(headers.get(header::SET_COOKIE).is_none());
    }

    #[tokio::test]
    async fn metrics_include_the_frame_loop() {
        let state = test_state().await;
        send(&state, request("GET", "/healthz", "")).await;
        let (_, _, body) = send(&state, request("GET", "/metrics", "")).await;
        for want in [
            r#"http_requests_total{method="GET",route="/healthz",status="200"} 1"#,
            "frames_tick_duration_seconds_count",
            "frames_subscribers",
        ] {
            assert!(body.contains(want), "missing {want}\n{body}");
        }
    }
}
