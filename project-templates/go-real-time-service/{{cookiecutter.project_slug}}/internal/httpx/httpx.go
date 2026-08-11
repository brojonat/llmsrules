// Package httpx holds the HTTP plumbing shared by every feature: the
// middleware adapter chain, the adapters themselves, and JSON helpers.
//
// Dependencies are always passed in explicitly. Nothing here reads globals.
package httpx

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/prometheus/client_golang/prometheus"
)

// Adapter wraps an http.Handler with additional behaviour.
type Adapter func(http.Handler) http.Handler

// Adapt applies adapters to h so that the first adapter listed is the
// outermost one, i.e. the first to see the request.
func Adapt(h http.Handler, adapters ...Adapter) http.Handler {
	for i := len(adapters) - 1; i >= 0; i-- {
		h = adapters[i](h)
	}
	return h
}

type contextKey string

const (
	claimsKey    contextKey = "claims"
	requestIDKey contextKey = "request_id"
)

// ClaimsFrom returns the JWT claims attached by WithJWTAuth, if any.
func ClaimsFrom(ctx context.Context) (jwt.MapClaims, bool) {
	claims, ok := ctx.Value(claimsKey).(jwt.MapClaims)
	return claims, ok
}

// RequestIDFrom returns the request ID attached by WithRequestID, if any.
func RequestIDFrom(ctx context.Context) (string, bool) {
	id, ok := ctx.Value(requestIDKey).(string)
	return id, ok
}

func WithRequestID() Adapter {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			requestID := fmt.Sprintf("%d", time.Now().UnixNano())
			ctx := context.WithValue(r.Context(), requestIDKey, requestID)
			w.Header().Set("X-Request-ID", requestID)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

func WithLogging(logger *slog.Logger) Adapter {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			next.ServeHTTP(w, r)
			logger.DebugContext(r.Context(), "request",
				"method", r.Method,
				"path", r.URL.Path,
				"duration", time.Since(start),
			)
		})
	}
}

func WithRecover(logger *slog.Logger) Adapter {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if rec := recover(); rec != nil {
					logger.ErrorContext(r.Context(), "panic recovered",
						"path", r.URL.Path,
						"panic", rec,
					)
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}

func WithJWTAuth(secret []byte) Adapter {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			authHeader := r.Header.Get("Authorization")
			if authHeader == "" {
				WriteJSONError(w, "missing authorization header", http.StatusUnauthorized)
				return
			}

			tokenString := strings.TrimPrefix(authHeader, "Bearer ")
			if tokenString == authHeader {
				WriteJSONError(w, "invalid authorization format", http.StatusUnauthorized)
				return
			}

			token, err := jwt.Parse(tokenString, func(token *jwt.Token) (interface{}, error) {
				if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
					return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
				}
				return secret, nil
			})
			if err != nil || !token.Valid {
				WriteJSONError(w, "invalid token", http.StatusUnauthorized)
				return
			}

			claims, ok := token.Claims.(jwt.MapClaims)
			if !ok {
				WriteJSONError(w, "invalid token claims", http.StatusUnauthorized)
				return
			}

			next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), claimsKey, claims)))
		})
	}
}

// responseWriter records the status code for metrics.
//
// It MUST forward Flush and expose Unwrap. Datastar upgrades a response to an
// SSE stream via http.NewResponseController, which walks Unwrap looking for a
// flushable writer and panics when it cannot find one. A naive wrapper that
// only embeds http.ResponseWriter hides the underlying http.Flusher and takes
// down every streaming endpoint on its first write.
type responseWriter struct {
	http.ResponseWriter
	statusCode int
}

func (rw *responseWriter) WriteHeader(code int) {
	rw.statusCode = code
	rw.ResponseWriter.WriteHeader(code)
}

func (rw *responseWriter) Unwrap() http.ResponseWriter { return rw.ResponseWriter }

func (rw *responseWriter) Flush() {
	if f, ok := rw.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

// Metrics owns the HTTP metric collectors. Construct it once and share the
// adapter across routes; registering the same collector twice panics.
type Metrics struct {
	duration *prometheus.HistogramVec
	total    *prometheus.CounterVec
}

func NewMetrics(registry *prometheus.Registry) *Metrics {
	m := &Metrics{
		duration: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "http_request_duration_seconds",
			Help:    "Duration of HTTP requests in seconds",
			Buckets: prometheus.DefBuckets,
		}, []string{"method", "path", "status"}),
		total: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "http_requests_total",
			Help: "Total number of HTTP requests",
		}, []string{"method", "path", "status"}),
	}
	registry.MustRegister(m.duration, m.total)
	return m
}

// Adapter records duration and count per request.
//
// Long-lived SSE handlers only report once they disconnect, so their duration
// measures connection lifetime rather than time-to-response. Read the streaming
// endpoints' numbers with that in mind.
func (m *Metrics) Adapter() Adapter {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			wrapped := &responseWriter{ResponseWriter: w, statusCode: http.StatusOK}
			next.ServeHTTP(wrapped, r)

			labels := prometheus.Labels{
				"method": r.Method,
				"path":   r.Pattern,
				"status": fmt.Sprintf("%d", wrapped.statusCode),
			}
			m.duration.With(labels).Observe(time.Since(start).Seconds())
			m.total.With(labels).Inc()
		})
	}
}

func WriteJSON(w http.ResponseWriter, data interface{}, code int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(data)
}

func WriteJSONError(w http.ResponseWriter, message string, code int) {
	WriteJSON(w, map[string]string{"error": message}, code)
}
