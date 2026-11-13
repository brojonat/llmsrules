//! One shared view, sampled: host stats. Every viewer sees the same thing, so
//! there is one key, `monitor`, and one sample + render per interval however
//! many tabs are open. Nothing writes host stats, so instead of being marked
//! dirty the view re-renders on a timer (`every`). The shape for dashboards
//! and live feeds.

use std::{
    sync::{Arc, Mutex, Weak},
    time::Duration,
};

use anyhow::Context;
use axum::{Router, extract::State, http::HeaderMap, response::Response, routing::get};
use maud::{Markup, html};
use sysinfo::System;

use crate::{
    app::{AppError, AppState, layout},
    frames::{Renderer, render_fn},
    stream::sse,
};

pub const KEY: &str = "monitor";

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/monitor", get(page))
        .route("/monitor/stream", get(stream))
}

pub fn register(renderer: &Arc<Renderer>, every: Duration) -> anyhow::Result<()> {
    // CPU usage is a difference between two refreshes, so the System lives
    // across renders. A std Mutex: it is never held across an .await.
    let sys = Arc::new(Mutex::new(System::new().context("reading host stats")?));
    // Weak: the renderer owns this closure, so a strong reference would be a cycle.
    let weak: Weak<Renderer> = Arc::downgrade(renderer);
    let render = render_fn(move |_key| {
        let stats = sample(&sys);
        let viewers = weak.upgrade().map_or(0, |r| r.viewers(KEY));
        async move { Ok(view(&stats, viewers).into_string()) }
    });
    renderer.handle(KEY, render, Some(every));
    Ok(())
}

struct Stats {
    cpu: f32,
    used: u64,
    total: u64,
    load: [f64; 3],
    uptime: u64,
}

fn sample(sys: &Mutex<System>) -> Stats {
    let mut sys = sys.lock().unwrap();
    sys.refresh_cpu_usage();
    sys.refresh_memory();
    // Not every platform reports these; zeros beat failing the whole view.
    let load = System::load_average().map_or([0.0; 3], |l| [l.one, l.five, l.fifteen]);
    Stats {
        cpu: sys.global_cpu_usage(),
        used: sys.used_memory(),
        total: sys.total_memory(),
        load,
        uptime: System::uptime().unwrap_or(0),
    }
}

fn view(s: &Stats, viewers: usize) -> Markup {
    let gib = |b: u64| b as f64 / (1u64 << 30) as f64;
    let mem_pct = if s.total == 0 {
        0.0
    } else {
        s.used as f64 / s.total as f64 * 100.0
    };
    html! {
        section #monitor .cards {
            div .card {
                h2 { "CPU" }
                p .big { (format!("{:.0}%", s.cpu)) }
                meter min="0" max="100" value=(s.cpu) {}
            }
            div .card {
                h2 { "Memory" }
                p .big { (format!("{:.1} / {:.1} GiB", gib(s.used), gib(s.total))) }
                meter min="0" max="100" value=(mem_pct) {}
            }
            div .card {
                h2 { "Load" }
                p .big { (format!("{:.2} {:.2} {:.2}", s.load[0], s.load[1], s.load[2])) }
            }
            div .card {
                h2 { "Uptime" }
                p .big { (format!("{}h {}m", s.uptime / 3600, s.uptime % 3600 / 60)) }
            }
            div .card {
                h2 { "Watching" }
                p .big { (viewers) }
                p .hint { "open streams on this view" }
            }
        }
    }
}

async fn page() -> Markup {
    layout(
        "Monitor",
        "Monitor",
        html! {
            h1 { "Monitor" }
            p .hint { "One render per interval, shared by every tab." }
            section #monitor data-init="@get('/monitor/stream', {openWhenHidden: true})" {}
        },
    )
}

async fn stream(State(app): State<AppState>, headers: HeaderMap) -> Result<Response, AppError> {
    let frames = app.renderer.subscribe(KEY)?;
    Ok(sse(frames, app.shutdown.clone(), &headers))
}

#[cfg(test)]
mod tests {
    use futures_util::StreamExt;

    use crate::app::tests::{open, test_state};

    #[tokio::test]
    async fn the_shared_view_counts_its_viewers_and_keeps_sampling() {
        let state = test_state().await;
        let mut a = Box::pin(open(&state, "/monitor/stream").await);
        let _b = Box::pin(open(&state, "/monitor/stream").await);
        let first = a.next().await.unwrap();
        assert!(first.contains("CPU") && first.contains("Memory"), "{first}");
        // Re-rendered on the timer with nothing marking it dirty.
        let later = a.next().await.unwrap();
        assert!(
            later.contains("<p class=\"big\">2</p>"),
            "two viewers: {later}"
        );
    }
}
