//! {{cookiecutter.project_name}} -- a complete real-time web app in one file.
//!
//! It follows the Tao of Datastar: the backend owns all state, one long-lived
//! SSE request streams the UI down, and short-lived POSTs send commands up.
//! That split is CQRS, and it is what makes the app multiplayer for free --
//! every connected browser renders from the same server-side state, so a write
//! from any of them shows up in all of them.
//!
//! State lives in SQLite, and the SQL is plain SQL: see the "Database"
//! section and `migrations/`. The browser gets datastar.js from a CDN via one
//! script tag; there is no frontend build step.
//!
//!     mise run dev   # then open http://localhost:8080 in two tabs

use std::{convert::Infallible, io::Write, str::FromStr, time::Duration};

use axum::{
    Router,
    body::{Body, Bytes},
    extract::State,
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use datastar::{axum::ReadSignals, prelude::PatchElements};
use maud::{DOCTYPE, Markup, PreEscaped, html};
use serde::Deserialize;
use sqlx::{
    FromRow, SqlitePool,
    sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions},
};
use tokio::sync::watch;
use tokio_util::sync::CancellationToken;

const TITLE: &str = "{{cookiecutter.project_name}}";

/// The board shows this many messages, and the table keeps no more.
const KEEP: i64 = 50;

// ---------------------------------------------------------------------------
// Database. Plain SQL, checked at runtime: `query` / `query_as` / `query_scalar`
// with `?` placeholders and `.bind()`. Rows map onto structs with
// `#[derive(FromRow)]`, matching columns by name. The schema is in
// `migrations/`, applied at startup.
// ---------------------------------------------------------------------------

#[derive(FromRow)]
struct Message {
    id: i64,
    body: String,
    created_at: String,
}

#[derive(FromRow)]
struct Stats {
    total: i64,
    last_at: Option<String>, // NULL when the table is empty
}

async fn connect(url: &str) -> Result<SqlitePool, sqlx::Error> {
    let opts = SqliteConnectOptions::from_str(url)?
        .create_if_missing(true)
        // WAL lets the many stream readers run while a write commits.
        .journal_mode(SqliteJournalMode::Wal)
        .busy_timeout(Duration::from_secs(5));
    let db = SqlitePoolOptions::new().connect_with(opts).await?;
    sqlx::migrate!().run(&db).await?;
    Ok(db)
}

async fn recent_messages(db: &SqlitePool) -> Result<Vec<Message>, sqlx::Error> {
    sqlx::query_as("SELECT id, body, created_at FROM messages ORDER BY id DESC LIMIT ?")
        .bind(KEEP)
        .fetch_all(db)
        .await
}

async fn stats(db: &SqlitePool) -> Result<Stats, sqlx::Error> {
    sqlx::query_as("SELECT count(*) AS total, max(created_at) AS last_at FROM messages")
        .fetch_one(db)
        .await
}

/// Insert, then trim to the newest `KEEP` rows, in one transaction: readers see
/// both or neither. Dropping `tx` without `commit()` rolls back.
async fn insert_message(db: &SqlitePool, body: &str) -> Result<i64, sqlx::Error> {
    let mut tx = db.begin().await?;
    let id: i64 = sqlx::query_scalar("INSERT INTO messages (body) VALUES (?) RETURNING id")
        .bind(body)
        .fetch_one(&mut *tx)
        .await?;
    sqlx::query("DELETE FROM messages WHERE id <= ?")
        .bind(id - KEEP)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok(id)
}

async fn clear_messages(db: &SqlitePool) -> Result<u64, sqlx::Error> {
    let res = sqlx::query("DELETE FROM messages").execute(db).await?;
    Ok(res.rows_affected())
}

// ---------------------------------------------------------------------------
// State. Cheap to clone: the pool, the sender and the token are handles, so
// axum hands each request its own copy and nothing needs an Arc.
// ---------------------------------------------------------------------------

#[derive(Clone)]
struct AppState {
    db: SqlitePool,
    /// A version counter. Writes bump it; every open stream wakes and
    /// re-renders. Several bumps before a stream wakes coalesce into one.
    changes: watch::Sender<u64>,
    /// Cancelled on shutdown so open streams end and the server can exit.
    shutdown: CancellationToken,
}

