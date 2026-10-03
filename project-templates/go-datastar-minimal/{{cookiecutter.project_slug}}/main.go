// {{cookiecutter.project_name}} -- a complete real-time web app in one file.
//
// It follows the Tao of Datastar: the backend owns all state, one long-lived
// SSE request streams the UI down, and short-lived POSTs send commands up.
// That split is CQRS, and it is what makes the app multiplayer for free --
// every connected browser renders from the same server-side state, so a write
// from any of them shows up in all of them.
//
// There is one dependency: the official Datastar Go SDK, which handles the SSE
// wire format, flushing, and signal decoding. The browser gets datastar.js from
// a CDN via one script tag; there is no frontend build step and no codegen.
//
//	go run .   # then open http://localhost:8080 in two tabs
package main

import (
	"bytes"
	"html/template"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"

	"github.com/starfederation/datastar-go/datastar"
)

// ---------------------------------------------------------------------------
// State. The backend is the source of truth; the browser holds none of this.
// ---------------------------------------------------------------------------

type store struct {
	mu       sync.Mutex
	messages []string
	watchers map[chan struct{}]struct{}
}

func newStore() *store {
	return &store{watchers: make(map[chan struct{}]struct{})}
}

func (s *store) list() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.messages...)
}

func (s *store) add(msg string) {
	s.mu.Lock()
	s.messages = append(s.messages, msg)
	s.mu.Unlock()
	s.notify()
}

func (s *store) clear() {
	s.mu.Lock()
	s.messages = nil
	s.mu.Unlock()
	s.notify()
}

// watch registers a listener and returns it along with its cleanup function.
func (s *store) watch() (<-chan struct{}, func()) {
	ch := make(chan struct{}, 1)
	s.mu.Lock()
	s.watchers[ch] = struct{}{}
	s.mu.Unlock()

	return ch, func() {
		s.mu.Lock()
		delete(s.watchers, ch)
		s.mu.Unlock()
	}
}

func (s *store) notify() {
	s.mu.Lock()
	defer s.mu.Unlock()
	for ch := range s.watchers {
		select {
		case ch <- struct{}{}:
		default:
			// A tick is already queued. Watchers re-read current state when
			// they wake, so coalescing here is not a lost update.
		}
	}
}

// ---------------------------------------------------------------------------
// Templates. One source of truth for markup, rendered entirely on the server.
// "board" is both part of the first page load and the fragment pushed on every
// change -- Datastar morphs it in, so there is no separate client-side view.
// ---------------------------------------------------------------------------

{% raw %}var page = template.Must(template.New("page").Parse(`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{.Title}}</title>
<link rel="icon" type="image/png" href="data:image/png;base64,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">
<script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.2/bundles/datastar.js"></script>
<style>
  body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem; }
  form { display: flex; gap: .5rem; margin: 1rem 0; }
  input { flex: 1; padding: .5rem; }
  /* 16px minimum, or iOS Safari zooms the page when the input is focused. */
  input, button { font-size: 1rem; }
  li { padding: .25rem 0; }
  footer { margin-top: 1rem; color: #666; font-size: .875rem; }
</style>
</head>
<!-- The one long-lived read request. It never returns; the server pushes
     every subsequent render down it. openWhenHidden keeps the stream alive
     when the tab is backgrounded -- without it Datastar closes GET streams on
     hide and reconnects on show, so a backgrounded tab goes stale. -->
<body data-init="@get('/updates', {openWhenHidden: true})">
{{template "board" .Messages}}
</body>
</html>
`))

// board is the live region. Every write re-renders this whole element and
// morphs it in: no per-field patching, no diffing by hand.
var board = template.Must(page.New("board").Parse(`<main id="board">
<h1>Messages</h1>
<!-- A command, not a render request. The server answers 204 and the update
     arrives on the SSE stream above. -->
<form data-on:submit__prevent="@post('/add'); $message = ''">
  <input name="message" placeholder="Say something" autocomplete="off" aria-label="Message" data-bind:message>
  <button type="submit">Send</button>
</form>
<ul aria-live="polite">
{{range .}}<li>{{.}}</li>
{{else}}<li><em>No messages yet.</em></li>
{{end}}</ul>
<footer>
{{len .}} message(s) &middot; open a second tab to watch them sync
<button data-on:click="@post('/clear')">Clear</button>
</footer>
</main>
`)){% endraw %}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

func handleIndex(s *store, title string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		data := struct {
			Title    string
			Messages []string
		}{title, s.list()}

		if err := page.Execute(w, data); err != nil {
			log.Printf("render page: %v", err)
		}
	})
}

// handleUpdates is the read side: render current state, then block until
// something changes, forever. It never renders in response to a request.
func handleUpdates(s *store) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// NewSSE writes the SSE headers and flushes every event it sends.
		// Add datastar.WithCompression() to negotiate Brotli/gzip on the
		// stream -- repetitive HTML compresses at ratios around 200:1.
		sse := datastar.NewSSE(w, r)

		changed, stop := s.watch()
		defer stop()

		for {
			var buf bytes.Buffer
			if err := board.Execute(&buf, s.list()); err != nil {
				log.Printf("render board: %v", err)
				return
			}

			// One "data: elements" line per line of HTML; trim so the
			// template's trailing newline does not become an empty one.
			if err := sse.PatchElements(strings.TrimSpace(buf.String())); err != nil {
				return // client went away
			}

			select {
			case <-sse.Context().Done():
				return
			case <-changed:
			}
		}
	})
}

// handleAdd is the write side: mutate and return nothing. The open stream is
// what puts the result on screen.
func handleAdd(s *store) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var signals struct {
			Message string `json:"message"`
		}
		// ReadSignals decodes the browser's signals: a JSON body on writes, a
		// ?datastar= query parameter on reads. Always call it before NewSSE --
		// upgrading the response first closes the body out from under it.
		if err := datastar.ReadSignals(r, &signals); err != nil {
			http.Error(w, "bad signals", http.StatusBadRequest)
			return
		}

		if msg := strings.TrimSpace(signals.Message); msg != "" {
			s.add(msg)
		}
		w.WriteHeader(http.StatusNoContent)
	})
}

func handleClear(s *store) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		s.clear()
		w.WriteHeader(http.StatusNoContent)
	})
}

func main() {
	s := newStore()

	mux := http.NewServeMux()
	mux.Handle("GET /{$}", handleIndex(s, "{{cookiecutter.project_name}}"))
	mux.Handle("GET /updates", handleUpdates(s))
	mux.Handle("POST /add", handleAdd(s))
	mux.Handle("POST /clear", handleClear(s))

	addr := ":8080"
	if port := os.Getenv("PORT"); port != "" {
		addr = ":" + port
	}

	log.Printf("listening on http://localhost%s", addr)
	// No WriteTimeout: it would cut the SSE stream off mid-flight.
	log.Fatal(http.ListenAndServe(addr, mux))
}
