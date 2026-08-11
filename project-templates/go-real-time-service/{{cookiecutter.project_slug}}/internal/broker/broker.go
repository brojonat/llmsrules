// Package broker runs an embedded NATS server with JetStream enabled and hands
// out JetStream KeyValue buckets.
//
// The broker is deliberately stateless. JetStream's store directory is a
// temporary directory removed on shutdown, and every bucket created through
// KV uses memory storage with a TTL. Restarting the process starts from a
// clean slate, which keeps the deployment a plain stateless Deployment with no
// volumes to manage.
//
// If this service later needs durable state, that belongs in whatever data
// system it is wired into -- not here. Switching a bucket to file storage and
// attaching a volume is a deliberate, separate decision.
package broker

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"os"
	"time"

	"github.com/delaneyj/toolbelt"
	"github.com/delaneyj/toolbelt/embeddednats"
	"github.com/nats-io/nats.go/jetstream"
	natsserver "github.com/nats-io/nats-server/v2/server"
)

type Broker struct {
	server   *embeddednats.Server
	js       jetstream.JetStream
	storeDir string
	logger   *slog.Logger
}

// Start boots the embedded NATS server. If port is 0 or already taken, a free
// port is chosen automatically.
func Start(ctx context.Context, logger *slog.Logger, port int) (*Broker, error) {
	storeDir, err := os.MkdirTemp("", "{{cookiecutter.project_slug}}-nats-")
	if err != nil {
		return nil, fmt.Errorf("creating nats store dir: %w", err)
	}

	if port <= 0 || !portIsFree(port) {
		free, err := toolbelt.FreePort()
		if err != nil {
			os.RemoveAll(storeDir)
			return nil, fmt.Errorf("finding a free nats port: %w", err)
		}
		port = free
	}

	server, err := embeddednats.New(ctx, embeddednats.WithNATSServerOptions(&natsserver.Options{
		JetStream: true,
		NoSigs:    true,
		Port:      port,
		StoreDir:  storeDir,
	}))
	if err != nil {
		os.RemoveAll(storeDir)
		return nil, fmt.Errorf("starting embedded nats: %w", err)
	}
	server.WaitForServer()

	client, err := server.Client()
	if err != nil {
		os.RemoveAll(storeDir)
		return nil, fmt.Errorf("connecting to embedded nats: %w", err)
	}

	js, err := jetstream.New(client)
	if err != nil {
		os.RemoveAll(storeDir)
		return nil, fmt.Errorf("creating jetstream client: %w", err)
	}

	logger.Info("embedded nats started", "port", port)

	return &Broker{server: server, js: js, storeDir: storeDir, logger: logger}, nil
}

// KV returns a memory-backed KeyValue bucket, creating it if necessary.
// Entries expire after ttl so that abandoned sessions do not accumulate.
func (b *Broker) KV(ctx context.Context, bucket string, ttl time.Duration) (jetstream.KeyValue, error) {
	kv, err := b.js.CreateOrUpdateKeyValue(ctx, jetstream.KeyValueConfig{
		Bucket:      bucket,
		Description: "{{cookiecutter.project_name}} " + bucket,
		Storage:     jetstream.MemoryStorage,
		Compression: true,
		TTL:         ttl,
		MaxBytes:    16 << 20, // 16MiB
	})
	if err != nil {
		return nil, fmt.Errorf("creating kv bucket %q: %w", bucket, err)
	}
	return kv, nil
}

// Close shuts the server down and removes its temporary store directory.
func (b *Broker) Close() {
	b.server.Close()
	if err := os.RemoveAll(b.storeDir); err != nil {
		b.logger.Warn("removing nats store dir", "error", err)
	}
}

func portIsFree(port int) bool {
	ln, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
	if err != nil {
		return false
	}
	return ln.Close() == nil
}
