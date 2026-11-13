//! Per-session todos: the feature to copy for most work.
//!
//! The page renders an empty placeholder whose `data-init` opens the stream.
//! The stream subscribes to the view `todos/<session>` and sends frames. Writes
//! change SQLite, mark that view dirty, and return 204; the next tick renders
//! it once and every tab on the session gets the frame. A write from another
//! tab, or a background job, reaches the screen by exactly the same path.

use axum::{
    Extension, Router,
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::Response,
    routing::{get, post},
};
use datastar::axum::ReadSignals;
use maud::{Markup, html};
use serde::Deserialize;
use sqlx::{FromRow, SqlitePool, sqlite::SqliteQueryResult};

use crate::{
    app::{AppError, AppState, Session, layout},
    frames::{Renderer, render_fn},
    stream::sse,
};

pub fn key(session: &str) -> String {
    format!("todos/{session}")
}

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/todos", get(page).post(add))
        .route("/todos/stream", get(stream))
        .route("/todos/{id}/toggle", post(toggle))
        .route("/todos/{id}/delete", post(delete))
        .route("/todos/clear-done", post(clear_done))
}

/// Registers the render function for every `todos/<session>` key.
pub fn register(renderer: &Renderer, db: SqlitePool) {
    let render = render_fn(move |key: String| {
        let db = db.clone();
        async move {
            let session = key.strip_prefix("todos/").unwrap_or_default();
            Ok(view(&load(&db, session).await?).into_string())
        }
    });
    renderer.handle("todos/", render, None);
}

// --- SQL -------------------------------------------------------------------

#[derive(FromRow)]
struct Todo {
    id: i64,
    text: String,
    done: bool,
}

async fn load(db: &SqlitePool, session: &str) -> Result<Vec<Todo>, sqlx::Error> {
    sqlx::query_as("SELECT id, text, done FROM todos WHERE session = ? ORDER BY id")
        .bind(session)
        .fetch_all(db)
        .await
}

// --- View ------------------------------------------------------------------

/// The whole live region. Its id matches the placeholder, so the first frame
/// replaces it and later frames morph into it.
fn view(todos: &[Todo]) -> Markup {
    let left = todos.iter().filter(|t| !t.done).count();
    html! {
        section #todos {
            form data-on:submit__prevent="@post('/todos'); $text = ''" {
                input data-bind:text placeholder="What needs doing?" autocomplete="off"
                    aria-label="New todo" maxlength="200";
                button type="submit" { "Add" }
            }
            ul .todos {
                @for t in todos {
                    li #{"todo-" (t.id)} .done[t.done] {
                        button .check aria-label="Toggle"
                            data-on:click={ "@post('/todos/" (t.id) "/toggle')" } {
                            @if t.done { "☑" } @else { "☐" }
                        }
                        span { (t.text) }
                        button .delete aria-label="Delete"
                            data-on:click={ "@post('/todos/" (t.id) "/delete')" } { "×" }
                    }
                }
            }
            footer {
                (left) " left"
                @if todos.iter().any(|t| t.done) {
                    button data-on:click="@post('/todos/clear-done')" { "Clear done" }
                }
            }
        }
    }
}

// --- Handlers ----------------------------------------------------------------

async fn page() -> Markup {
    layout(
        "Todos",
        "Todos",
        html! {
            h1 { "Todos" }
            p .hint { "Per session: open a second tab and they stay in sync." }
            // The one long-lived read. openWhenHidden keeps it open when the
            // tab is backgrounded, so the tab never goes stale.
            section #todos data-init="@get('/todos/stream', {openWhenHidden: true})" {}
        },
    )
}

async fn stream(
    State(app): State<AppState>,
    Extension(Session(session)): Extension<Session>,
    headers: HeaderMap,
) -> Result<Response, AppError> {
    let frames = app.renderer.subscribe(&key(&session))?;
    Ok(sse(frames, app.shutdown.clone(), &headers))
}

#[derive(Deserialize)]
struct NewTodo {
    #[serde(default)]
    text: String,
}

async fn add(
    State(app): State<AppState>,
    Extension(Session(session)): Extension<Session>,
    ReadSignals(signals): ReadSignals<NewTodo>,
) -> Result<StatusCode, AppError> {
    let text = signals.text.trim().to_owned();
    if text.is_empty() || text.chars().count() > 200 {
        return Ok(StatusCode::NO_CONTENT);
    }
    let db = app.db.clone();
    let s = session.clone();
    write(&app, &session, async move {
        sqlx::query("INSERT INTO todos (session, text) VALUES (?, ?)")
            .bind(s)
            .bind(text)
            .execute(&db)
            .await
    })
    .await
}

