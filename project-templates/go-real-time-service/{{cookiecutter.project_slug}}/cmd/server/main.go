package main

import (
	"context"
	"fmt"
	"log"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/gorilla/sessions"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/urfave/cli/v2"
	"golang.org/x/sync/errgroup"

	"{{cookiecutter.go_mod}}/internal/broker"
	"{{cookiecutter.go_mod}}/router"
)

func main() {
	app := &cli.App{
		Name:  "{{cookiecutter.project_slug}}",
		Usage: "{{cookiecutter.description}}",
		Commands: []*cli.Command{
			{
				Name:  "server",
				Usage: "Start the HTTP server",
				Flags: []cli.Flag{
					&cli.StringFlag{
						Name:    "addr",
						Value:   ":8080",
						EnvVars: []string{"SERVER_ADDR"},
					},
					&cli.StringFlag{
						Name:    "log-level",
						Value:   "warn",
						EnvVars: []string{"LOG_LEVEL"},
					},
					&cli.StringFlag{
						Name:    "session-secret",
						Value:   "change-me",
						Usage:   "key used to sign session cookies",
						EnvVars: []string{"SESSION_SECRET"},
					},
					&cli.IntFlag{
						Name:    "nats-port",
						Value:   0,
						Usage:   "port for the embedded NATS server (0 picks a free one)",
						EnvVars: []string{"NATS_PORT"},
					},
				},
				Action: runServer,
			},
		},
	}

	if err := app.Run(os.Args); err != nil {
		log.Fatal(err)
	}
}

func runServer(c *cli.Context) error {
	logger := setupLogger(c.String("log-level"))

	// Cancelling this context tears down request contexts too (see BaseContext
	// below), which is what lets long-lived SSE handlers return on shutdown.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	b, err := broker.Start(ctx, logger, c.Int("nats-port"))
	if err != nil {
		return fmt.Errorf("starting broker: %w", err)
	}
	defer b.Close()

	sessionStore := sessions.NewCookieStore([]byte(c.String("session-secret")))
	sessionStore.MaxAge(86400 * 30)
	sessionStore.Options.Path = "/"
	sessionStore.Options.HttpOnly = true
	sessionStore.Options.SameSite = http.SameSiteLaxMode

	handler, err := router.New(ctx, router.Deps{
		Logger:   logger,
		Broker:   b,
		Sessions: sessionStore,
		Registry: prometheus.NewRegistry(),
	})
	if err != nil {
		return fmt.Errorf("building router: %w", err)
	}

	addr := c.String("addr")
	server := &http.Server{
		Addr:        addr,
		Handler:     handler,
		BaseContext: func(net.Listener) context.Context { return ctx },
		ErrorLog:    slog.NewLogLogger(logger.Handler(), slog.LevelError),
		// No WriteTimeout: it would cut off SSE streams mid-flight.
		ReadHeaderTimeout: 10 * time.Second,
	}

	eg, egctx := errgroup.WithContext(ctx)

	eg.Go(func() error {
		logger.Info("server started", "addr", addr)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			return fmt.Errorf("http server: %w", err)
		}
		return nil
	})

	eg.Go(func() error {
		<-egctx.Done()
		logger.Info("server shutting down")

		shutdownCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()

		if err := server.Shutdown(shutdownCtx); err != nil {
			return fmt.Errorf("shutting down http server: %w", err)
		}
		return nil
	})

	if err := eg.Wait(); err != nil {
		return err
	}

	logger.Info("server stopped")
	return nil
}

func setupLogger(levelStr string) *slog.Logger {
	var level slog.Level
	switch strings.ToUpper(levelStr) {
	case "DEBUG":
		level = slog.LevelDebug
	case "INFO":
		level = slog.LevelInfo
	case "WARN":
		level = slog.LevelWarn
	case "ERROR":
		level = slog.LevelError
	default:
		level = slog.LevelWarn
	}
	return slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: level}))
}
