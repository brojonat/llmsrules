---
name: bayesian-mixture-models
description: Fit Bayesian Gaussian mixture models with PyMC for soft clustering with full uncertainty. Use when the user needs probabilistic cluster assignments, latent heterogeneity modeling, zero-inflated data, or principled model selection for number of clusters. Covers Dirichlet priors, label switching, LOO-CV model comparison, and applications beyond clustering.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
-->

# Bayesian Mixture Models — Soft Clustering with Uncertainty

For clustering where you need **probabilistic assignments** and
**uncertainty on cluster parameters**, use Bayesian Gaussian mixture
models with PyMC. Unlike k-means (hard assignments, no uncertainty)
or sklearn GMM (soft assignments, no parameter uncertainty), the
Bayesian approach gives you posteriors on everything: means,
variances, weights, and per-point assignments.

## When to use this skill

- You need soft cluster assignments (each point has a probability of
  belonging to each cluster)
- You want uncertainty on cluster locations, shapes, and weights
- You need principled model selection for the number of components K
- Your data has latent heterogeneity (subpopulations with different
  distributions)
- You're modeling zero-inflated data, outlier mixtures, or regime
  switching

## When NOT to use this skill

- You have > 10,000 points and just need fast hard assignments →
  use k-means or HDBSCAN from the `unsupervised` bundle
- Your clusters are non-convex (crescents, rings) → GMMs assume
  elliptical clusters; use HDBSCAN or spectral clustering
- You have high-dimensional data (> 20 features) → fit in a reduced
  space (PCA/UMAP first) or use a diagonal covariance model
- You want purely predictive clustering with no interpretability
  requirement → sklearn is fine

## Project layout

```
<project>/
├── data/                # input parquet/csv
├── src/
│   ├── train.py         # fit mixture model → MLflow log
│   ├── predict.py       # reload idata, assign new points
│   └── plots.py         # cluster viz, assignment entropy, weight posteriors
├── notebooks/
│   └── demo.py          # marimo walkthrough
└── mlruns/              # MLflow tracking store (gitignored)
```

## The model

```python
import pymc as pm
import numpy as np

K = 3  # number of components

with pm.Model() as mixture_model:
    # Mixture weights — Dirichlet prior (symmetric)
    w = pm.Dirichlet("w", a=np.ones(K) * 2.0)

    # Component means — ordered to break label switching
    mu_raw = pm.Normal("mu_raw", mu=0, sigma=5, shape=(K, D))
    sort_idx = pm.math.argsort(mu_raw[:, 0])
    mu = pm.Deterministic("mu", mu_raw[sort_idx])

    # Component standard deviations
    sigma = pm.HalfNormal("sigma", sigma=3, shape=K)

    # Likelihood — PyMC Mixture marginalizes out z
    components = [
        pm.MvNormal.dist(
            mu=mu[k],
            cov=pm.math.eye(D) * sigma[k] ** 2,
        )
        for k in range(K)
    ]
    pm.Mixture("obs", w=w, comp_dists=components, observed=X)

    idata = pm.sample(draws=2000, tune=2000, chains=4,
                      target_accept=0.9)
```

### Why `Mixture` instead of sampling z directly?

PyMC's `Mixture` distribution marginalizes out the discrete latent
variable z (cluster assignment). This is critical — NUTS (the default
sampler) can't handle discrete parameters. Marginalizing integrates
them out analytically, leaving only continuous parameters for MCMC.

### Label switching — the main gotcha

In a K-component mixture, there are K! equivalent solutions (any
permutation of labels gives the same likelihood). This creates a
multimodal posterior that MCMC can't explore properly.

**Fix:** order the means on one dimension:
```python
sort_idx = pm.math.argsort(mu_raw[:, 0])
mu = pm.Deterministic("mu", mu_raw[sort_idx])
```

This breaks the symmetry by constraining mu[0] < mu[1] < ... on the
first coordinate. Only works when clusters are separated on at least
one dimension. For badly overlapping clusters, consider using
informative priors or running multiple short chains.

## Computing soft assignments

After fitting, compute per-point assignment probabilities by
averaging over posterior samples:

