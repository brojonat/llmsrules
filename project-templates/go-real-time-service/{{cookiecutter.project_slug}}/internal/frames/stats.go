package frames

import (
	"slices"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

// overrunStats turns tick durations into a periodic summary while the loop is
// overrunning. The first overrun opens a window; every tick inside it is
// recorded; when the window closes, record reports percentiles once. One log
// line per window instead of one per tick, and the numbers double as a
// benchmark: open some connections and read the log.
type overrunStats struct {
	window  time.Duration
	started time.Time
	samples []time.Duration
}

type summary struct {
	n                  int
	p50, p95, p99, max time.Duration
}

func (o *overrunStats) record(took, budget time.Duration, now time.Time) (summary, bool) {
	if o.started.IsZero() {
		if took <= budget {
			return summary{}, false
		}
		o.started = now
	}
	o.samples = append(o.samples, took)
	if now.Sub(o.started) < o.window {
		return summary{}, false
	}

	s := o.samples
	slices.Sort(s)
	at := func(q float64) time.Duration { return s[int(q*float64(len(s)-1))] }
	out := summary{n: len(s), p50: at(0.50), p95: at(0.95), p99: at(0.99), max: s[len(s)-1]}

	o.started = time.Time{}
	o.samples = o.samples[:0]
	return out, true
}

type metrics struct {
	tickSeconds  prometheus.Histogram
	overruns     prometheus.Counter
	renderErrors prometheus.Counter
	subscribers  prometheus.Gauge
}

func newMetrics(registry prometheus.Registerer) *metrics {
	m := &metrics{
		tickSeconds: prometheus.NewHistogram(prometheus.HistogramOpts{
			Name:    "frames_tick_duration_seconds",
			Help:    "Time spent rendering one tick.",
			Buckets: prometheus.ExponentialBuckets(0.0005, 2, 14), // 0.5ms .. ~4s
		}),
		overruns: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "frames_tick_overruns_total",
			Help: "Ticks that took longer than the tick budget.",
		}),
		renderErrors: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "frames_render_errors_total",
			Help: "Views that failed to render.",
		}),
		subscribers: prometheus.NewGauge(prometheus.GaugeOpts{
			Name: "frames_subscribers",
			Help: "Open streams subscribed to a view.",
		}),
	}
	registry.MustRegister(m.tickSeconds, m.overruns, m.renderErrors, m.subscribers)
	return m
}
