# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo",
#     "pymc>=5.16",
#     "arviz>=0.19",
#     "numpy>=1.26",
#     "pandas>=2.2",
#     "matplotlib>=3.9",
#     "scipy>=1.13",
# ]
# ///
"""Worked example for the bayesian-regression bundle.

Hogg-inspired Bayesian GLM approach: starts with naive OLS to show
where it breaks, then builds up through homoscedastic Normal,
heteroscedastic Normal, and outlier-robust Student-t models. Compares
all four via LOO-CV. Self-contained synthetic data with planted
heteroscedasticity and outliers.

    marimo edit --sandbox demo.py

Reference: Hogg, Bovy & Lang (2010), "Data analysis recipes: Fitting
a model to data" (arXiv:1008.4686).
"""

import marimo

__generated_with = "0.23.0"
app = marimo.App(width="medium")


@app.cell
def imports():
    import marimo as mo
    import arviz as az
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import pymc as pm
    from scipy import stats

    return az, mo, np, pd, plt, pm, stats


@app.cell
def title(mo):
    mo.md(r"""
    # Bayesian Regression — The Hogg Way

    Most regression tutorials assume constant variance and no outliers.
    Real data violates both. This notebook follows the progression from
    Hogg, Bovy & Lang (2010):

    1. **OLS baseline** — and where it breaks
    2. **Bayesian Normal** — proper uncertainty, same assumptions
    3. **Heteroscedastic** — when variance depends on X
    4. **Robust (Student-t)** — when outliers contaminate the data
    5. **Model comparison** — LOO-CV to pick the right model

    The punchline: the "right" regression model is a generative model
    that matches your data's actual noise structure. Assuming Gaussian
    homoscedastic errors when you have outliers and varying noise
    biases your coefficients and underestimates your uncertainty.
    """)
    return


@app.cell
def data_section(mo):
    mo.md(r"""
    ## Synthetic data with planted problems
    """)
    return


@app.cell
def config_widgets(mo):
    n_points_slider = mo.ui.slider(
        start=50, stop=500, step=25, value=200,
        label="n data points",
    )
    outlier_frac_slider = mo.ui.slider(
        start=0.0, stop=0.20, step=0.02, value=0.08,
        label="outlier fraction",
    )
    hetero_strength_slider = mo.ui.slider(
        start=0.0, stop=2.0, step=0.1, value=1.0,
        label="heteroscedasticity strength (0 = constant variance)",
    )
    mo.vstack([n_points_slider, outlier_frac_slider, hetero_strength_slider])
    return hetero_strength_slider, n_points_slider, outlier_frac_slider


@app.cell
def generate_data(
    hetero_strength_slider,
    mo,
    n_points_slider,
    np,
    outlier_frac_slider,
    pd,
):
    """Generate linear data with heteroscedastic noise and outliers."""
    _rng = np.random.default_rng(42)
    n_points = int(n_points_slider.value)
    outlier_frac = float(outlier_frac_slider.value)
    hetero_strength = float(hetero_strength_slider.value)

    # True parameters
    true_intercept = 2.0
    true_slope = 1.5
    base_sigma = 0.5

    # Generate X
    x = np.sort(_rng.uniform(0, 10, size=n_points))

    # Heteroscedastic noise: sigma grows with x
    sigma_x = base_sigma + hetero_strength * 0.1 * x
    noise = _rng.normal(0, sigma_x)

    # True line + noise
    y_clean = true_intercept + true_slope * x
    y = y_clean + noise

    # Inject outliers: large vertical displacement
    n_outliers = int(n_points * outlier_frac)
    if n_outliers > 0:
        outlier_idx = _rng.choice(n_points, size=n_outliers, replace=False)
        y[outlier_idx] += _rng.normal(0, 8.0, size=n_outliers)
        is_outlier = np.zeros(n_points, dtype=bool)
        is_outlier[outlier_idx] = True
    else:
        is_outlier = np.zeros(n_points, dtype=bool)
        outlier_idx = np.array([], dtype=int)

    df = pd.DataFrame({"x": x, "y": y, "sigma_x": sigma_x, "outlier": is_outlier})

    mo.md(
        f"""
    **Ground truth:** y = {true_intercept} + {true_slope} * x + noise

    - **n = {n_points}**, outlier fraction = {outlier_frac:.0%} ({n_outliers} points)
    - **Heteroscedasticity:** sigma(x) = {base_sigma} + {hetero_strength * 0.1:.2f} * x
      (ranges from {base_sigma:.2f} to {base_sigma + hetero_strength:.2f})
    """
    )
    return (
        base_sigma,
        df,
        hetero_strength,
        is_outlier,
        n_points,
        sigma_x,
        true_intercept,
        true_slope,
        x,
        y,
    )


