"""Small problems from the model's own simulator, so the tests fit any model."""

import numpy as np

from {{cookiecutter.package_name}} import model as example

SMALL = {d: min(size, 4) for d, size in example.SIM_DIMS.items()}


def data(rng: np.random.Generator, truth, n: int) -> dict[str, np.ndarray]:
    """Fresh model inputs from the truth, the way the sampler gets them."""
    return example.from_arrow(example.simulate(rng, truth, n), truth.coords)
