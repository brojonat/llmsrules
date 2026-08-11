package counter

import (
	"log/slog"
	"net/http"
	"sync/atomic"

	"github.com/gorilla/sessions"
	"github.com/starfederation/datastar-go/datastar"

	"{{cookiecutter.go_mod}}/internal/httpx"
)

const (
	sessionName = "counter-session"
	countKey    = "count"
)

// Signals are the two values bound in page.templ.
type Signals struct {
	Global uint64 `json:"global"`
	User   uint64 `json:"user"`
}

// Counters holds the process-wide tally.
//
// It is in-memory and therefore per-pod, which is fine because this service
// deploys as a single replica. Scaling out means moving this into the broker.
type Counters struct {
	global   atomic.Uint64
	sessions sessions.Store
}

func NewCounters(store sessions.Store) *Counters {
	return &Counters{sessions: store}
}

func (c *Counters) userCount(r *http.Request) (uint64, *sessions.Session) {
	sess, _ := c.sessions.Get(r, sessionName)
	count, _ := sess.Values[countKey].(uint64)
	return count, sess
}

func handlePage(title string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := Page(title).Render(r.Context(), w); err != nil {
			httpx.WriteJSONError(w, "render failed", http.StatusInternalServerError)
		}
	})
}

// handleData seeds the page with current values on load.
func handleData(c *Counters, logger *slog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		user, _ := c.userCount(r)
		patch(w, r, logger, Signals{Global: c.global.Load(), User: user})
	})
}

func handleIncrementGlobal(c *Counters, logger *slog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		user, _ := c.userCount(r)
		patch(w, r, logger, Signals{Global: c.global.Add(1), User: user})
	})
}

func handleIncrementUser(c *Counters, logger *slog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		user, sess := c.userCount(r)
		user++
		sess.Values[countKey] = user

		// Save before the SSE upgrade: once the stream opens, headers are gone.
		if err := sess.Save(r, w); err != nil {
			logger.ErrorContext(r.Context(), "counter: save session", "error", err)
			httpx.WriteJSONError(w, "internal error", http.StatusInternalServerError)
			return
		}

		patch(w, r, logger, Signals{Global: c.global.Load(), User: user})
	})
}

func patch(w http.ResponseWriter, r *http.Request, logger *slog.Logger, s Signals) {
	if err := datastar.NewSSE(w, r).MarshalAndPatchSignals(s); err != nil {
		logger.DebugContext(r.Context(), "counter: patch signals", "error", err)
	}
}
