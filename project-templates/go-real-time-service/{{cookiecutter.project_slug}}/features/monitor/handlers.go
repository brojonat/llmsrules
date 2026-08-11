package monitor

import (
	"fmt"
	"log/slog"
	"math"
	"net/http"
	"strings"
	"time"

	"github.com/dustin/go-humanize"
	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/mem"
	"github.com/starfederation/datastar-go/datastar"

	"{{cookiecutter.go_mod}}/internal/httpx"
)

// Signals mirrors the Datastar signal names bound in page.templ.
//
// Fields are omitempty so a partial update (memory only, CPU only) leaves the
// other signals untouched on the client.
type Signals struct {
	MemUsed    string `json:"memUsed,omitempty"`
	MemTotal   string `json:"memTotal,omitempty"`
	MemPercent string `json:"memPercent,omitempty"`
	CPUUser    string `json:"cpuUser,omitempty"`
	CPUSystem  string `json:"cpuSystem,omitempty"`
	CPUIdle    string `json:"cpuIdle,omitempty"`
}

func handlePage(title string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if err := Page(title).Render(r.Context(), w); err != nil {
			httpx.WriteJSONError(w, "render failed", http.StatusInternalServerError)
		}
	})
}

// handleEvents pushes host stats on a ticker for as long as the client stays
// connected. There is no request/response pairing here at all.
func handleEvents(logger *slog.Logger, interval time.Duration) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		sse := datastar.NewSSE(w, r)

		ticker := time.NewTicker(interval)
		defer ticker.Stop()

		for {
			select {
			case <-ctx.Done():
				return

			case <-ticker.C:
				signals, err := sample()
				if err != nil {
					logger.ErrorContext(ctx, "monitor: sampling host stats", "error", err)
					return
				}
				if err := sse.MarshalAndPatchSignals(signals); err != nil {
					logger.DebugContext(ctx, "monitor: stream closed", "error", err)
					return
				}
			}
		}
	})
}

func sample() (Signals, error) {
	vm, err := mem.VirtualMemory()
	if err != nil {
		return Signals{}, fmt.Errorf("reading memory stats: %w", err)
	}

	times, err := cpu.Times(false)
	if err != nil {
		return Signals{}, fmt.Errorf("reading cpu stats: %w", err)
	}
	if len(times) == 0 {
		return Signals{}, fmt.Errorf("reading cpu stats: no samples returned")
	}

	return Signals{
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