@app.cell
def data_plot(df, is_outlier, mo, np, plt, true_intercept, true_slope, x, y):
    fig_data, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(13, 4.5))

    # Scatter with outliers highlighted
    _clean = ~is_outlier
    _ax1.scatter(x[_clean], y[_clean], s=15, alpha=0.6, color="#4477aa", label="clean")
    if is_outlier.any():
        _ax1.scatter(
            x[is_outlier], y[is_outlier], s=30, alpha=0.8,
            color="#cc3311", marker="x", label="outlier",
        )
    _xline = np.linspace(0, 10, 100)
    _ax1.plot(
        _xline, true_intercept + true_slope * _xline,
        color="black", ls="--", lw=1.5, label="true line",
    )
    _ax1.set_xlabel("x")
    _ax1.set_ylabel("y")
    _ax1.set_title("Data with true line")
    _ax1.legend(fontsize=8)

    # Residuals vs x to show heteroscedasticity
    _resid = y - (true_intercept + true_slope * x)
    _ax2.scatter(x, _resid, s=15, alpha=0.6, color="#4477aa")
    _ax2.axhline(0, color="grey", ls=":", lw=1)
    _ax2.set_xlabel("x")
    _ax2.set_ylabel("residual (y - true line)")
    _ax2.set_title("Residuals — fan shape = heteroscedasticity")

    fig_data.tight_layout()
    mo.as_html(fig_data)
    return


@app.cell
def ols_section(mo):
    mo.md(r"""
    ## Model 0: OLS baseline

    Ordinary least squares assumes constant variance, Gaussian errors,
    and no outliers. It gives a point estimate with no uncertainty
    on the error model. Let's see where it breaks.
    """)
    return


@app.cell
def ols_fit(mo, np, true_intercept, true_slope, x, y):
    """OLS via normal equations."""
    _X_ols = np.column_stack([np.ones_like(x), x])
    _beta_ols = np.linalg.lstsq(_X_ols, y, rcond=None)[0]
    ols_intercept = float(_beta_ols[0])
    ols_slope = float(_beta_ols[1])
    _resid_ols = y - _X_ols @ _beta_ols
    ols_sigma = float(np.std(_resid_ols))

    mo.md(
        f"""
    | Parameter | OLS estimate | True value | Error |
    |---|---|---|---|
    | intercept | {ols_intercept:.3f} | {true_intercept} | {ols_intercept - true_intercept:+.3f} |
    | slope | {ols_slope:.3f} | {true_slope} | {ols_slope - true_slope:+.3f} |
    | sigma | {ols_sigma:.3f} | (varies) | — |

    OLS gives one number for sigma. It can't tell you that the noise
    is 3x larger at x=10 than x=0, and it gives outliers equal weight
    in the fit.
    """
    )
    return ols_intercept, ols_slope


@app.cell
def bayesian_section(mo):
    mo.md(r"""
    ## Models 1-3: Bayesian progression

    We fit three PyMC models and compare them:

    1. **Normal homoscedastic** — same assumptions as OLS, but with
       full posterior
    2. **Normal heteroscedastic** — log-linear model for sigma(x)
    3. **Student-t robust** — heavy-tailed likelihood to downweight
       outliers
    """)
    return


