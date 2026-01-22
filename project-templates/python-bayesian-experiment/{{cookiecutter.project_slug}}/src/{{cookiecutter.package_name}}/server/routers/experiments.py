"""Experiments router for managing Bayesian experiments."""

from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from scipy import stats

from {{cookiecutter.package_name}}.db.store import ExperimentStore
from {{cookiecutter.package_name}}.models.bernoulli import fit_bernoulli_model
from {{cookiecutter.package_name}}.schemas import (
    CreateExperimentRequest,
    DataPoint,
    Experiment,
    PosteriorCurve,
    PosteriorSummary,
)

router = APIRouter(prefix="/experiments", tags=["experiments"])

# In-memory store (replace with database in production)
store = ExperimentStore()


@router.get("", response_model=list[Experiment])
def list_experiments():
    """List all experiments."""
    return store.list_experiments()


@router.post("", response_model=Experiment)
def create_experiment(request: CreateExperimentRequest):
    """Create a new experiment."""
    if store.get_experiment(request.name):
        raise HTTPException(status_code=400, detail=f"Experiment '{request.name}' already exists")

    experiment = Experiment(
        name=request.name,
        type=request.type,
        description=request.description,
        data=[],
    )
    store.save_experiment(experiment)
    return experiment


@router.get("/{name}", response_model=Experiment)
def get_experiment(name: str):
    """Get an experiment by name."""
    experiment = store.get_experiment(name)
    if not experiment:
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")
    return experiment


@router.delete("/{name}")
def delete_experiment(name: str):
    """Delete an experiment."""
    if not store.get_experiment(name):
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")
    store.delete_experiment(name)
    return {"status": "deleted", "name": name}


@router.post("/{name}/data", response_model=Experiment)
def add_data(name: str, data: list[DataPoint]):
    """Add data points to an experiment."""
    experiment = store.get_experiment(name)
    if not experiment:
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")

    experiment.data.extend(data)
    store.save_experiment(experiment)
    return experiment


@router.get("/{name}/posterior", response_model=PosteriorSummary)
def get_posterior(name: str, variant: Optional[str] = None):
    """Compute posterior distribution for an experiment."""
    experiment = store.get_experiment(name)
    if not experiment:
        raise HTTPException(status_code=404, detail=f"Experiment '{name}' not found")

    if not experiment.data:
        raise HTTPException(status_code=400, detail="No data available for this experiment")

    # Filter by variant if specified
    data = experiment.data
    if variant:
        data = [d for d in data if d.variant == variant]

    if not data:
        raise HTTPException(status_code=400, detail=f"No data for variant '{variant}'")

    # Extract outcomes (0/1 for Bernoulli)
    outcomes = np.array([1 if d.outcome else 0 for d in data])

    if experiment.type == "bernoulli":
        idata = fit_bernoulli_model(outcomes)
        posterior_samples = idata.posterior["p"].values.flatten()

        # Generate KDE curve
        kde = stats.gaussian_kde(posterior_samples)
        x = np.linspace(0, 1, 200)
        y = kde(x)

        return PosteriorSummary(
            parameter="p",
            mean=float(posterior_samples.mean()),
            std=float(posterior_samples.std()),
            hdi_low=float(np.percentile(posterior_samples, 3)),
            hdi_high=float(np.percentile(posterior_samples, 97)),
            curve=PosteriorCurve(x=x.tolist(), y=y.tolist()),
        )
    else:
        raise HTTPException(
            status_code=400, detail=f"Posterior not implemented for type '{experiment.type}'"
        )