async fn toggle(
    State(app): State<AppState>,
    Extension(Session(session)): Extension<Session>,
    Path(id): Path<i64>,
) -> Result<StatusCode, AppError> {
    let db = app.db.clone();
    let s = session.clone();
    write(&app, &session, async move {
        // `AND session = ?`: a session can only touch its own rows.
        sqlx::query("UPDATE todos SET done = NOT done WHERE id = ? AND session = ?")
            .bind(id)
            .bind(s)
            .execute(&db)
            .await
    })
    .await
}

async fn delete(
    State(app): State<AppState>,
    Extension(Session(session)): Extension<Session>,
    Path(id): Path<i64>,
) -> Result<StatusCode, AppError> {
    let db = app.db.clone();
    let s = session.clone();
    write(&app, &session, async move {
        sqlx::query("DELETE FROM todos WHERE id = ? AND session = ?")
            .bind(id)
            .bind(s)
            .execute(&db)
            .await
    })
    .await
}

async fn clear_done(
    State(app): State<AppState>,
    Extension(Session(session)): Extension<Session>,
) -> Result<StatusCode, AppError> {
    let db = app.db.clone();
    let s = session.clone();
    write(&app, &session, async move {
        sqlx::query("DELETE FROM todos WHERE session = ? AND done")
            .bind(s)
            .execute(&db)
            .await
    })
    .await
}

/// Runs a write, then marks the session's view dirty. Both happen in a task of
/// their own: the handler is dropped if the client disconnects, and a drop
/// between the commit and the mark would leave every tab stale.
async fn write<F>(app: &AppState, session: &str, op: F) -> Result<StatusCode, AppError>
where
    F: Future<Output = Result<SqliteQueryResult, sqlx::Error>> + Send + 'static,
{
    let (renderer, key) = (app.renderer.clone(), key(session));
    tokio::spawn(async move {
        op.await?;
        renderer.mark_dirty(&key);
        Ok::<_, sqlx::Error>(())
    })
    .await??;
    Ok(StatusCode::NO_CONTENT)
}

#[cfg(test)]
mod tests {
    use futures_util::StreamExt;

    use crate::app::tests::{open, request, send, test_state};

    #[tokio::test]
    async fn writes_land_on_every_stream_of_the_session() {
        let state = test_state().await;
        let mut tab1 = Box::pin(open(&state, "/todos/stream").await);
        let mut tab2 = Box::pin(open(&state, "/todos/stream").await);
        assert!(tab1.next().await.unwrap().contains("0 left"));
        assert!(tab2.next().await.unwrap().contains("0 left"));

        let (status, _, _) = send(
            &state,
            request("POST", "/todos", r#"{"text":"<b>milk</b>"}"#),
        )
        .await;
        assert_eq!(status, 204);
        for tab in [&mut tab1, &mut tab2] {
            let frame = tab.next().await.unwrap();
            assert!(
                frame.starts_with("event: datastar-patch-elements\n"),
                "{frame}"
            );
            assert!(
                frame.contains("&lt;b&gt;milk&lt;/b&gt;") && frame.contains("1 left"),
                "{frame}"
            );
        }

        let id: i64 = sqlx::query_scalar("SELECT id FROM todos")
            .fetch_one(&state.db)
            .await
            .unwrap();
        send(&state, request("POST", &format!("/todos/{id}/toggle"), "")).await;
        assert!(tab1.next().await.unwrap().contains("0 left"));
        send(&state, request("POST", "/todos/clear-done", "")).await;
        assert!(!tab1.next().await.unwrap().contains("milk"));
    }

    #[tokio::test]
    async fn sessions_cannot_touch_each_others_rows() {
        let state = test_state().await;
        sqlx::query("INSERT INTO todos (session, text) VALUES ('someone-else', 'theirs')")
            .execute(&state.db)
            .await
            .unwrap();
        send(&state, request("POST", "/todos/1/delete", "")).await;
        let n: i64 = sqlx::query_scalar("SELECT count(*) FROM todos")
            .fetch_one(&state.db)
            .await
            .unwrap();
        assert_eq!(n, 1);
    }
}