@app.cell
def fit_models(az, np, pm, x, y):
    """Fit all three Bayesian models."""
    _x_centered = x - x.mean()

    # --- Model 1: Normal homoscedastic ---
    with pm.Model() as model_homo:
        _alpha = pm.Normal("intercept", mu=0, sigma=10)
        _beta = pm.Normal("slope", mu=0, sigma=5)
        _sigma = pm.HalfNormal("sigma", sigma=5)
        _mu = _alpha + _beta * _x_centered
        pm.Normal("y_obs", mu=_mu, sigma=_sigma, observed=y)
        idata_homo = pm.sample(
            draws=2000, tune=1000, chains=4,
            random_seed=42, progressbar=False,
        )

    # --- Model 2: Normal heteroscedastic ---
    with pm.Model() as model_hetero:
        _alpha = pm.Normal("intercept", mu=0, sigma=10)
        _beta = pm.Normal("slope", mu=0, sigma=5)
        # log-linear model for sigma: log(sigma) = gamma0 + gamma1 * x
        _gamma0 = pm.Normal("log_sigma_intercept", mu=0, sigma=2)
        _gamma1 = pm.Normal("log_sigma_slope", mu=0, sigma=1)
        _log_sigma = _gamma0 + _gamma1 * _x_centered
        _sigma = pm.math.exp(_log_sigma)
        _mu = _alpha + _beta * _x_centered
        pm.Normal("y_obs", mu=_mu, sigma=_sigma, observed=y)
        idata_hetero = pm.sample(
            draws=2000, tune=1000, chains=4,
            random_seed=43, progressbar=False,
        )

    # --- Model 3: Student-t robust ---
    with pm.Model() as model_robust:
        _alpha = pm.Normal("intercept", mu=0, sigma=10)
        _beta = pm.Normal("slope", mu=0, sigma=5)
        _sigma = pm.HalfNormal("sigma", sigma=5)
        _nu = pm.Gamma("nu", alpha=2, beta=0.1)  # degrees of freedom
        _mu = _alpha + _beta * _x_centered
        pm.StudentT("y_obs", nu=_nu, mu=_mu, sigma=_sigma, observed=y)
        idata_robust = pm.sample(
            draws=2000, tune=1000, chains=4,
            random_seed=44, progressbar=False,
        )

    # Add x_mean to all idatas for later uncentering
    x_mean = float(x.mean())

    return (
        idata_hetero,
        idata_homo,
        idata_robust,
        model_hetero,
        model_homo,
        model_robust,
        x_mean,
    )


@app.cell
def coefficient_comparison(
    az,
    idata_hetero,
    idata_homo,
    idata_robust,
    mo,
    np,
    true_intercept,
    true_slope,
    x_mean,
):
    """Compare coefficient posteriors across all three models."""

    def _uncenter_summary(idata, x_mean):
        _slopes = idata.posterior["slope"].to_numpy().flatten()
        _intercepts = idata.posterior["intercept"].to_numpy().flatten()
        # Uncenter: original intercept = centered_intercept - slope * x_mean
        _orig_intercepts = _intercepts - _slopes * x_mean
        return {
            "slope_mean": float(np.mean(_slopes)),
            "slope_hdi": az.hdi(_slopes, hdi_prob=0.94),
            "intercept_mean": float(np.mean(_orig_intercepts)),
            "intercept_hdi": az.hdi(_orig_intercepts, hdi_prob=0.94),
        }

    _homo = _uncenter_summary(idata_homo, x_mean)
    _hetero = _uncenter_summary(idata_hetero, x_mean)
    _robust = _uncenter_summary(idata_robust, x_mean)

    mo.md(
        f"""
    ## Coefficient comparison (uncentered, 94% HDI)

    | Model | Intercept | Slope | True |
    |---|---|---|---|
    | **Homoscedastic** | {_homo['intercept_mean']:.3f} [{_homo['intercept_hdi'][0]:.3f}, {_homo['intercept_hdi'][1]:.3f}] | {_homo['slope_mean']:.3f} [{_homo['slope_hdi'][0]:.3f}, {_homo['slope_hdi'][1]:.3f}] | {true_intercept}, {true_slope} |
    | **Heteroscedastic** | {_hetero['intercept_mean']:.3f} [{_hetero['intercept_hdi'][0]:.3f}, {_hetero['intercept_hdi'][1]:.3f}] | {_hetero['slope_mean']:.3f} [{_hetero['slope_hdi'][0]:.3f}, {_hetero['slope_hdi'][1]:.3f}] | {true_intercept}, {true_slope} |
    | **Robust (Student-t)** | {_robust['intercept_mean']:.3f} [{_robust['intercept_hdi'][0]:.3f}, {_robust['intercept_hdi'][1]:.3f}] | {_robust['slope_mean']:.3f} [{_robust['slope_hdi'][0]:.3f}, {_robust['slope_hdi'][1]:.3f}] | {true_intercept}, {true_slope} |

    The robust model should recover the true coefficients best when
    outliers are present. The heteroscedastic model should have
    appropriately wider HDIs at high x and narrower at low x.
    """
    )
    return