impl AppState {
    fn new(db: SqlitePool) -> Self {
        Self {
            db,
            changes: watch::Sender::new(0),
            shutdown: CancellationToken::new(),
        }
    }

    fn notify(&self) {
        self.changes.send_modify(|v| *v += 1);
    }
}

// ---------------------------------------------------------------------------
// Templates. maud checks the markup at compile time and escapes every `(expr)`.
// `board` is both part of the first page load and the fragment pushed on every
// change -- Datastar morphs it in, so there is no separate client-side view.
// ---------------------------------------------------------------------------

fn page(board: Markup) -> Markup {
    html! {
        (DOCTYPE)
        html lang="en" {
            head {
                meta charset="utf-8";
                meta name="viewport" content="width=device-width, initial-scale=1";
                title { (TITLE) }
                link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>💬</text></svg>";
                script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.2/bundles/datastar.js" {}
                style { (PreEscaped(CSS)) }
            }
            // The one long-lived read request. It never returns; the server
            // pushes every subsequent render down it. openWhenHidden keeps it
            // open when the tab is backgrounded, so the tab never goes stale.
            body data-init="@get('/updates', {openWhenHidden: true})" {
                (board)
            }
        }
    }
}

const CSS: &str = "
  body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem; }
  form { display: flex; gap: .5rem; margin: 1rem 0; }
  input { flex: 1; padding: .5rem; }
  /* 16px minimum, or iOS Safari zooms the page when the input is focused. */
  input, button { font-size: 1rem; }
  li { padding: .25rem 0; }
  time { color: #666; font-size: .875rem; margin-right: .5rem; }
  footer { margin-top: 1rem; color: #666; font-size: .875rem; }
";

/// The live region. Every write re-renders this whole element and morphs it
/// in: no per-field patching, no diffing by hand.
fn board(messages: &[Message], stats: &Stats) -> Markup {
    html! {
        main #board {
            h1 { "Messages" }
            // A command, not a render request. The server answers 204 and the
            // update arrives on the SSE stream.
            form data-on:submit__prevent="@post('/add'); $message = ''" {
                input name="message" placeholder="Say something" autocomplete="off"
                    aria-label="Message" maxlength="500" data-bind:message;
                button type="submit" { "Send" }
            }
            ul aria-live="polite" {
                @for m in messages {
                    li #{"msg-" (m.id)} { time { (m.created_at) } (m.body) }
                } @if messages.is_empty() {
                    li { em { "No messages yet." } }
                }
            }
            footer {
                (stats.total) " message(s)"
                @if let Some(at) = &stats.last_at { ", last at " (at) }
                " · open a second tab to watch them sync "
                button data-on:click="@post('/clear')" { "Clear" }
            }
        }
    }
}

async fn render_board(db: &SqlitePool) -> Result<Markup, sqlx::Error> {
    let (messages, stats) = tokio::try_join!(recent_messages(db), stats(db))?;
    Ok(board(&messages, &stats))
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

async fn index(State(app): State<AppState>) -> Result<Markup, AppError> {
    Ok(page(render_board(&app.db).await?))
}

/// The read side: render current state, then wait for a change, forever. The
/// response body is a stream; when the client goes away axum drops it, which
/// cancels the loop at its next `.await`. Nothing to clean up.
async fn updates(State(app): State<AppState>, headers: HeaderMap) -> Response {
    let brotli = accepts_brotli(&headers);
    let stream = Stream {
        changes: app.changes.subscribe(),
        encoder: Encoder::new(brotli),
        app,
        first: true,
    };
    // unfold threads `Stream` through each step: yield one frame, get it back.
    let frames = futures_util::stream::unfold(stream, |mut s| async move {
        if !s.first {
            tokio::select! {
                res = s.changes.changed() => res.ok()?,
                () = s.app.shutdown.cancelled() => return None,
            }
        }
        s.first = false;
        let html = match render_board(&s.app.db).await {
            Ok(html) => html.into_string(),
            Err(e) => {
                tracing::error!(error = %e, "rendering board");
                return None; // ends the stream; the browser reconnects
            }
        };
        let event = PatchElements::new(html).as_datastar_event().to_string();
        let chunk = s.encoder.encode(event.as_bytes());
        Some((Ok::<_, Infallible>(chunk), s))
    });

    let mut res = Body::from_stream(frames).into_response();
    let h = res.headers_mut();
    h.insert(header::CONTENT_TYPE, "text/event-stream".parse().unwrap());
    h.insert(header::CACHE_CONTROL, "no-cache".parse().unwrap());
    h.insert(header::VARY, "accept-encoding".parse().unwrap());
    if brotli {
        h.insert(header::CONTENT_ENCODING, "br".parse().unwrap());
    }
    res
}

/// Everything one open stream owns.
struct Stream {
    app: AppState,
    changes: watch::Receiver<u64>,
    encoder: Encoder,
    first: bool,
}

#[derive(Deserialize)]
struct Signals {
    #[serde(default)]
    message: String,
}

/// The write side: mutate and return nothing. The open stream is what puts
/// the result on screen.
async fn add(
    State(app): State<AppState>,
    ReadSignals(signals): ReadSignals<Signals>,
) -> Result<StatusCode, AppError> {
    let body = signals.message.trim().to_owned();
    if body.is_empty() || body.chars().count() > 500 {
        return Ok(StatusCode::NO_CONTENT);
    }
    // Spawned so that a client disconnecting mid-request can't cancel us
    // between the commit and the notify (which would leave every other tab
    // stale until the next write). The handler is dropped; the task is not.
    tokio::spawn(async move {
        insert_message(&app.db, &body).await?;
        app.notify();
        Ok::<_, sqlx::Error>(())
    })
    .await??;
    Ok(StatusCode::NO_CONTENT)
}

async fn clear(State(app): State<AppState>) -> Result<StatusCode, AppError> {
    tokio::spawn(async move {
        clear_messages(&app.db).await?;
        app.notify();
        Ok::<_, sqlx::Error>(())
    })
    .await??;
    Ok(StatusCode::NO_CONTENT)
}

#[derive(Debug, thiserror::Error)]
enum AppError {
    #[error("database: {0}")]
    Db(#[from] sqlx::Error),
    #[error("task: {0}")]
    Join(#[from] tokio::task::JoinError),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        tracing::error!(error = %self, "request failed");
        StatusCode::INTERNAL_SERVER_ERROR.into_response()
    }
}

// ---------------------------------------------------------------------------
// Compression. Fat-morph HTML compresses ~200:1 because each stream keeps one
// Brotli context: every frame is compressed against the ones before it. Each
// open stream holds that context, and its size is set mostly by quality, then
// by the window. Quality 1 with lgwin 17 (a 128 KiB window, for frames up to
// ~64 KB) holds ~170 KiB per stream on 16 KB frames; quality 5 holds ~1.6 MiB
// for ~30% fewer bytes, and the usual default window (lgwin 22) ~9 MiB.
// ---------------------------------------------------------------------------

fn accepts_brotli(headers: &HeaderMap) -> bool {
    headers
        .get_all(header::ACCEPT_ENCODING)
        .iter()
        .filter_map(|v| v.to_str().ok())
        .flat_map(|v| v.split(','))
        .any(|enc| enc.split(';').next().is_some_and(|e| e.trim() == "br"))
}

enum Encoder {
    Identity,
    Brotli(Box<brotli::CompressorWriter<Vec<u8>>>),
}

impl Encoder {
    fn new(brotli: bool) -> Self {
        if !brotli {
            return Self::Identity;
        }
        let params = brotli::enc::BrotliEncoderParams {
            quality: 1,
            lgwin: 17,
            ..Default::default()
        };
        Self::Brotli(Box::new(brotli::CompressorWriter::with_params(
            Vec::new(),
            4096,
            &params,
        )))
    }

    /// Compress one event and flush, so the browser can decode it now rather
    /// than when the stream ends.
    fn encode(&mut self, event: &[u8]) -> Bytes {
        match self {
            Self::Identity => Bytes::copy_from_slice(event),
            Self::Brotli(w) => {
                // Writing to a Vec can't fail.
                w.write_all(event).expect("in-memory write");
                w.flush().expect("in-memory flush");
                Bytes::from(std::mem::take(w.get_mut()))
            }
        }
    }
}

// ---------------------------------------------------------------------------

fn app(state: AppState) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/updates", get(updates))
        .route("/add", post(add))
        .route("/clear", post(clear))
        .with_state(state)
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    use anyhow::Context;

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_env("LOG_LEVEL")
                .unwrap_or_else(|_| "info".into()),
        )
        .with_writer(std::io::stderr)
        .init();

    let url = std::env::var("DATABASE_URL").unwrap_or_else(|_| "sqlite://app.db".into());
    let db = connect(&url)
        .await
        .with_context(|| format!("opening {url}"))?;
    let state = AppState::new(db);

    let port = std::env::var("PORT").unwrap_or_else(|_| "8080".into());
    let addr = format!("0.0.0.0:{port}");
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .with_context(|| format!("binding {addr}"))?;
    tracing::info!("listening on http://localhost:{port}");

    // Graceful shutdown waits for open requests, and an SSE stream never
    // finishes on its own. Cancelling the token ends every stream.
    let shutdown = state.shutdown.clone();
    axum::serve(listener, app(state))
        .with_graceful_shutdown(async move {
            shutdown_signal().await;
            shutdown.cancel();
        })
        .await
        .context("serving")?;
    Ok(())
}

async fn shutdown_signal() {
    use tokio::signal::unix::{SignalKind, signal};
    let mut term = signal(SignalKind::terminate()).expect("installing SIGTERM handler");
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {}
        _ = term.recv() => {}
    }
    tracing::info!("shutting down");
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::Request;
    use futures_util::StreamExt;
    use tower::ServiceExt;

    /// Each connection to `sqlite::memory:` is its own empty database, so an
    /// in-memory pool must hold exactly one connection.
    async fn test_state() -> AppState {
        let db = SqlitePoolOptions::new()
            .max_connections(1)
            .connect("sqlite::memory:")
            .await
            .unwrap();
        sqlx::migrate!().run(&db).await.unwrap();
        AppState::new(db)
    }

    fn post_message(msg: &str) -> Request<Body> {
        Request::post("/add")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                serde_json::json!({ "message": msg }).to_string(),
            ))
            .unwrap()
    }

    #[tokio::test]
    async fn writes_show_up_on_the_stream() {
        let app = app(test_state().await);
        let res = app
            .clone()
            .oneshot(Request::get("/updates").body(Body::empty()).unwrap())
            .await
            .unwrap();
        let mut frames = res.into_body().into_data_stream();

        let first = frames.next().await.unwrap().unwrap();
        assert!(
            std::str::from_utf8(&first)
                .unwrap()
                .contains("No messages yet")
        );

        let res = app.oneshot(post_message("hello <b>")).await.unwrap();
        assert_eq!(res.status(), StatusCode::NO_CONTENT);

        let next = frames.next().await.unwrap().unwrap();
        let next = std::str::from_utf8(&next).unwrap();
        assert!(
            next.starts_with("event: datastar-patch-elements\n"),
            "{next}"
        );
        assert!(next.contains("hello &lt;b&gt;"), "escaped: {next}");
    }

    #[tokio::test]
    async fn brotli_frames_decode_before_the_stream_ends() {
        use std::io::Read;
        let res = app(test_state().await)
            .oneshot(
                Request::get("/updates")
                    .header(header::ACCEPT_ENCODING, "gzip, br;q=1.0")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(res.headers()[header::CONTENT_ENCODING], "br");
        let chunk = res
            .into_body()
            .into_data_stream()
            .next()
            .await
            .unwrap()
            .unwrap();

        // The stream is unfinished, so the decoder stops with an error after
        // handing over everything the flush made decodable.
        let mut out = Vec::new();
        let _ = brotli::Decompressor::new(&chunk[..], 4096).read_to_end(&mut out);
        assert!(
            String::from_utf8(out)
                .unwrap()
                .contains("datastar-patch-elements")
        );
    }

    #[tokio::test]
    async fn the_table_keeps_the_newest_rows_and_enforces_its_checks() {
        let db = test_state().await.db;
        for i in 0..KEEP + 10 {
            insert_message(&db, &format!("msg {i}")).await.unwrap();
        }
        let s = stats(&db).await.unwrap();
        assert_eq!(s.total, KEEP);
        assert_eq!(
            recent_messages(&db).await.unwrap()[0].body,
            format!("msg {}", KEEP + 9)
        );

        // The CHECK constraint in the migration is the last line of defence.
        assert!(insert_message(&db, &"x".repeat(501)).await.is_err());

        assert_eq!(clear_messages(&db).await.unwrap(), KEEP as u64);
        assert_eq!(stats(&db).await.unwrap().last_at, None);
    }
}
