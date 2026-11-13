//! One-shot signal patches: each click opens an SSE response, patches two
//! signals, and closes. No renderer, no database. The shape for cheap
//! interactions that need no shared state.

use std::{
    convert::Infallible,
    time::{SystemTime, UNIX_EPOCH},
};

use axum::{
    Router,
    response::sse::{Event, Sse},
    routing::{get, post},
};
use datastar::{axum::ReadSignals, prelude::PatchSignals};
use futures_util::Stream;
use maud::{Markup, html};
use serde::Deserialize;

use crate::app::{AppState, layout};

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/counter", get(page))
        .route("/counter/increment", post(increment))
}

async fn page() -> Markup {
    layout(
        "Counter",
        "Counter",
        html! {
            h1 { "Counter" }
            p .hint { "The count lives in the tab's signals; the server only computes the next value." }
            section .counter data-signals="{count: 0, at: 0}" {
                p .big data-text="$count" { "0" }
                button data-on:click="@post('/counter/increment')" { "+1" }
                p .hint data-show="$at" data-text="'server answered at ' + new Date($at).toLocaleTimeString()" {}
            }
        },
    )
}

#[derive(Deserialize)]
struct Signals {
    #[serde(default)]
    count: i64,
}

async fn increment(
    ReadSignals(signals): ReadSignals<Signals>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis() as u64);
    let patch = serde_json::json!({ "count": signals.count + 1, "at": at });
    let event = PatchSignals::new(patch.to_string()).write_as_axum_sse_event();
    Sse::new(futures_util::stream::once(async move { Ok(event) }))
}

#[cfg(test)]
mod tests {
    use crate::app::tests::{request, send, test_state};

    #[tokio::test]
    async fn increment_patches_the_signals_and_closes() {
        let state = test_state().await;
        let (status, _, body) = send(
            &state,
            request("POST", "/counter/increment", r#"{"count":41}"#),
        )
        .await;
        assert_eq!(status, 200);
        assert!(
            body.starts_with("event: datastar-patch-signals\n"),
            "{body}"
        );
        assert!(body.contains(r#""count":42"#), "{body}");
    }
}