@app.cell
def posterior_slopes_plot(
    az,
    idata_hetero,
    idata_homo,
    idata_robust,
    mo,
    plt,
    true_slope,
):
    fig_slopes, _axes = plt.subplots(1, 3, figsize=(14, 4))

    for _ax, _idata, _label, _color in [
        (_axes[0], idata_homo, "Homoscedastic", "#4477aa"),
        (_axes[1], idata_hetero, "Heteroscedastic", "#228833"),
        (_axes[2], idata_robust, "Robust (Student-t)", "#cc3311"),
    ]:
        _samples = _idata.posterior["slope"].to_numpy().flatten()
        _ax.hist(_samples, bins=50, density=True, alpha=0.7, color=_color)
        _ax.axvline(
            true_slope, color="red", ls="--", lw=1.5,
            label=f"true = {true_slope}",
        )
        _hdi = az.hdi(_samples, hdi_prob=0.94)
        _ax.axvspan(_hdi[0], _hdi[1], alpha=0.15, color=_color)
        _ax.set_title(_label)
        _ax.set_xlabel("slope")
        _ax.legend(fontsize=8)

    fig_slopes.suptitle("Posterior of slope across models", fontsize=11)
    fig_slopes.tight_layout()
    mo.as_html(fig_slopes)
    return


@app.cell
def hetero_diagnosis_section(mo):
    mo.md(r"""
    ## Diagnosing heteroscedasticity

    The Hogg paper's key insight: **plot residuals against predictors**.
    If you see a fan shape (variance increasing with x), your model
    needs a heteroscedastic error term. The heteroscedastic model
    learns log(sigma) = gamma_0 + gamma_1 * x, capturing the variance
    structure the homoscedastic model misses.
    """)
    return


@app.cell
def sigma_comparison_plot(
    base_sigma,
    hetero_strength,
    idata_hetero,
    idata_homo,
    mo,
    np,
    plt,
    x,
    x_mean,
):
    """Compare learned sigma(x) from the heteroscedastic model vs truth."""
    _x_grid = np.linspace(0, 10, 100)
    _x_grid_c = _x_grid - x_mean

    # True sigma(x)
    _true_sigma = base_sigma + hetero_strength * 0.1 * _x_grid

    # Homoscedastic: constant sigma
    _homo_sigma_samples = idata_homo.posterior["sigma"].to_numpy().flatten()
    _homo_mean = float(np.mean(_homo_sigma_samples))

    # Heteroscedastic: log(sigma) = gamma0 + gamma1 * x_centered
    _g0 = idata_hetero.posterior["log_sigma_intercept"].to_numpy().flatten()
    _g1 = idata_hetero.posterior["log_sigma_slope"].to_numpy().flatten()
    # Compute sigma(x) for each posterior sample at each x_grid point
    _log_sigma_draws = _g0[:, None] + _g1[:, None] * _x_grid_c[None, :]
    _sigma_draws = np.exp(_log_sigma_draws)
    _sigma_mean = _sigma_draws.mean(axis=0)
    _sigma_lo = np.percentile(_sigma_draws, 3, axis=0)
    _sigma_hi = np.percentile(_sigma_draws, 97, axis=0)

    fig_sigma, _ax = plt.subplots(figsize=(10, 5))
    _ax.plot(_x_grid, _true_sigma, color="black", ls="--", lw=2, label="true sigma(x)")
    _ax.axhline(_homo_mean, color="#4477aa", lw=2, label=f"homoscedastic (sigma={_homo_mean:.2f})")
    _ax.plot(_x_grid, _sigma_mean, color="#228833", lw=2, label="heteroscedastic mean")
    _ax.fill_between(
        _x_grid, _sigma_lo, _sigma_hi,
        alpha=0.2, color="#228833", label="94% CrI",
    )
    _ax.set_xlabel("x")
    _ax.set_ylabel("sigma")
    _ax.set_title("Noise model comparison: constant vs learned sigma(x)")
    _ax.legend(fontsize=9)
    fig_sigma.tight_layout()
    mo.as_html(fig_sigma)
    return


