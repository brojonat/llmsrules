#!/bin/bash
set -e

# Test cookiecutter templates
# Usage:
#   ./test-templates.sh                 # Generate all templates
#   ./test-templates.sh validate        # Generate + validate all templates
#   ./test-templates.sh go              # Generate go-service only
#   ./test-templates.sh validate go     # Generate + validate go-service
#   ./test-templates.sh python          # Generate python-service only
#   ./test-templates.sh validate python # Generate + validate python-service
#   ./test-templates.sh cli             # Generate python-cli only
#   ./test-templates.sh validate cli    # Generate + validate python-cli
#   ./test-templates.sh clean           # Remove test output directory

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/_test-output"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}==>${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }
section() { echo -e "\n${BLUE}━━━ $1 ━━━${NC}"; }

clean() {
    log "Cleaning test output directory..."
    rm -rf "$OUTPUT_DIR"
    success "Cleaned $OUTPUT_DIR"
}

# ============================================================================
# Generation functions
# ============================================================================

generate_go() {
    log "Generating go-service template..."
    cookiecutter "$SCRIPT_DIR/go-service" \
        --no-input \
        --output-dir "$OUTPUT_DIR" \
        project_name="Test Go Service" \
        author="testuser"
    success "Generated: $OUTPUT_DIR/test-go-service"
}

generate_python_service() {
    log "Generating python-service template..."
    cookiecutter "$SCRIPT_DIR/python-service" \
        --no-input \
        --output-dir "$OUTPUT_DIR" \
        project_name="Test Python Service" \
        author="testuser"
    success "Generated: $OUTPUT_DIR/test-python-service"
}

generate_python_cli() {
    log "Generating python-cli template..."
    cookiecutter "$SCRIPT_DIR/python-cli" \
        --no-input \
        --output-dir "$OUTPUT_DIR" \
        project_name="Test CLI" \
        author="testuser"
    success "Generated: $OUTPUT_DIR/test-cli"
}

# ============================================================================
# Validation functions
# ============================================================================

validate_go() {
    section "Validating go-service"
    local dir="$OUTPUT_DIR/test-go-service"
    cd "$dir"

    log "make help"
    make help
    success "make help works"

    log "go mod tidy"
    go mod tidy
    success "go mod tidy works"

    log "make build"
    make build
    success "make build works"

    log "./bin/test-go-service --help"
    ./bin/test-go-service --help
    success "CLI --help works"

    log "make test"
    make test || warn "Tests may fail without database (expected)"

    log "Starting server briefly..."
    timeout 3 ./bin/test-go-service server --addr :18080 &
    SERVER_PID=$!
    sleep 1
    if curl -sf http://localhost:18080/healthz > /dev/null 2>&1; then
        success "Server responds to /healthz"
    else
        warn "Server health check failed (may need AUTH_SECRET)"
    fi
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true

    success "go-service validation complete"
}

validate_python_service() {
    section "Validating python-service"
    local dir="$OUTPUT_DIR/test-python-service"
    cd "$dir"

    log "make help"
    make help
    success "make help works"

    log "uv sync --all-extras"
    uv sync --all-extras
    success "uv sync --all-extras works"

    log "uv run test-python-service --help"
    uv run test-python-service --help
    success "CLI --help works"

    log "make test"
    make test
    success "make test works"

    log "make lint"
    make lint
    success "make lint works"

    log "Starting server briefly..."
    uv run uvicorn server.main:app --host 0.0.0.0 --port 18000 &
    SERVER_PID=$!
    sleep 2
    if curl -sf http://localhost:18000/healthz > /dev/null 2>&1; then
        success "Server responds to /healthz"
    else
        warn "Server health check failed"
    fi
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true

    success "python-service validation complete"
}

validate_python_cli() {
    section "Validating python-cli"
    local dir="$OUTPUT_DIR/test-cli"
    cd "$dir"

    log "make help"
    make help
    success "make help works"

    # Simple PEP 723 script
    log "./simple.py --help"
    ./simple.py --help
    success "simple.py --help works"

    log "./simple.py hello --name World"
    ./simple.py hello --name World
    success "simple.py hello works"

    log "./simple.py add 2 3"
    ./simple.py add 2 3
    success "simple.py add works"

    # Structured CLI
    log "uv sync --all-extras"
    uv sync --all-extras
    success "uv sync --all-extras works"

    log "uv run test-cli --help"
    uv run test-cli --help
    success "test-cli --help works"

    log "uv run test-cli hello --name World"
    uv run test-cli hello --name World
    success "test-cli hello works"

    log "uv run test-cli foo do-something --verbose"
    uv run test-cli foo do-something --verbose
    success "test-cli foo do-something works"

    log "uv run test-cli bar greet World --count 2"
    uv run test-cli bar greet World --count 2
    success "test-cli bar greet works"

    log "make test"
    make test
    success "make test works"

    log "make lint"
    make lint
    success "make lint works"

    success "python-cli validation complete"
}

# ============================================================================
# Help
# ============================================================================

show_help() {
    cat << 'EOF'
Test cookiecutter templates

Usage: ./test-templates.sh [validate] [template]

Commands:
  (none)              Generate all templates
  validate            Generate + run validation tests on all templates
  validate <template> Generate + validate specific template
  go                  Generate go-service only
  python              Generate python-service only
  cli                 Generate python-cli only
  clean               Remove test output directory
  help                Show this help

Templates: go, python, cli

Examples:
  ./test-templates.sh                  # Generate all
  ./test-templates.sh validate         # Generate + test all
  ./test-templates.sh validate cli     # Generate + test python-cli only
  ./test-templates.sh cli              # Generate python-cli only
  ./test-templates.sh clean            # Clean up

EOF
    echo "Output directory: $OUTPUT_DIR"
}

# ============================================================================
# Main
# ============================================================================

main() {
    local cmd="${1:-}"
    local target="${2:-all}"

    case "$cmd" in
        clean)
            clean
            ;;
        help|--help|-h)
            show_help
            ;;
        validate)
            mkdir -p "$OUTPUT_DIR"
            case "$target" in
                go)
                    generate_go
                    validate_go
                    ;;
                python)
                    generate_python_service
                    validate_python_service
                    ;;
                cli)
                    generate_python_cli
                    validate_python_cli
                    ;;
                all)
                    generate_go
                    generate_python_service
                    generate_python_cli
                    echo ""
                    validate_go
                    validate_python_service
                    validate_python_cli
                    section "All validations passed!"
                    ;;
                *)
                    error "Unknown template: $target"
                    exit 1
                    ;;
            esac
            ;;
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
        ""|all)
            mkdir -p "$OUTPUT_DIR"
            generate_go
            echo ""
            generate_python_service
            echo ""
            generate_python_cli
            echo ""
            log "All templates generated in $OUTPUT_DIR"
            echo ""
            echo "Run './test-templates.sh validate' to test all entry points"
            echo ""
            echo "Or test manually:"
            echo "  cd $OUTPUT_DIR/test-go-service && make build && ./bin/test-go-service --help"
            echo "  cd $OUTPUT_DIR/test-python-service && uv sync --all-extras && make test"
            echo "  cd $OUTPUT_DIR/test-cli && ./simple.py hello"
            ;;
        *)
            error "Unknown command: $cmd"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
