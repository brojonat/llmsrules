#!/bin/bash
set -e

# Test cookiecutter templates quickly
# Usage:
#   ./test-templates.sh              # Generate all templates
#   ./test-templates.sh go           # Generate only go-service
#   ./test-templates.sh python       # Generate only python-service
#   ./test-templates.sh cli          # Generate only python-cli
#   ./test-templates.sh clean        # Remove test output directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/_test-output"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}==>${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }

clean() {
    log "Cleaning test output directory..."
    rm -rf "$OUTPUT_DIR"
    success "Cleaned $OUTPUT_DIR"
}

generate_go() {
    log "Generating go-service template..."
    cookiecutter "$SCRIPT_DIR/go-service" \
        --no-input \
        --output-dir "$OUTPUT_DIR" \
        project_name="Test Go Service" \
        author="testuser"
    success "Generated: $OUTPUT_DIR/test-go-service"
    echo "    cd $OUTPUT_DIR/test-go-service && make help"
}

generate_python_service() {
    log "Generating python-service template..."
    cookiecutter "$SCRIPT_DIR/python-service" \
        --no-input \
        --output-dir "$OUTPUT_DIR" \
        project_name="Test Python Service" \
        author="testuser"
    success "Generated: $OUTPUT_DIR/test-python-service"
    echo "    cd $OUTPUT_DIR/test-python-service && make help"
}

generate_python_cli() {
    log "Generating python-cli template..."
    cookiecutter "$SCRIPT_DIR/python-cli" \
        --no-input \
        --output-dir "$OUTPUT_DIR" \
        project_name="Test CLI" \
        author="testuser"
    success "Generated: $OUTPUT_DIR/test-cli"
    echo "    cd $OUTPUT_DIR/test-cli"
    echo "    ./simple.py hello --name World"
    echo "    uv sync && uv run test-cli foo do-something"
}

show_help() {
    echo "Test cookiecutter templates"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  (none)    Generate all templates"
    echo "  go        Generate go-service only"
    echo "  python    Generate python-service only"
    echo "  cli       Generate python-cli only"
    echo "  clean     Remove test output directory"
    echo "  help      Show this help"
    echo ""
    echo "Output directory: $OUTPUT_DIR"
}

# Main
case "${1:-all}" in
    go)
        mkdir -p "$OUTPUT_DIR"
        generate_go
        ;;
    python)
        mkdir -p "$OUTPUT_DIR"
        generate_python_service
        ;;
    cli)
        mkdir -p "$OUTPUT_DIR"
        generate_python_cli
        ;;
    clean)
        clean
        ;;
    help|--help|-h)
        show_help
        ;;
    all)
        mkdir -p "$OUTPUT_DIR"
        generate_go
        echo ""
        generate_python_service
        echo ""
        generate_python_cli
        echo ""
        log "All templates generated in $OUTPUT_DIR"
        echo ""
        echo "Quick test commands:"
        echo "  cd $OUTPUT_DIR/test-go-service && make build"
        echo "  cd $OUTPUT_DIR/test-python-service && uv sync && make test"
        echo "  cd $OUTPUT_DIR/test-cli && ./simple.py hello"
        ;;
    *)
        error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