@app.cell
def robust_section(mo):
    mo.md(r"""
    ## Outlier robustness — Student-t vs Normal

    The Student-t distribution has heavier tails than the Normal. By
    estimating the degrees-of-freedom parameter nu, the model learns
    *how heavy* the tails need to be. Low nu (~3-5) = lots of outliers.
    High nu (~30+) = essentially Normal.

    This is the Hogg paper's main recommendation: **never assume
    Gaussian errors. Use Student-t as the default likelihood** and let
    the data tell you whether Gaussian is appropriate (nu >> 30).
    """)
    return


@app.cell
def nu_posterior(idata_robust, mo, np, plt):
    _nu_samples = idata_robust.posterior["nu"].to_numpy().flatten()
    _nu_mean = float(np.mean(_nu_samples))

    fig_nu, _ax = plt.subplots(figsize=(8, 4))
    _ax.hist(_nu_samples, bins=60, density=True, alpha=0.7, color="#cc3311")
    _ax.axvline(_nu_mean, color="black", ls="-", lw=2, label=f"mean = {_nu_mean:.1f}")
    _ax.axvline(30, color="grey", ls=":", lw=1, label="nu=30 (approx Normal)")
    _ax.set_xlabel("degrees of freedom (nu)")
    _ax.set_ylabel("density")
    _ax.set_title("Posterior of nu — lower = heavier tails = more outlier robustness")
    _ax.legend(fontsize=9)
    _ax.set_xlim(0, min(100, float(np.percentile(_nu_samples, 99)) * 1.2))
    fig_nu.tight_layout()
    mo.as_html(fig_nu)
    return


@app.cell
def model_comparison_section(mo):
    mo.md(r"""
    ## Model comparison — LOO-CV

    ArviZ's `az.compare()` uses Pareto-smoothed importance sampling
    leave-one-out cross-validation (PSIS-LOO-CV) to rank models by
    out-of-sample predictive accuracy. The model with the highest
    `elpd_loo` (expected log pointwise predictive density) is the best
    fit for the data's actual generative process.
    """)
    return


@app.cell
def loo_comparison(
    az,
    idata_hetero,
    idata_homo,
    idata_robust,
    mo,
    model_hetero,
    model_homo,
    model_robust,
    pm,
):
    """Compare models via LOO-CV."""
    # Compute log-likelihood for each model (needed for LOO)
    pm.compute_log_likelihood(idata_homo, model=model_homo, progressbar=False)
    pm.compute_log_likelihood(idata_hetero, model=model_hetero, progressbar=False)
    pm.compute_log_likelihood(idata_robust, model=model_robust, progressbar=False)

    comparison = az.compare(
        {
            "homoscedastic": idata_homo,
            "heteroscedastic": idata_hetero,
            "robust_student_t": idata_robust,
        },
        ic="loo",
    )

    mo.md(
        f"""
    ## LOO-CV model comparison

    {comparison.to_markdown()}

    **Read this as:** the model ranked first has the best
    out-of-sample predictive accuracy. `elpd_diff` shows how much
    worse each subsequent model is. `weight` is the stacking weight
    — the optimal mixture of models for prediction.

    If your data has both heteroscedasticity and outliers, the robust
    model usually wins. If it has only heteroscedasticity (no outliers),
    the heteroscedastic model wins. The homoscedastic model should
    only win on clean, constant-variance data.
    """
    )
    return (comparison,)


