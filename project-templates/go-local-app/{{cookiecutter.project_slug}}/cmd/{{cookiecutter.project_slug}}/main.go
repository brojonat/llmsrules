// Command {{cookiecutter.project_slug}} is {{cookiecutter.description}}.
package main

import (
	"context"
	"fmt"
	"os"

	"github.com/urfave/cli/v3"
)

// version is set at build time with -ldflags "-X main.version=...".
var version = "dev"

func main() {
	root := &cli.Command{
		Name:    "{{cookiecutter.project_slug}}",
		Usage:   "{{cookiecutter.description}}",
		Version: version,
		Suggest: true,
		Commands: []*cli.Command{
			serveCommand(),
		},
	}
	if err := root.Run(context.Background(), os.Args); err != nil {
		fmt.Fprintln(os.Stderr, "{{cookiecutter.project_slug}}:", err)
		os.Exit(1)
	}
}
