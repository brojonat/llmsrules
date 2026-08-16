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