@app.cell
def fit_lines_plot(
    idata_hetero,
    idata_homo,
    idata_robust,
    is_outlier,
    mo,
    np,
    ols_intercept,
    ols_slope,
    plt,
    true_intercept,
    true_slope,
    x,
    x_mean,
    y,
):
    """Overlay all fitted lines on the data."""
    _x_grid = np.linspace(0, 10, 200)

    fig_fits, _ax = plt.subplots(figsize=(12, 6))

    # Data
    _clean = ~is_outlier
    _ax.scatter(x[_clean], y[_clean], s=12, alpha=0.4, color="grey", zorder=1)
    if is_outlier.any():
        _ax.scatter(
            x[is_outlier], y[is_outlier], s=25, alpha=0.7,
            color="#cc3311", marker="x", zorder=2, label="outlier",
        )

    # True line
    _ax.plot(
        _x_grid, true_intercept + true_slope * _x_grid,
        color="black", ls="--", lw=2, label="true", zorder=5,
    )

    # OLS
    _ax.plot(
        _x_grid, ols_intercept + ols_slope * _x_grid,
        color="orange", lw=2, label="OLS", zorder=4,
    )

    # Bayesian models: posterior mean lines
    for _idata, _label, _color in [
        (idata_homo, "Bayes Normal", "#4477aa"),
        (idata_hetero, "Bayes Hetero", "#228833"),
        (idata_robust, "Bayes Student-t", "#cc3311"),
    ]:
        _slopes = _idata.posterior["slope"].to_numpy().flatten()
        _intercepts = _idata.posterior["intercept"].to_numpy().flatten()
        _orig_intercepts = _intercepts - _slopes * x_mean
        _y_grid = np.mean(_orig_intercepts) + np.mean(_slopes) * _x_grid
        _ax.plot(_x_grid, _y_grid, lw=2, color=_color, label=_label, zorder=4)

    _ax.set_xlabel("x")
    _ax.set_ylabel("y")
    _ax.set_title("All fitted lines overlaid")
    _ax.legend(fontsize=9, loc="upper left")
    fig_fits.tight_layout()
    mo.as_html(fig_fits)
    return


@app.cell
def predictive_section(mo):
    mo.md(r"""
    ## Posterior predictive check

    The strongest diagnostic: **generate fake data from the fitted
    model and compare it to the real data**. If the model is correct,
    simulated data should look like the real data.
    """)
    return


@app.cell
def ppc_plot(idata_robust, mo, model_robust, np, plt, pm, y):
    """Posterior predictive check for the robust model."""
    with model_robust:
        _ppc = pm.sample_posterior_predictive(
            idata_robust, random_seed=42, progressbar=False,
        )

    _y_rep = _ppc.posterior_predictive["y_obs"].to_numpy().reshape(-1, len(y))

    fig_ppc, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(13, 4.5))

    # Density overlay: real vs simulated
    for _i in range(min(50, _y_rep.shape[0])):
        _ax1.hist(
            _y_rep[_i], bins=40, density=True, alpha=0.02,
            color="#228833", histtype="stepfilled",
        )
    _ax1.hist(
        y, bins=40, density=True, alpha=0.8,
        color="black", histtype="step", lw=2, label="observed",
    )
    _ax1.set_xlabel("y")
    _ax1.set_title("PPC: observed (black) vs simulated (green)")
    _ax1.legend(fontsize=9)

    # Mean and std of replications vs observed
    _y_rep_means = _y_rep.mean(axis=1)
    _ax2.hist(
        _y_rep_means, bins=40, density=True, alpha=0.7,
        color="#228833", label="simulated means",
    )
    _ax2.axvline(
        float(np.mean(y)), color="black", lw=2,
        label=f"observed mean = {np.mean(y):.2f}",
    )
    _ax2.set_xlabel("mean(y)")
    _ax2.set_title("PPC: distribution of replicated means")
    _ax2.legend(fontsize=9)

    fig_ppc.tight_layout()
    mo.as_html(fig_ppc)
    return


@app.cell
def glm_section(mo):
    mo.md(r"""
    ## Beyond linear — the GLM generalization

    Everything above extends naturally to GLMs:

    | Response type | Link function | Likelihood |
    |---|---|---|
    | Continuous, unbounded | identity | Normal / Student-t |
    | Binary (0/1) | logit | Bernoulli |
    | Count (non-negative integer) | log | Poisson / NegBinomial |
    | Positive continuous | log | Gamma / LogNormal |
    | Bounded [0, 1] | logit | Beta |

    The Hogg approach applies to all of them: **start with the
    simplest likelihood, check residuals and PPC, upgrade the
    likelihood to match what you actually see.**

    ```python
    # Example: Poisson GLM for count data
    with pm.Model():
        beta = pm.Normal("beta", 0, 1, shape=n_features)
        alpha = pm.Normal("alpha", 0, 5)
        mu = pm.math.exp(alpha + X @ beta)  # log link
        pm.Poisson("y", mu=mu, observed=y_counts)
    ```
    """)
    return


