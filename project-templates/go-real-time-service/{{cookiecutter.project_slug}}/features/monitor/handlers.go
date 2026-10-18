package monitor

import (
	"bytes"
	"context"
	"fmt"
	"log/slog"
	"math"
	"net/http"
	"strings"

	"github.com/dustin/go-humanize"
	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/mem"
	"github.com/starfederation/datastar-go/datastar"

	"{{cookiecutter.go_mod}}/internal/frames"
	"{{cookiecutter.go_mod}}/internal/httpx"
)

// Stats is one sample of host stats, formatted for display.
type Stats struct {
	MemUsed    string
	MemTotal   string
	MemPercent string
	CPUUser    string
	CPUSystem  string
	CPUIdle    string
}

const viewKey = "monitor"

func handlePage(title string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := Page(title).Render(r.Context(), w); err != nil {
			httpx.WriteJSONError(w, "render failed", http.StatusInternalServerError)
		}
	})
}

// render is the frames.RenderFunc for the monitor view. Every viewer sees the
// same host, so there is one key and one render per interval no matter how
// many tabs are open -- not one sampler per connection.
func render(ctx context.Context, _ string) ([]byte, error) {
	stats, err := sample()
	if err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	if err := StatsView(stats).Render(ctx, &buf); err != nil {
		return nil, fmt.Errorf("rendering monitor view: %w", err)
	}
	return buf.Bytes(), nil
}

// handleEvents is pure server push: subscribe to the shared view and send
// frames for as long as the client stays connected.
func handleEvents(renderer *frames.Renderer, logger *slog.Logger) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		sub, err := renderer.Subscribe(viewKey)
		if err != nil {
			logger.ErrorContext(r.Context(), "monitor: subscribe", "error", err)
			httpx.WriteJSONError(w, "internal error", http.StatusInternalServerError)
			return
		}
		defer sub.Close()

		sse := datastar.NewSSE(w, r, datastar.WithCompression())
		err = sub.Stream(r.Context(), func(html []byte) error {
			return sse.PatchElements(string(html))
		})
		if err != nil {
			logger.DebugContext(r.Context(), "monitor: stream closed", "error", err)
		}
	})
}

func sample() (Stats, error) {
	vm, err := mem.VirtualMemory()
	if err != nil {
		return Stats{}, fmt.Errorf("reading memory stats: %w", err)
	}

	times, err := cpu.Times(false)
	if err != nil {
		return Stats{}, fmt.Errorf("reading cpu stats: %w", err)
	}
	if len(times) == 0 {
		return Stats{}, fmt.Errorf("reading cpu stats: no samples returned")
	}

	return Stats{
		MemUsed:    humanize.Bytes(vm.Used),
		MemTotal:   humanize.Bytes(vm.Total),
		MemPercent: fmt.Sprintf("%.1f%%", vm.UsedPercent),
		CPUUser:    duration(times[0].User),
		CPUSystem:  duration(times[0].System),
		CPUIdle:    duration(times[0].Idle),
	}, nil
}

func duration(totalSeconds float64) string {
	seconds := int64(math.Round(totalSeconds))

	days := seconds / (24 * 3600)
	seconds %= 24 * 3600
	hours := seconds / 3600
	seconds %= 3600
	minutes := seconds / 60
	seconds %= 60

	var parts []string
	if days > 0 {
		parts = append(parts, fmt.Sprintf("%dd", days))
	}
	if hours > 0 || len(parts) > 0 {
		parts = append(parts, fmt.Sprintf("%dh", hours))
	}
	if minutes > 0 || len(parts) > 0 {
		parts = append(parts, fmt.Sprintf("%dm", minutes))
	}
	parts = append(parts, fmt.Sprintf("%ds", seconds))

	return strings.Join(parts, " ")
}
