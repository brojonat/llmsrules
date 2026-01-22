"""PyMC models for Bernoulli experiments."""

import arviz as az
import numpy as np
import pymc as pm


def fit_bernoulli_model(data: np.ndarray, draws: int = 1000, chains: int = 2) -> az.InferenceData:
    """
    Fit a Bayesian Bernoulli model to estimate the success probability.

    Parameters
    ----------
    data : np.ndarray
        Array of Bernoulli trials (0s and 1s).
    draws : int
        Number of posterior samples per chain.
    chains : int
        Number of MCMC chains.

    Returns
    -------
    az.InferenceData
        ArviZ InferenceData containing posterior samples for parameter 'p'.

    Example
    -------
    >>> import numpy as np
    >>> data = np.array([1, 1, 0, 1, 0, 1, 1, 1, 0, 1])
    >>> idata = fit_bernoulli_model(data)
    >>> p_samples = idata.posterior["p"].values.flatten()
    >>> print(f"Estimated p: {p_samples.mean():.3f} ± {p_samples.std():.3f}")
    """
    with pm.Model():
        # Prior: Beta(1, 1) is uniform on [0, 1]
        p = pm.Beta("p", alpha=1.0, beta=1.0)

        # Likelihood
        pm.Bernoulli("likelihood", p=p, observed=data)

        # Sample from posterior
        idata = pm.sample(draws=draws, chains=chains, progressbar=False)

    return idata
