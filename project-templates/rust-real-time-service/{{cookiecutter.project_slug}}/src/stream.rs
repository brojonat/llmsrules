//! Turns a view's frames into an SSE response: one `datastar-patch-elements`
//! event per frame, Brotli-compressed when the browser accepts it.

use std::{convert::Infallible, io::Write};

use axum::{
    body::{Body, Bytes},
    http::{HeaderMap, HeaderValue, header},
    response::{IntoResponse, Response},
};
use datastar::prelude::PatchElements;
use tokio::sync::watch;
use tokio_util::sync::CancellationToken;

use crate::frames::Frame;

/// The whole read side of a live view. Sends the current frame, then each new
/// one, until the client leaves (axum drops the body, which drops `frames` and
/// so unsubscribes) or the server shuts down.
pub fn sse(
    frames: watch::Receiver<Frame>,
    shutdown: CancellationToken,
    headers: &HeaderMap,
) -> Response {
    let brotli = accepts_brotli(headers);
    let state = (frames, shutdown, Encoder::new(brotli), true);
    let body = futures_util::stream::unfold(
        state,
        |(mut frames, shutdown, mut encoder, first)| async move {
            if !first {
                next_frame(&mut frames, &shutdown).await?;
            }
            // borrow_and_update marks the value seen. If several frames were
            // published since the last send, this is the newest; the rest are skipped.
            let html = loop {
                if let Some(html) = frames.borrow_and_update().clone() {
                    break html;
                }
                next_frame(&mut frames, &shutdown).await?; // no first render yet
            };
            let event = PatchElements::new(&*html).as_datastar_event().to_string();
            let chunk = encoder.encode(event.as_bytes());
            Some((
                Ok::<_, Infallible>(chunk),
                (frames, shutdown, encoder, false),
            ))
        },
    );
    sse_response(Body::from_stream(body), brotli)
}

/// Waits for a new frame; `None` ends the stream.
async fn next_frame(
    frames: &mut watch::Receiver<Frame>,
    shutdown: &CancellationToken,
) -> Option<()> {
    tokio::select! {
        res = frames.changed() => res.ok(),
        () = shutdown.cancelled() => None,
    }
}

pub fn accepts_brotli(headers: &HeaderMap) -> bool {
    headers
        .get_all(header::ACCEPT_ENCODING)
        .iter()
        .filter_map(|v| v.to_str().ok())
        .flat_map(|v| v.split(','))
        .any(|enc| enc.split(';').next().is_some_and(|e| e.trim() == "br"))
}

/// One Brotli context per stream: every frame is compressed against the ones
/// before it, so an unchanged region costs a few bytes. Quality and window set
/// the memory each open stream holds. Measured with the `brotli` crate, per
/// stream after 300 frames:
///
/// | frame | quality 5, lgwin 17   | quality 1, lgwin 17   |
/// |-------|-----------------------|-----------------------|
/// | 1 KB  | 1.4 MiB, 91 B/frame   | 17 KiB, 267 B/frame   |
/// | 16 KB | 1.6 MiB, 1.2 KB/frame | 170 KiB, 1.7 KB/frame |
/// | 64 KB | 2.2 MiB, 4.6 KB/frame | 650 KiB, 7.3 KB/frame |
///
/// Quality 1 holds a tenth of the memory or less, paying in bandwidth on
/// small frames; open streams, not bytes, are what a crowd multiplies. Keep 2^lgwin at
/// least twice the largest frame. Avoid quality 5-9 with lgwin <= 16 in this
/// crate: it switches hashers and holds ~15 MiB per stream.
pub enum Encoder {
    Identity,
    Brotli(Box<brotli::CompressorWriter<Vec<u8>>>),
}

impl Encoder {
    pub fn new(brotli: bool) -> Self {
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

    /// Compress one event and flush, so the browser can decode it now.
    pub fn encode(&mut self, event: &[u8]) -> Bytes {
        match self {
            Self::Identity => Bytes::copy_from_slice(event),
            Self::Brotli(w) => {
                w.write_all(event).expect("in-memory write");
                w.flush().expect("in-memory flush");
                Bytes::from(std::mem::take(w.get_mut()))
            }
        }
    }
}

pub fn sse_response(body: Body, brotli: bool) -> Response {
    let mut res = body.into_response();
    let h = res.headers_mut();
    h.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/event-stream"),
    );
    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-cache"));
    h.insert(header::VARY, HeaderValue::from_static("accept-encoding"));
    if brotli {
        h.insert(header::CONTENT_ENCODING, HeaderValue::from_static("br"));
    }
    res
}
