---
name: bayesian-regression
description: Fit Bayesian regression models with PyMC using the Hogg approach — start simple, diagnose problems, upgrade the likelihood. Use when the user needs regression with proper uncertainty quantification, heteroscedastic errors, outlier robustness, or model comparison. Covers Normal, Student-t, and GLM likelihoods with ArviZ diagnostics and LOO-CV.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
-->

# Bayesian Regression — The Hogg Way

For regression where you need **proper uncertainty**, **outlier
robustness**, or **heteroscedastic error modeling**, use Bayesian
regression with PyMC. This skill follows the approach from Hogg, Bovy
& Lang (2010): start with the simplest model, diagnose where it
fails, and upgrade the likelihood to match the data's actual noise
structure.

The existing `regression` bundle uses XGBoost for nonlinear tabular
prediction. This bundle is for when you need **interpretable
coefficients with honest uncertainty** — the kind of regression that
goes in a paper, a regulatory filing, or a causal analysis.

## When to use this skill

- You need coefficient estimates with credible intervals (not just
  point predictions)
- Your data has heteroscedastic noise (variance that depends on
  predictors)
- Your data has outliers that bias OLS/MLE estimates
- You want to compare multiple model specifications (Normal vs
  Student-t vs Poisson) using principled model comparison
- You need posterior predictive checks to validate model assumptions
- You want a GLM (logistic, Poisson, Beta regression) with full
  Bayesian inference

## When NOT to use this skill

- You want the best possible *prediction* on tabular data and don't
  care about coefficients → use `regression` (XGBoost) bundle
- Your response is binary → use `bayesian-ab-testing` (conversion)
  or fit a Bayesian logistic regression using the GLM pattern below
- You have hierarchical/grouped data where coefficients vary by
  group → use `bayesian-regression` with partial pooling (see
  hierarchical section below)

## Project layout

```
<project>/
├── data/                # input parquet/csv
├── src/
│   ├── train.py         # fit models → MLflow log
│   ├── predict.py       # reload idata, posterior predictive
│   └── plots.py         # residuals, PPC, coefficient comparison
├── notebooks/
│   └── demo.py          # marimo walkthrough
└── mlruns/              # MLflow tracking store (gitignored)
```

## The Hogg workflow

### Step 1: OLS baseline

Always start here. OLS is fast, deterministic, and gives you a
reference point. Then check residuals.

```python
import numpy as np

X_design = np.column_stack([np.ones(n), x])
beta_ols = np.linalg.lstsq(X_design, y, rcond=None)[0]
residuals = y - X_design @ beta_ols
```

**Residual diagnostics:**
- Plot residuals vs each predictor → fan shape = heteroscedasticity
- QQ-plot of residuals → heavy tails = outliers
- If both look fine, OLS is defensible. But you still don't have
  uncertainty on the error model.

### Step 2: Bayesian Normal (homoscedastic)

Same assumptions as OLS, but with a full posterior:

```python
import pymc as pm

with pm.Model():
    intercept = pm.Normal("intercept", mu=0, sigma=10)
    slope = pm.Normal("slope", mu=0, sigma=5)
    sigma = pm.HalfNormal("sigma", sigma=5)

    mu = intercept + slope * x
    pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y)

    idata = pm.sample(draws=2000, tune=1000, chains=4)
```

**Center your predictors.** Subtracting the mean of x before fitting
reduces posterior correlation between intercept and slope, making
MCMC more efficient. Uncenter for reporting.

### Step 3: Heteroscedastic model

If residuals show a fan shape, model log(sigma) as a function of x:

```python
with pm.Model():
    intercept = pm.Normal("intercept", mu=0, sigma=10)
    slope = pm.Normal("slope", mu=0, sigma=5)

    # Noise model: log(sigma) = gamma0 + gamma1 * x
    gamma0 = pm.Normal("log_sigma_intercept", mu=0, sigma=2)
    gamma1 = pm.Normal("log_sigma_slope", mu=0, sigma=1)
    sigma = pm.math.exp(gamma0 + gamma1 * x)

    mu = intercept + slope * x
    pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y)
```

This gives you **pointwise uncertainty** — wider prediction intervals
where the data is noisier, narrower where it's cleaner. OLS can't
do this.

### Step 4: Robust model (Student-t)

The Hogg paper's core recommendation: **use Student-t as the default
likelihood.** It reduces to Normal when nu is large and gracefully
downweights outliers when nu is small.

```python
with pm.Model():
    intercept = pm.Normal("intercept", mu=0, sigma=10)
    slope = pm.Normal("slope", mu=0, sigma=5)
    sigma = pm.HalfNormal("sigma", sigma=5)
    nu = pm.Gamma("nu", alpha=2, beta=0.1)  # degrees of freedom

    mu = intercept + slope * x
    pm.StudentT("y_obs", nu=nu, mu=mu, sigma=sigma, observed=y)
```

**Interpreting nu:**
- nu < 5: heavy outlier contamination
- nu ~ 5-30: moderate tails
- nu > 30: data is essentially Gaussian — Student-t wasn't needed

### Step 5: Model comparison via LOO-CV

