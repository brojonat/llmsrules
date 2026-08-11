package todos

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/delaneyj/toolbelt/id"
	"github.com/gorilla/sessions"
	"github.com/nats-io/nats.go/jetstream"

	"{{cookiecutter.go_mod}}/internal/broker"
)

const (
	bucketName  = "todos"
	bucketTTL   = time.Hour
	sessionName = "todos-session"
)

// Service owns the board state. Boards live in a NATS KV bucket keyed by
// session ID, which is what makes the read path a watch rather than a poll.
type Service struct {
	kv       jetstream.KeyValue
	sessions sessions.Store
}

func NewService(ctx context.Context, b *broker.Broker, store sessions.Store) (*Service, error) {
	kv, err := b.KV(ctx, bucketName, bucketTTL)
	if err != nil {
		return nil, err
	}
	return &Service{kv: kv, sessions: store}, nil
}

// EnsureSession issues the session cookie if the caller does not have one yet.
//
// The page handler calls this before rendering so that the cookie is already
// set by the time the browser opens its SSE stream and starts firing
// mutations. Leaving it to those requests instead would let a mutation that
// races the stream's response headers create a second session, and the user
// would watch a board that nothing was writing to.
func (s *Service) EnsureSession(w http.ResponseWriter, r *http.Request) (string, error) {
	return s.sessionID(w, r)
}

// Board returns the caller's board, seeding and persisting a fresh one on
// first contact. It also issues the session cookie, so it must be called
// before anything is written to w.
func (s *Service) Board(w http.ResponseWriter, r *http.Request) (string, *Board, error) {
	sessionID, err := s.sessionID(w, r)
	if err != nil {
		return "", nil, err
	}

	entry, err := s.kv.Get(r.Context(), sessionID)
	if err != nil {
		if err != jetstream.ErrKeyNotFound {
			return "", nil, fmt.Errorf("reading board: %w", err)
		}
		board := NewBoard()
		if err := s.Save(r.Context(), sessionID, board); err != nil {
			return "", nil, err
		}
		return sessionID, board, nil
	}

	board := &Board{}
	if err := json.Unmarshal(entry.Value(), board); err != nil {
		return "", nil, fmt.Errorf("decoding board: %w", err)
	}
	return sessionID, board, nil
}

// Save writes the board back, which is what wakes up every watcher on this
// session -- including the caller's own SSE stream. Handlers therefore never
// render a response themselves; they mutate and save.
func (s *Service) Save(ctx context.Context, sessionID string, board *Board) error {
	b, err := json.Marshal(board)
	if err != nil {
		return fmt.Errorf("encoding board: %w", err)
	}
	if _, err := s.kv.Put(ctx, sessionID, b); err != nil {
		return fmt.Errorf("writing board: %w", err)
	}
	return nil
}

// Watch streams updates for one session. The caller must Stop the watcher.
func (s *Service) Watch(ctx context.Context, sessionID string) (jetstream.KeyWatcher, error) {
	w, err := s.kv.Watch(ctx, sessionID)
	if err != nil {
		return nil, fmt.Errorf("watching board: %w", err)
	}
	return w, nil
}

func (s *Service) sessionID(w http.ResponseWriter, r *http.Request) (string, error) {
	// A decode failure (rotated SESSION_SECRET, tampered cookie) still yields a
	// usable new session, so treat it as a cache miss rather than an error.
	sess, _ := s.sessions.Get(r, sessionName)

	if existing, ok := sess.Values["id"].(string); ok && existing != "" {
		return existing, nil
	}

	ident := id.NextEncodedID()
	sess.Values["id"] = ident
	if err := sess.Save(r, w); err != nil {
		return "", fmt.Errorf("saving session: %w", err)
	}
	return ident, nil
}
