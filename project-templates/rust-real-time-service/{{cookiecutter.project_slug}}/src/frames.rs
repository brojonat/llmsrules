//! Renders views on a fixed tick and hands every open stream the newest frame
//! of the view it is watching.
//!
//! This is immediate-mode rendering on the server: a frame is the whole HTML of
//! a view, Datastar morphs it in, and per-connection compression ships only
//! what changed. The tick is what keeps the cost bounded:
//!
//! - Writes only mark a view dirty. A hundred writes inside one tick are one
//!   render, so renders per second never exceed views x tick rate, however
//!   many writes or viewers there are.
//! - A tick that overruns its budget makes the interval skip the ticks it
//!   missed. The next render reads the latest state, so the frames in between
//!   simply never exist: the server sheds frame rate instead of piling up work.
//! - Each view's frames go out on a `watch` channel, which holds one value. The
//!   renderer overwrites it and never waits on a client, so a slow connection
//!   skips frames instead of queueing them. That is safe because every frame is
//!   the whole view: dropping one loses nothing the next one does not carry.
//!
//! Views are addressed by string keys ("todos/<session>", "monitor"). Features
//! register a render function for a key prefix with `handle`. Only keys with at
//! least one open stream are rendered, and subscribing marks the key dirty, so
//! a new viewer always gets a fresh frame and nothing outlives its viewers.
//! Unsubscribing is dropping the receiver.