```python
from scipy import stats

mu_samples = idata.posterior["mu"].to_numpy().reshape(-1, K, D)
sigma_samples = idata.posterior["sigma"].to_numpy().reshape(-1, K)
w_samples = idata.posterior["w"].to_numpy().reshape(-1, K)

assignment_probs = np.zeros((N, K))
for s in range(0, n_samples, thin):
    log_probs = np.zeros((N, K))
    for k in range(K):
        dist = stats.multivariate_normal(
            mean=mu_samples[s, k],
            cov=np.eye(D) * sigma_samples[s, k] ** 2,
        )
        log_probs[:, k] = np.log(w_samples[s, k]) + dist.logpdf(X)
    # Normalize (log-sum-exp)
    max_lp = log_probs.max(axis=1, keepdims=True)
    probs = np.exp(log_probs - max_lp)
    probs /= probs.sum(axis=1, keepdims=True)
    assignment_probs += probs

assignment_probs /= n_used
```

**Assignment entropy** is a useful diagnostic — high-entropy points
are on cluster boundaries where the model is genuinely uncertain.

## Model selection — picking K

Fit models with different K and compare via LOO-CV:

```python
import arviz as az

results = {}
for k in range(2, 7):
    # ... fit model with k components ...
    pm.compute_log_likelihood(idata_k, model=model_k)
    results[f"K={k}"] = idata_k

comparison = az.compare(results, ic="loo")
```

The model with the highest `elpd_loo` has the best out-of-sample
predictive accuracy. This is more principled than BIC/AIC because
it uses the full posterior and doesn't rely on asymptotic
approximations.

**Note:** keep `draws` and `tune` consistent across K values so
the comparison is fair.

## Covariance structure

| Type | Parameters per component | When to use |
|---|---|---|
| `spherical` (isotropic) | 1 (single sigma) | Clusters are round, few data points |
| `diagonal` | D (one sigma per dimension) | Features are independent, moderate data |
| `full` | D(D+1)/2 | Clusters are elliptical, plenty of data |

Start with spherical/diagonal and upgrade to full only if you have
enough data. Full covariance with K=5 and D=10 means 275 covariance
parameters — easy to overfit.

## Beyond clustering — other mixture applications

### Zero-inflated models
```python
# Too many zeros in count data
pm.ZeroInflatedPoisson("y", psi=psi, mu=mu, observed=counts)
```

### Outlier detection
```python
# 2-component mixture: tight inlier + wide outlier
sigma_inlier = pm.HalfNormal("sigma_in", sigma=1)
sigma_outlier = pm.HalfNormal("sigma_out", sigma=10)
```
Points with high posterior probability of belonging to the outlier
component are outliers — no arbitrary thresholds.

### Regime switching
Time series where the generative process switches between states.
Each state is a mixture component. Add a transition matrix for
Hidden Markov Model (HMM) structure.

## MLflow logging

| Kind | What |
|---|---|
| `params` | K, covariance_type, draws, tune, chains, target_accept |
| `metrics` | elpd_loo, p_loo, mean_assignment_entropy, max_rhat, min_ess, weight_means |
| `tags` | data_hash, n_points, n_features |
| `artifacts` | posterior/idata.nc, plots/{clusters.png, assignments.png, weights.png, loo_comparison.png} |

## Common pitfalls

1. **Ignoring label switching.** If you don't order the means, the
   posterior is multimodal and all summary statistics (means, HDIs)
   are meaningless — they average over permutations.
2. **Using full covariance with too little data.** K=5 with full 10D
   covariance has 275 covariance parameters. Use diagonal or
   spherical unless you have >> 100 points per component per
   dimension.
3. **Picking K by elbow plot.** Elbow plots are subjective and
   unreliable. Use LOO-CV for principled comparison.
4. **Expecting well-separated clusters.** If the true clusters
   overlap heavily, the model will correctly report high assignment
   entropy for boundary points. That's not a failure — it's the
   model telling you the clusters aren't separable.
5. **Low target_accept.** Mixture models often need
   `target_accept=0.9` or higher for good convergence. The default
   0.8 may not be enough.
6. **Not thinning for assignment computation.** Computing
   P(z=k|x, theta) for every posterior sample and every data point
   is O(n_samples * N * K). Thin to ~200 samples for speed.

## Worked example

See `demo.py` (marimo notebook). It generates synthetic 2D clustered
data, fits a Bayesian GMM with PyMC, shows posterior mean locations
with uncertainty clouds, soft assignments with entropy, comparison
with sklearn EM, and LOO-CV model selection for K. Run it with:

```
marimo edit --sandbox demo.py
```
