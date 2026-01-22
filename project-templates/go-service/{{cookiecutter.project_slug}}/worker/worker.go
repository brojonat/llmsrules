package worker

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"go.temporal.io/sdk/client"
	sdklog "go.temporal.io/sdk/log"
	"go.temporal.io/sdk/worker"
)

// RunWorker starts the Temporal worker with the specified options.
func RunWorker(ctx context.Context, l *slog.Logger, temporalAddr, namespace, taskQueue string) error {
	temporalLogger := sdklog.NewStructuredLogger(l)

	// Connect to Temporal with retries
	var c client.Client
	var err error
	maxRetries := 5
	retryInterval := 5 * time.Second

	for i := 0; i < maxRetries; i++ {
		c, err = client.Dial(client.Options{
			Logger:    temporalLogger,
			HostPort:  temporalAddr,
			Namespace: namespace,
		})
		if err == nil {
			l.Info("connected to Temporal", "address", temporalAddr, "namespace", namespace)
			break
		}
		l.Error("failed to connect to Temporal", "attempt", i+1, "max_attempts", maxRetries, "error", err)
		if i < maxRetries-1 {
			l.Info("retrying Temporal connection", "interval", retryInterval)
			time.Sleep(retryInterval)
		}
	}
	if err != nil {
		return fmt.Errorf("couldn't connect to Temporal after %d attempts: %w", maxRetries, err)
	}
	defer c.Close()

	// Create the worker
	w := worker.New(c, taskQueue, worker.Options{})

	// Register workflows
	// w.RegisterWorkflow(YourWorkflow)

	// Register activities
	// w.RegisterActivity(YourActivity)

	l.Info("starting worker", "task_queue", taskQueue)
	err = w.Run(worker.InterruptCh())
	l.Info("worker stopped")
	return err
}

// CheckConnection attempts to connect to Temporal and returns an error if it fails.
// Used for health checks.
func CheckConnection(ctx context.Context, l *slog.Logger, temporalAddr, namespace string) error {
	temporalLogger := sdklog.NewStructuredLogger(l)

	c, err := client.Dial(client.Options{
		Logger:    temporalLogger,
		HostPort:  temporalAddr,
		Namespace: namespace,
	})
	if err != nil {
		return fmt.Errorf("health check failed: %w", err)
	}
	c.Close()

	l.Info("health check successful")
	return nil
}
