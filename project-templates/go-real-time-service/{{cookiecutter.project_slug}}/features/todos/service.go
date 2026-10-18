package todos

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/delaneyj/toolbelt/id"
	"github.com/gorilla/sessions"
	"github.com/nats-io/nats.go/jetstream"

	"{{cookiecutter.go_mod}}/internal/broker"
	"{{cookiecutter.go_mod}}/internal/frames"
)

const (
	bucketName  = "todos"
	bucketTTL   = time.Hour
	sessionName = "todos-session"
	viewPrefix  = "todos/"
)

func viewKey(sessionID string) string { return viewPrefix + sessionID }

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

	board, err := s.load(r.Context(), sessionID)
	if err == jetstream.ErrKeyNotFound {
		board = NewBoard()
		err = s.Save(r.Context(), sessionID, board)
	}
	if err != nil {
		return "", nil, err
	}
	return sessionID, board, nil
}

func (s *Service) load(ctx context.Context, sessionID string) (*Board, error) {
	entry, err := s.kv.Get(ctx, sessionID)
	if err == jetstream.ErrKeyNotFound {
		return nil, err
	}
	if err != nil {
		return nil, fmt.Errorf("reading board: %w", err)
	}

	board := &Board{}
	if err := json.Unmarshal(entry.Value(), board); err != nil {
		return nil, fmt.Errorf("decoding board: %w", err)
	}
	return board, nil
}

// Render is the frames.RenderFunc for "todos/<session id>". It runs on the
// renderer's tick, never in a request.
func (s *Service) Render(ctx context.Context, key string) ([]byte, error) {
	board, err := s.load(ctx, strings.TrimPrefix(key, viewPrefix))
	if err == jetstream.ErrKeyNotFound {
		board = NewBoard() // expired while someone was watching; show a fresh one
	} else if err != nil {
		return nil, err
	}

	var buf bytes.Buffer
	if err := TodosView(NewView(board)).Render(ctx, &buf); err != nil {
		return nil, fmt.Errorf("rendering todos view: %w", err)
	}
	return buf.Bytes(), nil
}

// Save writes the board back. The bucket watcher started by MarkDirtyOnWrite
// sees the write and marks the session's view dirty, and the next tick pushes
// it to every stream on this session -- including the caller's own. Handlers
// therefore never render a response themselves; they mutate and save.
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

// MarkDirtyOnWrite watches the whole bucket and marks the view of every
// written session dirty. One watcher for the bucket, not one per stream: the
// renderer coalesces the marks, so a burst of writes is still one render.
func (s *Service) MarkDirtyOnWrite(ctx context.Context, renderer *frames.Renderer, logger *slog.Logger) error {
	watcher, err := s.kv.WatchAll(ctx, jetstream.UpdatesOnly(), jetstream.IgnoreDeletes())
	if err != nil {
		return fmt.Errorf("watching todos bucket: %w", err)
	}

	go func() {
		defer func() {
			if err := watcher.Stop(); err != nil {
				logger.Debug("todos: stopping bucket watcher", "error", err)
			}
		}()
		for {
			select {
			case <-ctx.Done():
				return
			case entry, open := <-watcher.Updates():
				if !open {
					if ctx.Err() == nil {
						logger.Error("todos: bucket watcher closed; live updates stopped")
					}
					return
				}
				if entry != nil {
					renderer.MarkDirty(viewKey(entry.Key()))
				}
			}
		}
	}()
	return nil
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
