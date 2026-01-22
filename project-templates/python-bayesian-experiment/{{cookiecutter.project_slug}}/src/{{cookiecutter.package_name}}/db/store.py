"""In-memory experiment store.

For production use, replace with a proper database backend
(e.g., DuckDB via Ibis, PostgreSQL, etc.)
"""

from typing import Optional

from {{cookiecutter.package_name}}.schemas import Experiment


class ExperimentStore:
    """Simple in-memory store for experiments.

    In production, replace this with a database-backed implementation.
    Consider using:
    - ibis-framework[duckdb] for local/embedded storage
    - ibis-framework[postgres] for production databases
    - MLflow for model artifact storage
    """

    def __init__(self):
        self._experiments: dict[str, Experiment] = {}

    def list_experiments(self) -> list[Experiment]:
        """List all experiments."""
        return list(self._experiments.values())

    def get_experiment(self, name: str) -> Optional[Experiment]:
        """Get an experiment by name."""
        return self._experiments.get(name)

    def save_experiment(self, experiment: Experiment) -> None:
        """Save or update an experiment."""
        self._experiments[experiment.name] = experiment

    def delete_experiment(self, name: str) -> bool:
        """Delete an experiment. Returns True if deleted, False if not found."""
        if name in self._experiments:
            del self._experiments[name]
            return True
        return False
