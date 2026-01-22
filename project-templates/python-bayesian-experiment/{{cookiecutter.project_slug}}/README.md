# {{cookiecutter.project_name}}

{{cookiecutter.description}}

## Quick Start

```bash
# Install dependencies
uv sync --all-extras

# Run the API server
make run-server

# In another terminal, run CLI commands
{{cookiecutter.project_slug}} experiments list
{{cookiecutter.project_slug}} experiments create --name my-exp --type bernoulli
```

## Development

```bash
# Start dev session (API server + MLflow UI in tmux)
make start-dev

# Run tests
make test

# Run linter
make lint

# Format code
make format
```

## Project Structure

```
.
├── src/{{cookiecutter.package_name}}/
│   ├── cli/                    # Click CLI commands
│   │   ├── main.py             # CLI entrypoint
│   │   └── experiments.py      # Experiment management commands
│   ├── server/                 # FastAPI server
│   │   ├── main.py             # App entrypoint
│   │   └── routers/            # API routers
│   ├── models/                 # PyMC Bayesian models
│   │   └── bernoulli.py        # Bernoulli model
│   ├── db/                     # Data storage
│   │   └── store.py            # Experiment store
│   └── schemas.py              # Pydantic schemas
├── tests/
├── docker-compose.yaml         # MLflow + MinIO services
├── Makefile
└── pyproject.toml
```

## Creating Experiments

### Via CLI

```bash
# Create a Bernoulli experiment
{{cookiecutter.project_slug}} experiments create --name click-rate --type bernoulli

# Add data
echo '[{"timestamp": "2024-01-01T00:00:00", "outcome": true}]' | \
  {{cookiecutter.project_slug}} experiments add-data --name click-rate --file -

# Get posterior
{{cookiecutter.project_slug}} experiments posterior --name click-rate
```

### Via API

```bash
# Create experiment
curl -X POST http://localhost:8000/experiments \
  -H "Content-Type: application/json" \
  -d '{"name": "click-rate", "type": "bernoulli"}'

# Add data
curl -X POST http://localhost:8000/experiments/click-rate/data \
  -H "Content-Type: application/json" \
  -d '[{"timestamp": "2024-01-01T00:00:00", "outcome": true}]'

# Get posterior
curl http://localhost:8000/experiments/click-rate/posterior
```

## Adding New Model Types

1. Create a model in `src/{{cookiecutter.package_name}}/models/`:

```python
# models/my_model.py
import pymc as pm
import arviz as az

def fit_my_model(data) -> az.InferenceData:
    with pm.Model():
        # Define priors
        theta = pm.Normal("theta", mu=0, sigma=1)
        # Define likelihood
        pm.Normal("obs", mu=theta, sigma=1, observed=data)
        # Sample
        idata = pm.sample()
    return idata
```

2. Add to schemas if needed
3. Add a router endpoint or extend the experiments router
4. Update `schemas.py` with the new experiment type