Don't guess which model is right. Let predictive accuracy decide:

```python
import arviz as az

pm.compute_log_likelihood(idata_homo, model=model_homo)
pm.compute_log_likelihood(idata_hetero, model=model_hetero)
pm.compute_log_likelihood(idata_robust, model=model_robust)

comparison = az.compare({
    "homoscedastic": idata_homo,
    "heteroscedastic": idata_hetero,
    "robust": idata_robust,
}, ic="loo")
```

The model with the highest `elpd_loo` has the best out-of-sample
predictive accuracy. `weight` gives the optimal stacking mixture.

## GLM generalization

The same workflow extends to any GLM by changing the link function
and likelihood:

| Response type | Link | Likelihood | PyMC code |
|---|---|---|---|
| Continuous | identity | Normal / Student-t | `pm.Normal("y", mu=mu, sigma=sigma)` |
| Binary | logit | Bernoulli | `pm.Bernoulli("y", logit_p=mu)` |
| Count | log | Poisson | `pm.Poisson("y", mu=pm.math.exp(mu))` |
| Count (overdispersed) | log | NegBinomial | `pm.NegativeBinomial("y", mu=pm.math.exp(mu), alpha=alpha)` |
| Positive continuous | log | Gamma | `pm.Gamma("y", mu=pm.math.exp(mu), sigma=sigma)` |
| Proportion [0,1] | logit | Beta | `pm.Beta("y", mu=pm.math.invlogit(mu), kappa=kappa)` |

The diagnostic workflow is the same: fit, check PPC, upgrade
likelihood if simulated data doesn't match real data.

## Hierarchical / partial pooling

When data has groups (stores, users, regions), fit a hierarchical
model that partially pools coefficient estimates:

```python
with pm.Model(coords={"group": group_names}):
    # Hyperpriors (population-level)
    mu_slope = pm.Normal("mu_slope", mu=0, sigma=5)
    sigma_slope = pm.HalfNormal("sigma_slope", sigma=2)

    # Group-level slopes (partial pooling)
    slope = pm.Normal("slope", mu=mu_slope, sigma=sigma_slope,
                      dims="group")

    # Likelihood
    mu = intercept + slope[group_idx] * x
    pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y)
```

Partial pooling shrinks noisy group estimates toward the population
mean — groups with more data keep their own estimate, groups with
little data borrow strength from the population.

## Diagnostics — always check

1. **Convergence:** R-hat < 1.01, ESS > 400 for all parameters
2. **Trace plots:** well-mixed chains (fuzzy caterpillars, not
   trending or stuck)
3. **Posterior predictive check:** simulated data should look like
   real data
4. **Residual plots:** no patterns remaining after model fit

## MLflow logging

| Kind | What |
|---|---|
| `params` | model_type (normal/student_t/hetero), n_features, draws, tune, chains, seed, centering |
| `metrics` | elpd_loo, p_loo, coefficients (mean + hdi), sigma, nu (if student-t), rhat_max, ess_min |
| `tags` | data_hash, model_family |
| `artifacts` | posterior/idata.nc, plots/{coefficients.png, residuals.png, ppc.png, sigma_x.png, loo_comparison.png} |

## Common pitfalls

1. **Assuming Gaussian errors by default.** Use Student-t as the
   default likelihood and let the data tell you if Gaussian is
   appropriate (nu >> 30).
2. **Not centering predictors.** Uncentered x creates strong
   posterior correlation between intercept and slope, slowing MCMC
   convergence. Always center, then uncenter for reporting.
3. **Ignoring heteroscedasticity.** Constant-variance models
   underestimate uncertainty where noise is high and overestimate
   where it's low. Plot residuals vs predictors.
4. **Deleting outliers instead of modeling them.** Outlier deletion
   is subjective and loses information. Student-t likelihood
   automatically downweights outliers — let the model handle it.
5. **Comparing models by coefficient similarity to OLS.** The right
   comparison is LOO-CV predictive accuracy, not "which model agrees
   with OLS." The whole point is that OLS is wrong when assumptions
   fail.
6. **Not running posterior predictive checks.** A model with great
   LOO-CV can still be misspecified in ways PPC reveals (e.g., wrong
   tail shape, missed multimodality).
7. **Using informative priors without justification.** Start with
   weakly informative priors (Normal(0, 10) for coefficients,
   HalfNormal(5) for scale). Only tighten if you have real domain
   knowledge.

## Worked example

See `demo.py` (marimo notebook). It generates synthetic data with
planted heteroscedasticity and outliers, fits OLS + three Bayesian
models (Normal, heteroscedastic, Student-t), compares them via
LOO-CV, and shows posterior predictive checks. Run it with:

```
marimo edit --sandbox demo.py
```

## References

- Hogg, Bovy & Lang (2010), "Data analysis recipes: Fitting a model
  to data" (arXiv:1008.4686)
- McElreath (2020), *Statistical Rethinking*, Chapters 4-5
  (regression) and 13-14 (hierarchical)
- Gelman et al. (2013), *Bayesian Data Analysis*, Chapter 14 (GLMs)