use std::{
    collections::{HashMap, HashSet},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use futures_util::future::BoxFuture;
use prometheus_client::{
    metrics::{
        counter::Counter,
        gauge::Gauge,
        histogram::{Histogram, exponential_buckets},
    },
    registry::Registry,
};
use tokio::{sync::watch, time::MissedTickBehavior};
use tokio_util::sync::CancellationToken;

/// The newest frame of a view; `None` until its first render.
pub type Frame = Option<Arc<str>>;

/// Renders the whole view for a key from current state.
pub type RenderFn = Arc<dyn Fn(String) -> BoxFuture<'static, anyhow::Result<String>> + Send + Sync>;

/// Wraps an async fn as a `RenderFn`.
pub fn render_fn<F, Fut>(f: F) -> RenderFn
where
    F: Fn(String) -> Fut + Send + Sync + 'static,
    Fut: Future<Output = anyhow::Result<String>> + Send + 'static,
{
    Arc::new(move |key| Box::pin(f(key)))
}

#[derive(Debug, thiserror::Error)]
#[error("no view registered for {0:?}")]
pub struct UnknownView(String);

struct Route {
    prefix: String,
    render: RenderFn,
    every: Option<Duration>,
    last: Option<Instant>,
}

#[derive(Default)]
struct Inner {
    routes: Vec<Route>,
    dirty: HashSet<String>,
    views: HashMap<String, watch::Sender<Frame>>,
}

pub struct Renderer {
    tick: Duration,
    inner: Mutex<Inner>,
    metrics: Metrics,
}

struct Metrics {
    tick_seconds: Histogram,
    overruns: Counter,
    subscribers: Gauge,
    render_errors: Counter,
}

impl Renderer {
    pub fn new(tick: Duration, registry: &mut Registry) -> Arc<Self> {
        let metrics = Metrics {
            tick_seconds: Histogram::new(exponential_buckets(0.0005, 2.0, 14)),
            overruns: Counter::default(),
            subscribers: Gauge::default(),
            render_errors: Counter::default(),
        };
        let r = registry.sub_registry_with_prefix("frames");
        r.register(
            "tick_duration_seconds",
            "Time to render one tick",
            metrics.tick_seconds.clone(),
        );
        r.register(
            "tick_overruns",
            "Ticks that took longer than the budget",
            metrics.overruns.clone(),
        );
        r.register("subscribers", "Open streams", metrics.subscribers.clone());
        r.register(
            "render_errors",
            "Renders that failed",
            metrics.render_errors.clone(),
        );
        Arc::new(Self {
            tick,
            inner: Mutex::new(Inner::default()),
            metrics,
        })
    }

    /// Registers `render` for every key starting with `prefix`; the longest
    /// matching prefix wins. With `every`, subscribed keys under the prefix
    /// re-render at least that often, for views whose source is sampled rather
    /// than written (host stats).
    pub fn handle(&self, prefix: &str, render: RenderFn, every: Option<Duration>) {
        let mut inner = self.inner.lock().unwrap();
        inner.routes.push(Route {
            prefix: prefix.to_owned(),
            render,
            every,
            last: None,
        });
        inner
            .routes
            .sort_by_key(|r| std::cmp::Reverse(r.prefix.len()));
    }

    /// Schedules `key` for a render on the next tick. Cheap and never blocks,
    /// so call it wherever a write happens; repeated marks coalesce.
    pub fn mark_dirty(&self, key: &str) {
        self.inner.lock().unwrap().dirty.insert(key.to_owned());
    }

    /// Registers interest in `key` and schedules its first render. Drop the
    /// receiver to unsubscribe.
    pub fn subscribe(&self, key: &str) -> Result<watch::Receiver<Frame>, UnknownView> {
        let mut inner = self.inner.lock().unwrap();
        if !inner.routes.iter().any(|r| key.starts_with(&r.prefix)) {
            return Err(UnknownView(key.to_owned()));
        }
        inner.dirty.insert(key.to_owned());
        let rx = match inner.views.get(key) {
            Some(tx) => tx.subscribe(),
            None => {
                let (tx, rx) = watch::channel(None);
                inner.views.insert(key.to_owned(), tx);
                rx
            }
        };
        Ok(rx)
    }

    /// Number of open streams on `key`.
    pub fn viewers(&self, key: &str) -> usize {
        let inner = self.inner.lock().unwrap();
        inner.views.get(key).map_or(0, |tx| tx.receiver_count())
    }

    /// Ticks until `shutdown` is cancelled.
    pub async fn run(self: Arc<Self>, shutdown: CancellationToken) {
        let mut interval = tokio::time::interval(self.tick);
        interval.set_missed_tick_behavior(MissedTickBehavior::Skip);
        let mut stats = OverrunStats::new(Duration::from_secs(20));
        loop {
            tokio::select! {
                () = shutdown.cancelled() => return,
                _ = interval.tick() => {
                    let now = Instant::now();
                    self.step(now).await;
                    let took = now.elapsed();
                    self.metrics.tick_seconds.observe(took.as_secs_f64());
                    if took > self.tick {
                        self.metrics.overruns.inc();
                    }
                    if let Some(s) = stats.record(took, self.tick, now) {
                        tracing::warn!(
                            budget = ?self.tick, ticks = s.n, p50 = ?s.p50, p95 = ?s.p95,
                            p99 = ?s.p99, max = ?s.max, "frames: tick overrun"
                        );
                    }
                }
            }
        }
    }

    /// Renders every dirty key that has a viewer. Rendering is serial; if the
    /// overrun log says one task is not enough, render the jobs concurrently
    /// here (a `JoinSet`) and wait for all of them before returning.
    pub(crate) async fn step(&self, now: Instant) {
        let jobs: Vec<(String, RenderFn)> = {
            let mut inner = self.inner.lock().unwrap();
            let Inner {
                routes,
                dirty,
                views,
            } = &mut *inner;

            // Forget views nobody watches. Whoever subscribes next creates the
            // channel again and marks the key dirty, so this never serves stale HTML.
            views.retain(|_, tx| tx.receiver_count() > 0);
            let open: usize = views.values().map(|tx| tx.receiver_count()).sum();
            self.metrics.subscribers.set(open as i64);

            for route in routes.iter_mut() {
                let Some(every) = route.every else { continue };
                if route
                    .last
                    .is_some_and(|last| now.duration_since(last) < every)
                {
                    continue;
                }
                route.last = Some(now);
                dirty.extend(
                    views
                        .keys()
                        .filter(|k| k.starts_with(&route.prefix))
                        .cloned(),
                );
            }

            dirty
                .drain()
                .filter(|key| views.contains_key(key))
                .filter_map(|key| {
                    let route = routes.iter().find(|r| key.starts_with(&r.prefix))?;
                    Some((key, route.render.clone()))
                })
                .collect()
        };

        for (key, render) in jobs {
            match render(key.clone()).await {
                Ok(html) => self.publish(&key, html.into()),
                Err(e) => {
                    self.metrics.render_errors.inc();
                    tracing::error!(%key, error = %e, "frames: render");
                }
            }
        }
    }

    fn publish(&self, key: &str, html: Arc<str>) {
        let inner = self.inner.lock().unwrap();
        if let Some(tx) = inner.views.get(key) {
            // send_replace: never fails and never waits, whoever is listening.
            tx.send_replace(Some(html));
        }
    }
}

/// Collects tick durations over a window and, if any tick overran, summarizes
/// them once at the end of the window: one log line per window, not per tick.
struct OverrunStats {
    window: Duration,
    start: Option<Instant>,
    samples: Vec<Duration>,
    overran: bool,
}

struct Summary {
    n: usize,
    p50: Duration,
    p95: Duration,
    p99: Duration,
    max: Duration,
}

impl OverrunStats {
    fn new(window: Duration) -> Self {
        Self {
            window,
            start: None,
            samples: Vec::new(),
            overran: false,
        }
    }

    fn record(&mut self, took: Duration, budget: Duration, now: Instant) -> Option<Summary> {
        let start = *self.start.get_or_insert(now);
        self.samples.push(took);
        self.overran |= took > budget;
        if now.duration_since(start) < self.window {
            return None;
        }
        let (overran, mut samples) = (self.overran, std::mem::take(&mut self.samples));
        (self.start, self.overran) = (None, false);
        if !overran {
            return None;
        }
        samples.sort();
        let at = |q: f64| samples[((samples.len() - 1) as f64 * q).round() as usize];
        Some(Summary {
            n: samples.len(),
            p50: at(0.50),
            p95: at(0.95),
            p99: at(0.99),
            max: *samples.last().unwrap(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    fn counting_renderer(every: Option<Duration>) -> (Arc<Renderer>, Arc<AtomicUsize>) {
        let r = Renderer::new(Duration::from_millis(100), &mut Registry::default());
        let calls = Arc::new(AtomicUsize::new(0));
        let c = calls.clone();
        r.handle(
            "view/",
            render_fn(move |key| {
                let n = c.fetch_add(1, Ordering::SeqCst) + 1;
                async move { Ok(format!("{key} #{n}")) }
            }),
            every,
        );
        (r, calls)
    }

    #[tokio::test]
    async fn marks_coalesce_and_only_watched_views_render() {
        let (r, calls) = counting_renderer(None);
        assert!(r.subscribe("other").is_err(), "unregistered prefix");

        r.mark_dirty("view/unwatched");
        let rx = r.subscribe("view/a").unwrap();
        for _ in 0..100 {
            r.mark_dirty("view/a");
        }
        r.step(Instant::now()).await;
        assert_eq!(
            calls.load(Ordering::SeqCst),
            1,
            "one render for 100 marks, none unwatched"
        );
        assert_eq!(rx.borrow().as_deref(), Some("view/a #1"));

        r.step(Instant::now()).await;
        assert_eq!(
            calls.load(Ordering::SeqCst),
            1,
            "nothing dirty, nothing rendered"
        );
    }

    #[tokio::test]
    async fn a_slow_stream_skips_to_the_newest_frame() {
        let (r, _) = counting_renderer(None);
        let mut rx = r.subscribe("view/a").unwrap();
        for _ in 0..3 {
            r.mark_dirty("view/a");
            r.step(Instant::now()).await;
        }
        // Three frames were published while nobody read; only the last is there.
        rx.changed().await.unwrap();
        assert_eq!(rx.borrow_and_update().as_deref(), Some("view/a #3"));
        assert!(!rx.has_changed().unwrap());
    }

    #[tokio::test]
    async fn dropping_the_receiver_unsubscribes() {
        let (r, calls) = counting_renderer(None);
        let rx = r.subscribe("view/a").unwrap();
        assert_eq!(r.viewers("view/a"), 1);
        drop(rx);
        r.step(Instant::now()).await;
        assert_eq!(r.viewers("view/a"), 0);
        assert_eq!(
            calls.load(Ordering::SeqCst),
            0,
            "the subscribe mark was dropped too"
        );
    }

    #[tokio::test]
    async fn every_rerenders_sampled_views() {
        let (r, calls) = counting_renderer(Some(Duration::from_millis(500)));
        let _rx = r.subscribe("view/a").unwrap();
        let t0 = Instant::now();
        r.step(t0).await; // subscribe mark (and the first `every`)
        r.step(t0 + Duration::from_millis(100)).await; // too soon
        r.step(t0 + Duration::from_millis(600)).await; // due
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn overruns_are_summarized_once_per_window() {
        let mut s = OverrunStats::new(Duration::from_secs(20));
        let t0 = Instant::now();
        let budget = Duration::from_millis(100);
        assert!(s.record(Duration::from_millis(10), budget, t0).is_none());
        assert!(
            s.record(
                Duration::from_millis(300),
                budget,
                t0 + Duration::from_secs(1)
            )
            .is_none()
        );
        let sum = s
            .record(
                Duration::from_millis(20),
                budget,
                t0 + Duration::from_secs(21),
            )
            .unwrap();
        assert_eq!((sum.n, sum.max), (3, Duration::from_millis(300)));
        // A quiet window says nothing.
        let t1 = t0 + Duration::from_secs(30);
        s.record(Duration::from_millis(10), budget, t1);
        assert!(
            s.record(
                Duration::from_millis(10),
                budget,
                t1 + Duration::from_secs(21)
            )
            .is_none()
        );
    }
}
