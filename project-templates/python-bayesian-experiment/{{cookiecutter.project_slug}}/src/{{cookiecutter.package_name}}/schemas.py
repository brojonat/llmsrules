"""Pydantic schemas for the API."""

from typing import Literal, Optional

from pydantic import BaseModel


class DataPoint(BaseModel):
    """A single data point in an experiment."""

    timestamp: str
    variant: str = "control"
    outcome: bool
    value: Optional[float] = None


class CreateExperimentRequest(BaseModel):
    """Request to create a new experiment."""

    name: str
    type: Literal["bernoulli", "ab_test"]
    description: str = ""


class Experiment(BaseModel):
    """An experiment with its data."""

    name: str
    type: Literal["bernoulli", "ab_test"]
    description: str = ""
    data: list[DataPoint] = []


class PosteriorCurve(BaseModel):
    """Posterior density curve for plotting."""

    x: list[float]
    y: list[float]


class PosteriorSummary(BaseModel):
    """Summary statistics for a posterior distribution."""

    parameter: str
    mean: float
    std: float
    hdi_low: float
    hdi_high: float
    curve: PosteriorCurve
