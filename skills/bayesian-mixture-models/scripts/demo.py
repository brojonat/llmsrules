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
#     "scikit-learn>=1.5",
# ]
# ///
"""Worked example for the bayesian-mixture-models bundle.

Self-contained: generates synthetic clustered data, fits a Bayesian
Gaussian mixture model with PyMC, shows soft assignments with
uncertainty, compares with sklearn's EM-based GMM, and demonstrates
model selection for K via LOO-CV. No external data files.

    marimo edit --sandbox demo.py
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
    from sklearn.mixture import GaussianMixture

    return GaussianMixture, az, mo, np, pd, plt, pm, stats


@app.cell
def title(mo):
    mo.md(r"""
    # Bayesian Mixture Models — Soft Clustering with Uncertainty

    K-means gives you hard assignments: each point belongs to exactly
    one cluster. Gaussian mixture models (GMMs) give you **soft
    assignments**: each point has a probability of belonging to each
    cluster. Bayesian GMMs go further — you get **uncertainty on
    everything**: the cluster means, variances, weights, and the
    assignments themselves.

    This notebook covers:

    1. **Bayesian GMM with PyMC** — Dirichlet prior on weights, Normal
       priors on means, InverseGamma on variances
    2. **Soft assignments** — posterior probability of each point
       belonging to each cluster
    3. **Comparison with sklearn EM** — point estimates vs full
       posteriors
    4. **Model selection** — picking K (number of components)
    5. **When mixtures aren't just clustering** — latent heterogeneity,
       zero-inflated models, outlier detection
    """)
    return


@app.cell
def config_section(mo):
    mo.md(r"""
    ## Data configuration
    """)
    return


@app.cell
def config_widgets(mo):
    k_true_slider = mo.ui.slider(
        start=2, stop=5, step=1, value=3,
        label="true K (number of clusters)",
    )
    n_per_cluster_slider = mo.ui.slider(
        start=30, stop=300, step=10, value=100,
        label="points per cluster",
    )
    separation_slider = mo.ui.slider(
        start=1.0, stop=6.0, step=0.5, value=3.0,
        label="cluster separation (higher = easier)",
    )
    mo.vstack([k_true_slider, n_per_cluster_slider, separation_slider])
    return k_true_slider, n_per_cluster_slider, separation_slider


@app.cell
def generate_data(
    k_true_slider,
    mo,
    n_per_cluster_slider,
    np,
    pd,
    separation_slider,
):
    """Generate 2D clustered data with known ground truth."""
    _rng = np.random.default_rng(42)
    k_true = int(k_true_slider.value)
    n_per = int(n_per_cluster_slider.value)
    separation = float(separation_slider.value)

    # Place cluster centers on a circle
    _angles = np.linspace(0, 2 * np.pi, k_true, endpoint=False)
    true_means = np.column_stack([
        separation * np.cos(_angles),
        separation * np.sin(_angles),
    ])

    # Varying cluster sizes (variance)
    true_sigmas = 0.5 + 0.5 * _rng.uniform(size=k_true)

    # Unequal weights
    _raw_weights = _rng.dirichlet(np.ones(k_true) * 3)
    true_weights = _raw_weights

    # Generate data
    _all_x = []
    _all_labels = []
    for _k in range(k_true):
        _n_k = int(n_per * true_weights[_k] / true_weights.min())
        _pts = _rng.normal(
            loc=true_means[_k], scale=true_sigmas[_k], size=(_n_k, 2),
        )
        _all_x.append(_pts)
        _all_labels.append(np.full(_n_k, _k, dtype=int))

    data_x = np.vstack(_all_x)
    true_labels = np.concatenate(_all_labels)
    n_total = len(true_labels)

    df = pd.DataFrame({
        "x0": data_x[:, 0],
        "x1": data_x[:, 1],
        "true_cluster": true_labels,
    })

    _weights_str = ", ".join(f"{w:.2f}" for w in true_weights)
    mo.md(
        f"""
    **Generated:** {n_total} points in {k_true} clusters

    | Cluster | Center | Sigma | Weight |
    |---|---|---|---|
    """
        + "\n".join(
            f"    | {_k} | ({true_means[_k, 0]:.1f}, {true_means[_k, 1]:.1f}) "
            f"| {true_sigmas[_k]:.2f} | {true_weights[_k]:.2f} |"
            for _k in range(k_true)
        )
    )
    return (
        data_x,
        df,
        k_true,
        n_total,
        true_labels,
        true_means,
        true_sigmas,
        true_weights,
    )


@app.cell
def data_plot(data_x, k_true, mo, np, plt, true_labels, true_means):
    _colors = plt.cm.tab10(np.linspace(0, 1, max(k_true, 3)))
    fig_data, _ax = plt.subplots(figsize=(8, 6))

    for _k in range(k_true):
        _mask = true_labels == _k
        _ax.scatter(
            data_x[_mask, 0], data_x[_mask, 1],
            s=15, alpha=0.6, color=_colors[_k],
            label=f"cluster {_k}",
        )
        _ax.scatter(
            true_means[_k, 0], true_means[_k, 1],
            s=200, marker="*", color=_colors[_k],
            edgecolors="black", linewidths=0.8,
        )

    _ax.set_xlabel("x0")
    _ax.set_ylabel("x1")
    _ax.set_title("True clusters (stars = true centers)")
    _ax.legend(fontsize=8)
    _ax.set_aspect("equal")
    fig_data.tight_layout()
    mo.as_html(fig_data)
    return


@app.cell
def sklearn_section(mo):
    mo.md(r"""
    ## Frequentist baseline: sklearn GaussianMixture (EM)

    Sklearn's GMM uses Expectation-Maximization to find maximum
    likelihood estimates. It's fast and gives you soft assignments,
    but no uncertainty on the parameters — the cluster means, variances,
    and weights are point estimates.
    """)
    return


@app.cell
def sklearn_fit(GaussianMixture, data_x, k_true, mo, np, plt, true_labels):
    _gmm = GaussianMixture(
        n_components=k_true, covariance_type="full",
        random_state=42, n_init=5,
    )
    _gmm.fit(data_x)
    sklearn_probs = _gmm.predict_proba(data_x)
    sklearn_labels = _gmm.predict(data_x)

    # Accuracy (accounting for label permutation)
    from itertools import permutations

    _best_acc = 0.0
    for _perm in permutations(range(k_true)):
        _remapped = np.array([_perm[_l] for _l in sklearn_labels])
        _acc = float(np.mean(_remapped == true_labels))
        _best_acc = max(_best_acc, _acc)

    fig_sk, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Hard assignments
    _colors = plt.cm.tab10(np.linspace(0, 1, max(k_true, 3)))
    for _k in range(k_true):
        _mask = sklearn_labels == _k
        _ax1.scatter(
            data_x[_mask, 0], data_x[_mask, 1],
            s=15, alpha=0.6, color=_colors[_k],
        )
    _ax1.scatter(
        _gmm.means_[:, 0], _gmm.means_[:, 1],
        s=200, marker="*", color="black", label="EM centers",
    )
    _ax1.set_title(f"sklearn GMM — hard assignments (acc={_best_acc:.1%})")
    _ax1.legend(fontsize=8)
    _ax1.set_aspect("equal")

    # Soft assignments — entropy of assignment probabilities
    _entropy = -np.sum(
        sklearn_probs * np.log(sklearn_probs + 1e-10), axis=1,
    )
    _sc = _ax2.scatter(
        data_x[:, 0], data_x[:, 1],
        c=_entropy, s=15, alpha=0.7, cmap="YlOrRd",
    )
    fig_sk.colorbar(_sc, ax=_ax2, label="assignment entropy")
    _ax2.set_title("Assignment uncertainty (higher = less certain)")
    _ax2.set_aspect("equal")

    fig_sk.tight_layout()
    mo.as_html(fig_sk)
    return sklearn_labels, sklearn_probs


@app.cell
def bayesian_section(mo):
    mo.md(r"""
    ## Bayesian GMM with PyMC

    The Bayesian model puts priors on everything:

    $$w \sim \text{Dirichlet}(\alpha_1, \ldots, \alpha_K)$$
    $$\mu_k \sim \text{Normal}(0, \tau)$$
    $$\sigma_k \sim \text{HalfNormal}(s)$$
    $$z_i \sim \text{Categorical}(w)$$
    $$x_i \mid z_i = k \sim \text{Normal}(\mu_k, \sigma_k)$$

    PyMC's `NormalMixture` marginalizes out the discrete latent
    variable $z_i$ (cluster assignment), which makes MCMC much more
    efficient than sampling $z$ directly.

    **Label switching:** In a mixture model, swapping cluster labels
    (rename cluster 0 to cluster 1 and vice versa) gives an equally
    valid solution. This creates multimodal posteriors that MCMC
    struggles with. We handle it with ordered means
    (`pm.math.sort`) — constraining $\mu_0 < \mu_1 < \ldots$ breaks
    the symmetry.
    """)
    return


@app.cell
def fit_bayesian(az, data_x, k_true, np, pm):
    """Fit a Bayesian Gaussian mixture model with PyMC."""
    with pm.Model() as mixture_model:
        # Priors on mixture weights
        _w = pm.Dirichlet("w", a=np.ones(k_true) * 2.0)

        # Priors on component means (ordered on first dimension to
        # break label switching symmetry)
        _mu_raw = pm.Normal(
            "mu_raw", mu=0, sigma=5, shape=(k_true, 2),
        )
        # Sort by first coordinate to impose ordering
        _sort_idx = pm.math.argsort(_mu_raw[:, 0])
        _mu = pm.Deterministic("mu", _mu_raw[_sort_idx])

        # Priors on component standard deviations
        _sigma = pm.HalfNormal("sigma", sigma=3, shape=k_true)

        # Likelihood: 2D isotropic Normal mixture
        # NormalMixture works on 1D, so we use Mixture with MvNormal
        _components = [
            pm.MvNormal.dist(
                mu=_mu[_k],
                cov=pm.math.eye(2) * _sigma[_k] ** 2,
            )
            for _k in range(k_true)
        ]
        pm.Mixture("obs", w=_w, comp_dists=_components, observed=data_x)

        idata = pm.sample(
            draws=2000, tune=2000, chains=4,
            random_seed=42, progressbar=False,
            target_accept=0.9,
        )

    # Convergence check
    _summary = az.summary(idata, var_names=["w", "sigma"])
    rhat_ok = bool(np.all(_summary["r_hat"] < 1.05))

    return idata, mixture_model, rhat_ok


@app.cell
def diagnostics(az, idata, mo, rhat_ok):
    _rhat_msg = (
        "all R-hat < 1.05"
        if rhat_ok
        else "WARNING: some R-hat >= 1.05 — increase tune/draws or check model"
    )
    _summary_w = az.summary(idata, var_names=["w"])
    _summary_sigma = az.summary(idata, var_names=["sigma"])
    mo.md(
        f"""
    ## MCMC diagnostics

    **Convergence:** {_rhat_msg}

    ### Mixture weights
    {_summary_w.to_markdown()}

    ### Component scales
    {_summary_sigma.to_markdown()}
    """
    )
    return


@app.cell
def trace_section(az, idata, mo, plt):
    _fig = plt.figure(figsize=(12, 8))
    az.plot_trace(idata, var_names=["w", "sigma"], figsize=(12, 8))
    _fig = plt.gcf()
    _fig.tight_layout()
    mo.as_html(_fig)
    return


@app.cell
def learned_means_plot(
    data_x,
    idata,
    k_true,
    mo,
    np,
    plt,
    true_labels,
    true_means,
):
    """Overlay posterior mean locations with uncertainty ellipses."""
    _mu_samples = idata.posterior["mu"].to_numpy()  # (chains, draws, K, 2)
    _mu_flat = _mu_samples.reshape(-1, k_true, 2)  # (n_samples, K, 2)
    _mu_mean = _mu_flat.mean(axis=0)  # (K, 2)

    _colors = plt.cm.tab10(np.linspace(0, 1, max(k_true, 3)))
    fig_means, _ax = plt.subplots(figsize=(8, 6))

    # Data colored by true label
    for _k in range(k_true):
        _mask = true_labels == _k
        _ax.scatter(
            data_x[_mask, 0], data_x[_mask, 1],
            s=10, alpha=0.3, color="grey",
        )

    # Posterior samples of means (scatter cloud)
    for _k in range(k_true):
        _ax.scatter(
            _mu_flat[::10, _k, 0], _mu_flat[::10, _k, 1],
            s=3, alpha=0.1, color=_colors[_k],
        )
        _ax.scatter(
            _mu_mean[_k, 0], _mu_mean[_k, 1],
            s=150, marker="o", color=_colors[_k],
            edgecolors="black", linewidths=1.5,
            label=f"learned {_k}",
            zorder=5,
        )

    # True centers
    for _k in range(k_true):
        _ax.scatter(
            true_means[_k, 0], true_means[_k, 1],
            s=200, marker="*", color="red",
            edgecolors="black", linewidths=0.8,
            zorder=6,
        )

    _ax.set_xlabel("x0")
    _ax.set_ylabel("x1")
    _ax.set_title(
        "Posterior mean locations (clouds = uncertainty, red stars = truth)"
    )
    _ax.legend(fontsize=8)
    _ax.set_aspect("equal")
    fig_means.tight_layout()
    mo.as_html(fig_means)
    return


@app.cell
def soft_assignment_section(mo):
    mo.md(r"""
    ## Soft assignments — the Bayesian advantage

    Each point gets a **posterior probability of belonging to each
    cluster**, computed by averaging over all posterior samples. Points
    near cluster boundaries have genuinely uncertain assignments —
    this is information that hard clustering throws away.
    """)
    return


@app.cell
def compute_soft_assignments(data_x, idata, k_true, np, pm, stats):
    """Compute posterior assignment probabilities for each data point."""
    _mu_samples = idata.posterior["mu"].to_numpy().reshape(-1, k_true, 2)
    _sigma_samples = idata.posterior["sigma"].to_numpy().reshape(-1, k_true)
    _w_samples = idata.posterior["w"].to_numpy().reshape(-1, k_true)
    _n_samples = _mu_samples.shape[0]
    _n_points = data_x.shape[0]

    # For each posterior sample, compute assignment probabilities
    # using Bayes' rule: P(z=k|x) = w_k * N(x|mu_k,sigma_k) / sum
    _thin = max(1, _n_samples // 200)  # thin for speed
    _assignment_probs = np.zeros((_n_points, k_true))
    _n_used = 0

    for _s in range(0, _n_samples, _thin):
        _log_probs = np.zeros((_n_points, k_true))
        for _k in range(k_true):
            _dist = stats.multivariate_normal(
                mean=_mu_samples[_s, _k],
                cov=np.eye(2) * _sigma_samples[_s, _k] ** 2,
            )
            _log_probs[:, _k] = (
                np.log(_w_samples[_s, _k] + 1e-10)
                + _dist.logpdf(data_x)
            )
        # Normalize (log-sum-exp for numerical stability)
        _max_lp = _log_probs.max(axis=1, keepdims=True)
        _probs = np.exp(_log_probs - _max_lp)
        _probs /= _probs.sum(axis=1, keepdims=True)
        _assignment_probs += _probs
        _n_used += 1

    assignment_probs = _assignment_probs / _n_used
    bayes_labels = assignment_probs.argmax(axis=1)

    return assignment_probs, bayes_labels


@app.cell
def soft_assignment_plot(
    assignment_probs,
    data_x,
    k_true,
    mo,
    np,
    plt,
):
    fig_soft, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(13, 5))

    _colors = plt.cm.tab10(np.linspace(0, 1, max(k_true, 3)))

    # Left: colored by most-probable cluster, alpha = confidence
    _best = assignment_probs.argmax(axis=1)
    _confidence = assignment_probs.max(axis=1)
    for _k in range(k_true):
        _mask = _best == _k
        _ax1.scatter(
            data_x[_mask, 0], data_x[_mask, 1],
            s=15, alpha=_confidence[_mask] * 0.8 + 0.1,
            color=_colors[_k], label=f"cluster {_k}",
        )
    _ax1.set_title("Bayesian GMM — opacity = assignment confidence")
    _ax1.legend(fontsize=8)
    _ax1.set_aspect("equal")

    # Right: assignment entropy
    _entropy = -np.sum(
        assignment_probs * np.log(assignment_probs + 1e-10), axis=1,
    )
    _sc = _ax2.scatter(
        data_x[:, 0], data_x[:, 1],
        c=_entropy, s=15, alpha=0.7, cmap="YlOrRd",
    )
    fig_soft.colorbar(_sc, ax=_ax2, label="assignment entropy")
    _ax2.set_title("Assignment entropy (high = boundary point)")
    _ax2.set_aspect("equal")

    fig_soft.tight_layout()
    mo.as_html(fig_soft)
    return


@app.cell
def comparison_section(mo):
    mo.md(r"""
    ## Bayesian vs sklearn: what do you gain?

    Both give you soft assignments. The Bayesian model additionally
    gives you:

    - **Uncertainty on cluster locations** — not just "the center is
      here" but "the center is probably within this cloud"
    - **Uncertainty on weights** — "cluster 0 has 30-40% of the data,
      not exactly 35%"
    - **Principled model comparison** — LOO-CV to pick K instead of
      BIC/AIC
    - **Regularization via priors** — the Dirichlet prior shrinks
      small clusters toward zero, naturally handling the "empty
      cluster" problem that EM struggles with
    """)
    return


@app.cell
def weight_comparison(
    idata,
    k_true,
    mo,
    np,
    plt,
    sklearn_probs,
    true_weights,
):
    _w_samples = idata.posterior["w"].to_numpy().reshape(-1, k_true)
    _w_mean = _w_samples.mean(axis=0)
    _sklearn_w = sklearn_probs.mean(axis=0)

    # Sort all weights for consistent comparison
    _true_sorted = np.sort(true_weights)[::-1]
    _bayes_sorted = np.sort(_w_mean)[::-1]
    _sk_sorted = np.sort(_sklearn_w)[::-1]

    fig_w, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(13, 4.5))

    # Bar comparison
    _x_pos = np.arange(k_true)
    _width = 0.25
    _ax1.bar(
        _x_pos - _width, _true_sorted, _width,
        color="black", alpha=0.6, label="true",
    )
    _ax1.bar(
        _x_pos, _bayes_sorted, _width,
        color="#228833", alpha=0.7, label="Bayesian",
    )
    _ax1.bar(
        _x_pos + _width, _sk_sorted, _width,
        color="#4477aa", alpha=0.7, label="sklearn EM",
    )
    _ax1.set_xlabel("component (sorted by weight)")
    _ax1.set_ylabel("weight")
    _ax1.set_title("Mixture weight estimates")
    _ax1.set_xticks(_x_pos)
    _ax1.legend(fontsize=8)

    # Posterior distributions of weights
    _colors = plt.cm.tab10(np.linspace(0, 1, max(k_true, 3)))
    for _k in range(k_true):
        _ax2.hist(
            _w_samples[:, _k], bins=40, density=True, alpha=0.5,
            color=_colors[_k], label=f"w[{_k}]",
        )
    _ax2.set_xlabel("weight")
    _ax2.set_ylabel("density")
    _ax2.set_title("Posterior distributions of mixture weights")
    _ax2.legend(fontsize=8)

    fig_w.tight_layout()
    mo.as_html(fig_w)
    return


@app.cell
def model_selection_section(mo):
    mo.md(r"""
    ## Model selection — picking K

    Fit models with K = 2, 3, 4, 5 and compare via LOO-CV. The model
    with the highest `elpd_loo` best predicts held-out data. Unlike
    BIC/AIC, LOO-CV accounts for the full posterior and doesn't rely
    on asymptotic approximations.
    """)
    return


@app.cell
def model_selection(az, data_x, mo, np, pm):
    """Fit mixture models with different K and compare via LOO-CV."""
    _results = {}

    for _k in range(2, 6):
        with pm.Model() as _model:
            _w = pm.Dirichlet("w", a=np.ones(_k) * 2.0)
            _mu = pm.Normal("mu", mu=0, sigma=5, shape=(_k, 2))
            _sigma = pm.HalfNormal("sigma", sigma=3, shape=_k)

            _components = [
                pm.MvNormal.dist(
                    mu=_mu[_j],
                    cov=pm.math.eye(2) * _sigma[_j] ** 2,
                )
                for _j in range(_k)
            ]
            pm.Mixture("obs", w=_w, comp_dists=_components, observed=data_x)

            _idata = pm.sample(
                draws=1000, tune=1500, chains=2,
                random_seed=_k * 10, progressbar=False,
                target_accept=0.9,
            )
            pm.compute_log_likelihood(
                _idata, model=_model, progressbar=False,
            )

        _results[f"K={_k}"] = _idata

    comparison = az.compare(_results, ic="loo")
    mo.md(
        f"""
    ### LOO-CV model comparison

    {comparison.to_markdown()}

    The model ranked first has the best out-of-sample predictive
    accuracy. If the true K is well-separated, the correct K should
    win clearly. If clusters overlap heavily, adjacent K values will
    be close — which is itself informative (the data doesn't strongly
    prefer one K over another).
    """
    )
    return (comparison,)


@app.cell
def applications_section(mo):
    mo.md(r"""
    ## Beyond clustering — why mixture models matter

    Mixture models aren't just for clustering. They're a general tool
    for modeling **latent heterogeneity**:

    **Zero-inflated models:** Your data has too many zeros (e.g.,
    insurance claims, species counts). Model it as a mixture of
    "always zero" (structural zeros) and a count distribution:
    ```python
    pm.ZeroInflatedPoisson("y", psi=psi, mu=mu, observed=y)
    ```

    **Outlier detection:** A 2-component mixture where the "inlier"
    component is tight and the "outlier" component is wide. Points
    assigned to the wide component are outliers — no ad-hoc thresholds
    needed.

    **Regime switching:** Time series where the process switches
    between states (bull/bear market, high/low volatility). Each
    regime is a mixture component.

    **Semi-supervised learning:** You have labels for some points but
    not others. The mixture model uses the unlabeled points to
    better estimate cluster shapes, improving classification on the
    labeled ones.
    """)
    return


@app.cell
def real_world_examples(mo):
    mo.md(r"""
    ## Real-world applications

    Mixture models go far beyond "find the clusters." The core idea —
    **the data was generated by multiple distinct processes** — shows
    up everywhere.

    ### Customer segmentation (RFM analysis)
    - **Features:** recency (days since last purchase), frequency
      (purchases per year), monetary (average order value)
    - **Model:** K=3-5 Gaussian mixture on log-transformed RFM
    - **What you learn:** "VIP" (high freq, high monetary), "at-risk"
      (high recency, formerly active), "casual" (low freq, low
      monetary) — with soft assignments so you know which customers
      are on the boundary between segments
    - **Business action:** different retention campaigns per segment,
      with confidence on which segment each customer belongs to

    ### Anomaly detection (network security, fraud)
    - **Model:** 2-component mixture: "normal" (tight, 95% of data)
      + "anomalous" (wide, 5%)
    - **Features:** request latency, payload size, time since last
      request
    - **What you learn:** posterior P(anomaly | features) for each
      request — no arbitrary threshold, the model learns the boundary
    - **Advantage over rule-based:** adapts to the actual distribution
      of normal traffic, catches novel anomalies that rules miss

    ### Genomics: single-cell RNA-seq clustering
    - **Features:** gene expression levels (1000+ genes, reduced to
      20-50 PCs)
    - **Model:** Bayesian GMM on PCA-reduced expression space
    - **What you learn:** cell types and subtypes with uncertainty —
      "this cell is 70% T-cell, 30% NK-cell" is more informative than
      a hard assignment when studying transition states
    - **Why Bayesian:** small cell counts per subtype, need uncertainty
      to avoid overclaiming rare cell types

    ### Insurance claims: zero-inflated modeling
    - **Model:** 2-component mixture: P(no claim) = w_0,
      P(claim amount | claim) ~ LogNormal
    - **Data:** `(policy_id, claim_amount)` where most entries are $0
    - **What you learn:** the probability of any claim at all (w_0)
      and the distribution of claim sizes conditional on a claim
      occurring — both with uncertainty
    - **PyMC:** `pm.ZeroInflatedLogNormal` or manual Mixture

    ### Financial market regimes
    - **Model:** 2-3 component mixture of Normals on daily returns
    - **Components:** "calm" (low vol, ~12% annualized), "stressed"
      (high vol, ~30%), optionally "crash" (extreme vol, fat tails)
    - **What you learn:** posterior probability of being in each
      regime *today* — drives portfolio allocation, hedging decisions
    - **Extension:** Hidden Markov Model (HMM) adds a transition
      matrix so the regime at time t depends on t-1

    ### Document topic modeling (lightweight alternative to LDA)
    - **Features:** TF-IDF or embedding vectors (reduced to 10-20D)
    - **Model:** GMM on document embeddings
    - **What you learn:** topic clusters with soft assignments —
      a document about "Bayesian A/B testing" might be 60% statistics,
      40% software engineering
    - **When to use:** when you want a quick topic model without the
      complexity of LDA/BERTopic and your corpus is < 50K documents
    """)
    return


@app.cell
def your_data_section(mo):
    mo.md(r"""
    ## Applying to your data

    ### Expected data format

    A mixture model needs a **feature matrix** — one row per
    observation, one column per feature:

    | Column | Type | Description |
    |---|---|---|
    | `feature_0` ... `feature_D` | float | Numeric features |
    | `cluster` | int | (Optional) Ground truth labels for validation |

    ```python
    import ibis

    table = ibis.duckdb.connect().read_parquet("data/customers.parquet")
    feature_cols = ["recency", "frequency", "monetary"]
    X = (
        table
        .select(*feature_cols)
        .execute()
        .to_numpy()
    )
    ```

    ### High-dimensional data (> 5-10 features)

    GMMs struggle in high dimensions:

    - **Full covariance** requires O(D^2) parameters per component —
      with K=5 and D=20, that's 1050 covariance parameters
    - **Curse of dimensionality** — distances become less meaningful,
      clusters are harder to separate
    - **Solution:** reduce dimensionality first with PCA or UMAP, then
      fit the mixture in the reduced space (2-5 dimensions)

    ```python
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    X_scaled = StandardScaler().fit_transform(X)
    X_reduced = PCA(n_components=5).fit_transform(X_scaled)
    # Fit mixture model on X_reduced, not X
    ```

    Alternatively, use **diagonal covariance** (one sigma per
    dimension instead of a full covariance matrix) to reduce
    parameters dramatically.

    ### When mixtures are the wrong tool

    - **Non-ellipsoidal clusters** (crescents, rings, spirals) — GMMs
      assume elliptical shapes. Use HDBSCAN or spectral clustering.
    - **Very large N (> 100K)** with just clustering needed — sklearn
      EM or mini-batch k-means is orders of magnitude faster. Use
      Bayesian GMM only when you need the uncertainty.
    - **Categorical features** — GMMs are for continuous data. For
      mixed types, use latent class analysis or encode categoricals
      first.
    """)
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    1. **Bayesian GMMs give you uncertainty on everything** — cluster
       locations, shapes, weights, and point assignments. EM gives you
       point estimates only.
    2. **Soft assignments are the point.** If a point is 60% cluster A
       and 40% cluster B, that uncertainty matters for downstream
       decisions. Don't throw it away with hard assignments.
    3. **Use LOO-CV to pick K**, not elbow plots or silhouette scores.
       Bayesian model comparison is principled and accounts for model
       complexity automatically.
    4. **Label switching is the main gotcha.** Use ordered means
       (sort on one dimension) to break the symmetry. Without this,
       the posterior is multimodal and MCMC won't converge.
    5. **Mixture models are a general tool**, not just clustering.
       Zero-inflation, outlier detection, regime switching, and
       semi-supervised learning are all mixture problems.

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/bayesian-mixture-models/` directory and your AI
    agent will follow the same patterns on your real data.
    """)
    return


if __name__ == "__main__":
    app.run()
