// Package frames renders views on a fixed tick and hands every open stream the
// newest frame of the view it is watching.
//
// This is immediate-mode rendering on the server: a frame is the whole HTML of
// a view, Datastar morphs it in, and per-connection compression ships only what
// changed. The tick is what keeps the cost bounded:
//
//   - Writes only mark a view dirty. A hundred writes inside one tick are one
//     render, so renders per second never exceed views x tick rate, however
//     many writes or viewers there are.
//   - A tick that overruns its budget makes time.Ticker drop the ticks it
//     missed. The next render reads the latest state, so the frames in between
//     simply never exist. The server sheds frame rate instead of piling up work.
//   - Each subscriber holds one frame slot. The renderer overwrites it and never
//     waits on a client, so a slow connection skips frames instead of queueing
//     them. That is safe because every frame is the whole view: dropping one
//     loses nothing the next one does not carry.
//
// Views are addressed by string keys ("todos/<session>", "monitor"). Features
// register a RenderFunc for a key prefix with Handle. Only keys that have at
// least one open subscriber are rendered, and subscribing marks the key dirty,
// so a new viewer always gets a fresh render and nothing outlives its viewers.
package frames

import (
	"context"
	"fmt"
	"log/slog"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

// RenderFunc renders the current frame for key.
type RenderFunc func(ctx context.Context, key string) ([]byte, error)

// Option configures a route registered with Handle.
type Option func(*route)

// Every re-renders every subscribed key under the prefix at least once per d,
// whether or not anything marked it dirty. Use it for views whose source is
// sampled rather than written, like host stats.
func Every(d time.Duration) Option {
	return func(rt *route) { rt.every = d }
}

type route struct {
	prefix string
	render RenderFunc
	every  time.Duration
	last   time.Time
}

// Renderer owns the tick loop. Construct it with New and run it with Run.
type Renderer struct {
	tick    time.Duration
	logger  *slog.Logger
	metrics *metrics

	mu     sync.Mutex
	routes []*route
	dirty  map[string]struct{}
	subs   map[string]map[*Sub]struct{}
}

func New(tick time.Duration, logger *slog.Logger, registry prometheus.Registerer) *Renderer {
	return &Renderer{
		tick:    tick,
		logger:  logger,
		metrics: newMetrics(registry),
		dirty:   make(map[string]struct{}),
		subs:    make(map[string]map[*Sub]struct{}),
	}
}

// Handle registers render for every key that starts with prefix. The longest
// matching prefix wins.
func (r *Renderer) Handle(prefix string, render RenderFunc, opts ...Option) {
	rt := &route{prefix: prefix, render: render}
	for _, opt := range opts {
		opt(rt)
	}

	r.mu.Lock()
	defer r.mu.Unlock()
	r.routes = append(r.routes, rt)
	slices.SortFunc(r.routes, func(a, b *route) int { return len(b.prefix) - len(a.prefix) })
}

// MarkDirty schedules key for a render on the next tick. It is cheap and never
// blocks, so call it from anywhere a write happens; repeated marks coalesce.
func (r *Renderer) MarkDirty(key string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.dirty[key] = struct{}{}
}

// Subscribe registers interest in key and schedules its first render. The
// caller must Close the subscription when its stream ends.
func (r *Renderer) Subscribe(key string) (*Sub, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if r.routeFor(key) == nil {
		return nil, fmt.Errorf("no view registered for %q", key)
	}

	s := &Sub{r: r, key: key, wake: make(chan struct{}, 1)}
	if r.subs[key] == nil {
		r.subs[key] = make(map[*Sub]struct{})
	}
	r.subs[key][s] = struct{}{}
	r.dirty[key] = struct{}{}
	r.metrics.subscribers.Inc()
	return s, nil
}

// Run ticks until ctx is cancelled.
func (r *Renderer) Run(ctx context.Context) error {
	t := time.NewTicker(r.tick)
	defer t.Stop()

	stats := overrunStats{window: 20 * time.Second}
	for {
		select {
		case <-ctx.Done():
			return nil
		case now := <-t.C:
			start := time.Now()
			r.step(ctx, now)
			took := time.Since(start)

			r.metrics.tickSeconds.Observe(took.Seconds())
			if took > r.tick {
				r.metrics.overruns.Inc()
			}
			if s, ok := stats.record(took, r.tick, now); ok {
				r.logger.Warn("frames: tick overrun",
					"budget", r.tick.String(), "ticks", s.n,
					"p50", s.p50.String(), "p95", s.p95.String(),
					"p99", s.p99.String(), "max", s.max.String())
			}
		}
	}
}

// step renders every dirty key that has a subscriber. Rendering is serial; if
// the overrun log says one goroutine is not enough, split the keys across a few
// workers here and wait for all of them before returning.
func (r *Renderer) step(ctx context.Context, now time.Time) {
	r.mu.Lock()
	for _, rt := range r.routes {
		if rt.every <= 0 || now.Sub(rt.last) < rt.every {
			continue
		}
		rt.last = now
		for key := range r.subs {
			if strings.HasPrefix(key, rt.prefix) {
				r.dirty[key] = struct{}{}
			}
		}
	}

	type job struct {
		key    string
		render RenderFunc
	}
	var jobs []job
	for key := range r.dirty {
		// No subscriber, nothing to render for. Whoever subscribes next marks
		// the key dirty again, so dropping the mark here never serves stale HTML.
		if len(r.subs[key]) == 0 {
			continue
		}
		jobs = append(jobs, job{key: key, render: r.routeFor(key).render})
	}
	clear(r.dirty)
	r.mu.Unlock()

	for _, j := range jobs {
		html, err := j.render(ctx, j.key)
		if err != nil {
			r.metrics.renderErrors.Inc()
			r.logger.Error("frames: render", "key", j.key, "error", err)
			continue
		}
		r.publish(j.key, html)
	}
}

func (r *Renderer) publish(key string, html []byte) {
	r.mu.Lock()
	defer r.mu.Unlock()
	for s := range r.subs[key] {
		s.set(html)
	}
}

func (r *Renderer) routeFor(key string) *route {
	for _, rt := range r.routes {
		if strings.HasPrefix(key, rt.prefix) {
			return rt
		}
	}
	return nil
}

// Sub is one stream's view of one key: a single frame slot plus a wake-up
// channel. The renderer overwrites the slot; the stream sends whatever is in
// it when it is ready.
type Sub struct {
	r    *Renderer
	key  string
	wake chan struct{}

	mu      sync.Mutex
	html    []byte
	version uint64
}

// Latest returns the newest frame and its version. A stream remembers the
// version it last sent and skips a frame it has already sent.
func (s *Sub) Latest() ([]byte, uint64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.html, s.version
}

// Stream sends each new frame to send until ctx is cancelled or send fails.
// It is the whole read loop of an SSE handler:
//
//	err := sub.Stream(ctx, func(b []byte) error { return sse.PatchElements(string(b)) })
//
// While send is blocked on a slow client, newer frames overwrite the slot.
// When send returns, the loop picks up the newest one and skips the rest.
func (s *Sub) Stream(ctx context.Context, send func([]byte) error) error {
	var sent uint64
	for {
		if html, version := s.Latest(); html != nil && version != sent {
			if err := send(html); err != nil {
				return err
			}
			sent = version
		}
		select {
		case <-ctx.Done():
			return nil
		case <-s.wake:
		}
	}
}

// Close unregisters the subscription.
func (s *Sub) Close() {
	s.r.mu.Lock()
	defer s.r.mu.Unlock()
	if _, ok := s.r.subs[s.key][s]; !ok {
		return
	}
	delete(s.r.subs[s.key], s)
	if len(s.r.subs[s.key]) == 0 {
		delete(s.r.subs, s.key)
	}
	s.r.metrics.subscribers.Dec()
}

func (s *Sub) set(html []byte) {
	s.mu.Lock()
	s.html = html
	s.version++
	s.mu.Unlock()

	select {
	case s.wake <- struct{}{}:
	default:
		// A wake-up is already pending; the stream will read the newest frame.
	}
}