@app.cell
def real_world_examples(mo):
    mo.md(r"""
    ## Real-world applications

    Bayesian regression shines when you need **interpretable
    coefficients with honest uncertainty** and your data violates the
    textbook assumptions (constant variance, no outliers). Here are
    scenarios where the Hogg approach pays off.

    ### Real estate pricing
    - **Model:** price ~ bedrooms + sqft + age + location
    - **Why Bayesian:** variance is heteroscedastic — a $5M mansion
      has much more price uncertainty than a $200K condo. Model
      log(sigma) as a function of price tier.
    - **Likelihood:** Normal (or Student-t for the occasional
      foreclosure sold at 40% of market value)
    - **Data:** `(price, bedrooms, sqft, year_built, zip_code)`

    ### Manufacturing quality control
    - **Model:** defect_rate ~ temperature + pressure + humidity
    - **Why Bayesian:** you need credible intervals on each
      coefficient to set process control limits. "Temperature
      increases defect rate by 0.3-0.7% per degree" is actionable;
      "coefficient = 0.5" is not.
    - **Likelihood:** Beta regression (defect rate is bounded 0-1)
    - **Extension:** hierarchical — partial pooling across production
      lines (each line has its own baseline but shares the
      temperature effect)

    ### Clinical dose-response
    - **Model:** response ~ log(dose) with Emax or sigmoidal shape
    - **Why Bayesian:** small sample sizes (30-100 patients per arm),
      strong prior information from pre-clinical studies, and
      regulatory requirement for full uncertainty quantification
    - **Likelihood:** Normal for continuous endpoints, Bernoulli for
      binary (responder/non-responder)
    - **Gotcha:** use Student-t — clinical data always has outliers
      (protocol deviations, measurement errors)

    ### Marketing mix modeling
    - **Model:** revenue ~ TV_spend + digital_spend + seasonality
    - **Why Bayesian:** carryover effects (TV ads have delayed impact),
      diminishing returns (saturation curves), and management wants
      credible intervals for ROI per channel, not just point estimates
    - **Likelihood:** LogNormal (revenue is positive and right-skewed)
    - **Extension:** hierarchical across regions — each market has its
      own coefficients but borrows strength from the national model

    ### Energy demand forecasting
    - **Model:** demand ~ temperature + hour_of_day + day_of_week
    - **Why Bayesian:** demand variance changes with temperature
      (extreme heat/cold → more unpredictable load). Heteroscedastic
      model gives wider prediction intervals on extreme days.
    - **Likelihood:** Normal with log-linear sigma
    - **Optimization link:** use the posterior predictive distribution
      to set reserve capacity — this is a decision analysis problem
      (see `bayesian-decision-analysis` bundle)

    ### Insurance loss modeling
    - **Model:** claim_amount ~ age + coverage_type + region
    - **Why Bayesian:** heavy-tailed claim distributions (most claims
      are small, a few are catastrophic). Student-t or LogNormal
      likelihood captures this naturally.
    - **Likelihood:** LogNormal or Gamma (positive continuous, right-
      skewed). Zero-inflated variant if most policies have zero claims.
    - **Extension:** hierarchical across policy types with partial
      pooling
    """)
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    The Hogg approach to regression:

    1. **Start with OLS** to get a baseline, then check residuals for
       heteroscedasticity (fan shape) and outliers (large deviations).
    2. **Fit the Bayesian Normal** to get proper uncertainty. If
       residuals look fine, you're done.
    3. **Add heteroscedasticity** if variance depends on predictors.
       Model log(sigma) as a linear function of x — the model learns
       the noise structure.
    4. **Use Student-t as your default likelihood.** It reduces to
       Normal when nu is large and gracefully handles outliers when
       nu is small. Let the data decide.
    5. **Compare models with LOO-CV.** Don't guess which model is
       "right" — let predictive accuracy decide.

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/bayesian-regression/` directory and your AI agent
    will follow the same workflow on your real data.
    """)
    return


if __name__ == "__main__":
    app.run()
