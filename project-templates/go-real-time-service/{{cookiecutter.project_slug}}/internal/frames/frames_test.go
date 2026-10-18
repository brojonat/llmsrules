package frames

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

// countingView renders "<key>#<n>" and counts its renders per key.
type countingView struct {
	mu    sync.Mutex
	calls map[string]int
}

func (v *countingView) render(_ context.Context, key string) ([]byte, error) {
	v.mu.Lock()
	defer v.mu.Unlock()
	v.calls[key]++
	return fmt.Appendf(nil, "%s#%d", key, v.calls[key]), nil
}

func newTestRenderer(t *testing.T) (*Renderer, *countingView) {
	t.Helper()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	r := New(10*time.Millisecond, logger, prometheus.NewRegistry())
	v := &countingView{calls: make(map[string]int)}
	r.Handle("board/", v.render)
	return r, v
}

func subscribe(t *testing.T, r *Renderer, key string) *Sub {
	t.Helper()
	s, err := r.Subscribe(key)
	if err != nil {
		t.Fatalf("subscribe %q: %v", key, err)
	}
	t.Cleanup(s.Close)
	return s
}

func TestWritesInOneTickCoalesce(t *testing.T) {
	r, v := newTestRenderer(t)
	subscribe(t, r, "board/a")
	subscribe(t, r, "board/a") // second tab on the same view

	for range 100 {
		r.MarkDirty("board/a")
	}
	r.step(context.Background(), time.Now())

	if got := v.calls["board/a"]; got != 1 {
		t.Fatalf("100 writes and 2 viewers in one tick should be 1 render, got %d", got)
	}
}

func TestUnwatchedViewsAreNotRendered(t *testing.T) {
	r, v := newTestRenderer(t)

	r.MarkDirty("board/nobody")
	r.step(context.Background(), time.Now())

	if got := v.calls["board/nobody"]; got != 0 {
		t.Fatalf("a view with no subscribers should not render, got %d renders", got)
	}
}

func TestSubscribeRendersFresh(t *testing.T) {
	r, v := newTestRenderer(t)

	first := subscribe(t, r, "board/a")
	r.step(context.Background(), time.Now())
	first.Close()

	second := subscribe(t, r, "board/a")
	r.step(context.Background(), time.Now())

	html, _ := second.Latest()
	if string(html) != "board/a#2" || v.calls["board/a"] != 2 {
		t.Fatalf("a new subscriber should get a fresh render, got %q after %d renders", html, v.calls["board/a"])
	}
}

func TestUnknownKeyIsRejected(t *testing.T) {
	r, _ := newTestRenderer(t)
	if _, err := r.Subscribe("nope"); err == nil {
		t.Fatal("subscribing to a key with no route should fail")
	}
}

func TestSlowStreamSkipsToNewestFrame(t *testing.T) {
	r, _ := newTestRenderer(t)
	s := subscribe(t, r, "board/a")

	// Three ticks land while the stream is busy elsewhere.
	for range 3 {
		r.MarkDirty("board/a")
		r.step(context.Background(), time.Now())
	}

	ctx, cancel := context.WithCancel(context.Background())
	var sent []string
	err := s.Stream(ctx, func(b []byte) error {
		sent = append(sent, string(b))
		cancel()
		return nil
	})
	if err != nil {
		t.Fatalf("stream: %v", err)
	}
	if len(sent) != 1 || sent[0] != "board/a#3" {
		t.Fatalf("a slow stream should send only the newest frame, sent %q", sent)
	}
}

func TestEveryRerendersWithoutWrites(t *testing.T) {
	r, v := newTestRenderer(t)
	r.Handle("clock", v.render, Every(time.Second))
	subscribe(t, r, "clock")

	start := time.Now()
	// Subscribing marks the key; half a second later is too soon to resample;
	// a second and a half later is due.
	r.step(context.Background(), start)
	r.step(context.Background(), start.Add(500*time.Millisecond))
	r.step(context.Background(), start.Add(1500*time.Millisecond))

	if got := v.calls["clock"]; got != 2 {
		t.Fatalf("expected 2 renders (subscribe + one interval), got %d", got)
	}
}

func TestOverrunStatsSummarizeOneWindow(t *testing.T) {
	o := overrunStats{window: time.Second}
	budget := 100 * time.Millisecond
	now := time.Now()

	if _, ok := o.record(50*time.Millisecond, budget, now); ok {
		t.Fatal("a tick within budget should not open a window")
	}

	tick := []time.Duration{
		300 * time.Millisecond,
		100 * time.Millisecond,
		100 * time.Millisecond,
	}
	for i, d := range tick {
		if _, ok := o.record(d, budget, now.Add(time.Duration(i)*100*time.Millisecond)); ok {
			t.Fatal("window should still be open")
		}
	}

	s, ok := o.record(100*time.Millisecond, budget, now.Add(time.Second))
	if !ok {
		t.Fatal("window should close after one second")
	}
	if s.n != 4 || s.max != 300*time.Millisecond || s.p50 != 100*time.Millisecond {
		t.Fatalf("unexpected summary %+v", s)
	}
}
