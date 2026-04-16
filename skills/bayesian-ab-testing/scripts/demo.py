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
"""Worked example for the bayesian-ab-testing bundle.

Self-contained: generates its own synthetic A/B test data, fits a
Beta-Binomial PyMC model, and lets you interactively explore the
posterior, expected loss, and decision thresholds. No external data
files. No MLflow. No datagen.

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

    return az, mo, np, pd, plt, pm, stats


@app.cell
def title(mo):
    mo.md(r"""
    # Bayesian A/B Testing with PyMC

    A worked example covering the four things that turn "which variant
    won?" into a decision you can defend:

    1. **Posterior distributions** over each variant's conversion rate
    2. **P(B > A)** — the probability that B actually beats A
    3. **Expected loss** — how much you lose (in conversion-rate points)
       by picking the wrong variant
    4. **ROPE** (Region of Practical Equivalence) — is the difference
       big enough to matter?

    No p-values. No "statistical significance." Just direct answers to
    the questions stakeholders actually ask.
    """)
    return


@app.cell
def config_section(mo):
    mo.md(r"""
    ## Experiment configuration

    Adjust the ground-truth conversion rates, sample sizes, and prior
    strength below. The model re-fits automatically.
    """)
    return


@app.cell
def config_widgets(mo):
    true_p_a_slider = mo.ui.slider(
        start=0.01, stop=0.30, step=0.005, value=0.05,
        label="true p_A (control conversion rate)",
    )
    true_p_b_slider = mo.ui.slider(
        start=0.01, stop=0.30, step=0.005, value=0.065,
        label="true p_B (treatment conversion rate)",
    )
    n_a_slider = mo.ui.slider(
        start=100, stop=10000, step=100, value=2000,
        label="n_A (control visitors)",
    )
    n_b_slider = mo.ui.slider(
        start=100, stop=10000, step=100, value=2000,
        label="n_B (treatment visitors)",
    )
    prior_strength_slider = mo.ui.slider(
        start=0.5, stop=10.0, step=0.5, value=1.0,
        label="prior strength (Beta alpha=beta=this)",
    )
    mo.vstack([
        true_p_a_slider,
        true_p_b_slider,
        n_a_slider,
        n_b_slider,
        prior_strength_slider,
    ])
    return (
        n_a_slider,
        n_b_slider,
        prior_strength_slider,
        true_p_a_slider,
        true_p_b_slider,
    )


@app.cell
def generate_data(
    mo,
    n_a_slider,
    n_b_slider,
    np,
    true_p_a_slider,
    true_p_b_slider,
):
    """Generate synthetic A/B test data from two Bernoulli arms."""
    rng = np.random.default_rng(42)
    true_p_a = true_p_a_slider.value
    true_p_b = true_p_b_slider.value
    n_a = int(n_a_slider.value)
    n_b = int(n_b_slider.value)

    conversions_a = int(rng.binomial(n_a, true_p_a))
    conversions_b = int(rng.binomial(n_b, true_p_b))

    true_lift = true_p_b - true_p_a
    true_rel_lift = true_lift / true_p_a if true_p_a > 0 else float("inf")

    mo.md(
        f"""
    ## Simulated experiment

    | | Control (A) | Treatment (B) |
    |---|---|---|
    | **Visitors** | {n_a:,} | {n_b:,} |
    | **Conversions** | {conversions_a:,} | {conversions_b:,} |
    | **Observed rate** | {conversions_a / n_a:.4f} | {conversions_b / n_b:.4f} |

    **Ground truth:** p_A = {true_p_a}, p_B = {true_p_b},
    lift = {true_lift:+.4f} ({true_rel_lift:+.1%} relative)
    """
    )
    return conversions_a, conversions_b, n_a, n_b, true_lift, true_p_a, true_p_b


@app.cell
def model_section(mo):
    mo.md(r"""
    ## PyMC model — Beta-Binomial

    The model is conjugate, so we *could* compute the posterior in closed
    form. We use PyMC anyway because:

    - Real A/B tests often need non-conjugate extensions (covariates,
      hierarchical pooling across segments, time-varying rates)
    - The sampling + ArviZ diagnostics pattern transfers to those harder
      models unchanged
    - It proves the plumbing works before you need it for something complex

    $$p_A \sim \text{Beta}(\alpha_0, \beta_0)$$
    $$p_B \sim \text{Beta}(\alpha_0, \beta_0)$$
    $$\text{conversions}_A \sim \text{Binomial}(n_A, p_A)$$
    $$\text{conversions}_B \sim \text{Binomial}(n_B, p_B)$$
    $$\delta = p_B - p_A$$
    """)
    return


@app.cell
def fit_model(
    az,
    conversions_a,
    conversions_b,
    n_a,
    n_b,
    np,
    pm,
    prior_strength_slider,
):
    """Fit the Beta-Binomial A/B test model with PyMC."""
    prior_alpha = prior_strength_slider.value
    prior_beta = prior_strength_slider.value

    with pm.Model() as ab_model:
        # Priors — symmetric Beta (uniform when alpha=beta=1)
        p_a = pm.Beta("p_A", alpha=prior_alpha, beta=prior_beta)
        p_b = pm.Beta("p_B", alpha=prior_alpha, beta=prior_beta)

        # Deterministic quantities of interest
        delta = pm.Deterministic("delta", p_b - p_a)
        pm.Deterministic("relative_lift", (p_b - p_a) / p_a)

        # Likelihood — sufficient statistics (Binomial, not N Bernoulli)
        pm.Binomial("obs_A", n=n_a, p=p_a, observed=conversions_a)
        pm.Binomial("obs_B", n=n_b, p=p_b, observed=conversions_b)

        # Sample
        idata = pm.sample(
            draws=2000,
            tune=1000,
            chains=4,
            random_seed=42,
            progressbar=False,
        )

    # Extract posterior samples
    p_a_samples = idata.posterior["p_A"].to_numpy().flatten()
    p_b_samples = idata.posterior["p_B"].to_numpy().flatten()
    delta_samples = idata.posterior["delta"].to_numpy().flatten()
    rel_lift_samples = idata.posterior["relative_lift"].to_numpy().flatten()

    # Convergence check
    summary = az.summary(idata, var_names=["p_A", "p_B", "delta"])
    rhat_ok = bool(np.all(summary["r_hat"] < 1.01))

    return (
        ab_model,
        delta_samples,
        idata,
        p_a_samples,
        p_b_samples,
        prior_alpha,
        prior_beta,
        rel_lift_samples,
        rhat_ok,
        summary,
    )


@app.cell
def diagnostics_section(mo, rhat_ok, summary):
    rhat_status = "all R-hat < 1.01" if rhat_ok else "WARNING: some R-hat >= 1.01 -- increase draws/tune"
    mo.md(
        f"""
    ## MCMC diagnostics

    **Convergence:** {rhat_status}

    {summary.to_markdown()}

    If R-hat > 1.01 or ESS < 400, the sampler hasn't converged —
    increase `draws` or `tune`, or check the model for
    identifiability issues.
    """
    )
    return


@app.cell
def trace_plot(az, idata, mo, plt):
    fig_trace = plt.figure(figsize=(12, 6))
    az.plot_trace(
        idata,
        var_names=["p_A", "p_B", "delta"],
        figsize=(12, 6),
    )
    fig_trace = plt.gcf()
    fig_trace.tight_layout()
    mo.as_html(fig_trace)
    return


@app.cell
def posterior_section(mo):
    mo.md(r"""
    ## Posterior distributions

    The posterior over each conversion rate, and the posterior over
    their difference (delta = p_B - p_A). The red dashed line marks
    the ground truth; the shaded region is the 94% HDI.
    """)
    return


@app.cell
def posterior_plot(
    az,
    delta_samples,
    mo,
    np,
    p_a_samples,
    p_b_samples,
    plt,
    true_lift,
    true_p_a,
    true_p_b,
):
    fig_post, axes_post = plt.subplots(1, 3, figsize=(14, 4))

    # p_A posterior
    _ax = axes_post[0]
    _ax.hist(p_a_samples, bins=60, density=True, alpha=0.7, color="#4477aa")
    _ax.axvline(true_p_a, color="red", ls="--", lw=1.5, label=f"true = {true_p_a}")
    hdi_a = az.hdi(p_a_samples, hdi_prob=0.94)
    _ax.axvspan(hdi_a[0], hdi_a[1], alpha=0.15, color="#4477aa")
    _ax.set_title("p_A (control)")
    _ax.set_xlabel("conversion rate")
    _ax.legend(fontsize=8)

    # p_B posterior
    _ax = axes_post[1]
    _ax.hist(p_b_samples, bins=60, density=True, alpha=0.7, color="#cc3311")
    _ax.axvline(true_p_b, color="red", ls="--", lw=1.5, label=f"true = {true_p_b}")
    hdi_b = az.hdi(p_b_samples, hdi_prob=0.94)
    _ax.axvspan(hdi_b[0], hdi_b[1], alpha=0.15, color="#cc3311")
    _ax.set_title("p_B (treatment)")
    _ax.set_xlabel("conversion rate")
    _ax.legend(fontsize=8)

    # delta posterior
    _ax = axes_post[2]
    _ax.hist(delta_samples, bins=60, density=True, alpha=0.7, color="#228833")
    _ax.axvline(0, color="grey", ls=":", lw=1, label="zero (no effect)")
    _ax.axvline(true_lift, color="red", ls="--", lw=1.5, label=f"true = {true_lift:+.4f}")
    hdi_d = az.hdi(delta_samples, hdi_prob=0.94)
    _ax.axvspan(hdi_d[0], hdi_d[1], alpha=0.15, color="#228833")
    _ax.set_title("delta = p_B - p_A")
    _ax.set_xlabel("conversion rate difference")
    _ax.legend(fontsize=8)

    fig_post.tight_layout()
    mo.as_html(fig_post)
    return


@app.cell
def decision_section(mo):
    mo.md(r"""
    ## Decision metrics — the whole point

    Bayesian A/B testing answers business questions directly from
    posterior samples. No p-values, no "significance levels" — just
    probabilities and expected costs.
    """)
    return


@app.cell
def rope_widget(mo):
    rope_slider = mo.ui.slider(
        start=0.0, stop=0.02, step=0.001, value=0.005,
        label="ROPE half-width (minimum practically significant difference)",
        full_width=True,
    )
    rope_slider
    return (rope_slider,)


@app.cell
def decision_metrics(
    delta_samples,
    mo,
    np,
    p_a_samples,
    p_b_samples,
    rel_lift_samples,
    rope_slider,
):
    _rope = rope_slider.value

    # Core decision metrics from posterior samples
    prob_b_better = float(np.mean(delta_samples > 0))
    prob_a_better = float(np.mean(delta_samples < 0))
    prob_b_better_by_rope = float(np.mean(delta_samples > _rope))
    prob_practical_equiv = float(
        np.mean((delta_samples > -_rope) & (delta_samples < _rope))
    )

    # Expected loss: what you give up by choosing the wrong arm
    # If you pick B but A is actually better, your loss is (p_A - p_B)
    # clipped to zero when B is actually better
    loss_choosing_b = float(np.mean(np.maximum(p_a_samples - p_b_samples, 0)))
    loss_choosing_a = float(np.mean(np.maximum(p_b_samples - p_a_samples, 0)))

    # Posterior mean lift
    mean_delta = float(np.mean(delta_samples))
    mean_rel_lift = float(np.mean(rel_lift_samples))

    # Decision recommendation
    if loss_choosing_b < loss_choosing_a and prob_b_better_by_rope > 0.90:
        recommendation = "**Ship B.** High confidence that B beats A by a practically significant margin."
    elif loss_choosing_a < loss_choosing_b and (1 - prob_b_better_by_rope) > 0.90:
        recommendation = "**Keep A.** B is not better (or the difference is too small to matter)."
    elif prob_practical_equiv > 0.50:
        recommendation = "**Practically equivalent.** The difference is within the ROPE — pick whichever is cheaper to maintain."
    else:
        recommendation = "**Keep collecting data.** Neither arm has a clear enough advantage yet."

    mo.md(
        f"""
    ### Results (ROPE = +/- {_rope:.3f})

    | Metric | Value |
    |---|---|
    | **P(B > A)** | {prob_b_better:.4f} |
    | **P(A > B)** | {prob_a_better:.4f} |
    | **P(B > A + ROPE)** | {prob_b_better_by_rope:.4f} |
    | **P(practically equivalent)** | {prob_practical_equiv:.4f} |
    | **Expected loss choosing B** | {loss_choosing_b:.6f} |
    | **Expected loss choosing A** | {loss_choosing_a:.6f} |
    | **Posterior mean lift** | {mean_delta:+.5f} ({mean_rel_lift:+.1%} relative) |

    ### Recommendation

    {recommendation}

    **How to read expected loss:** if you pick B and run it forever, you
    lose ~{loss_choosing_b:.6f} conversion-rate points vs the optimal
    choice. If you pick A, you lose ~{loss_choosing_a:.6f}. **Pick the
    arm with lower expected loss.** When both losses are tiny (< 0.0001),
    the arms are effectively equivalent.
    """
    )
    return loss_choosing_a, loss_choosing_b, prob_b_better


@app.cell
def expected_loss_plot(
    delta_samples,
    loss_choosing_a,
    loss_choosing_b,
    mo,
    np,
    plt,
    rope_slider,
):
    """Visualize the expected loss for each decision."""
    _rope = rope_slider.value

    fig_loss, axes_loss = plt.subplots(1, 2, figsize=(13, 4.5))

    # Left: posterior of delta with ROPE shaded
    _ax = axes_loss[0]
    _ax.hist(delta_samples, bins=80, density=True, alpha=0.7, color="#228833")
    _ax.axvline(0, color="grey", ls=":", lw=1)
    _ax.axvspan(-_rope, _rope, alpha=0.2, color="orange", label=f"ROPE (+-{_rope})")
    # Shade the "B wins" region
    _ax.axvspan(
        _rope, float(np.max(delta_samples)) + 0.001,
        alpha=0.1, color="#cc3311", label="B wins (beyond ROPE)",
    )
    _ax.set_xlabel("delta (p_B - p_A)")
    _ax.set_ylabel("density")
    _ax.set_title("Posterior of delta with ROPE")
    _ax.legend(fontsize=8, loc="upper right")

    # Right: expected loss comparison
    _ax = axes_loss[1]
    arms = ["Choose A\n(keep control)", "Choose B\n(ship treatment)"]
    losses = [loss_choosing_a, loss_choosing_b]
    colors = ["#4477aa", "#cc3311"]
    _bars = _ax.bar(arms, losses, color=colors, width=0.5)
    for _bar, _val in zip(_bars, losses):
        _ax.text(
            _bar.get_x() + _bar.get_width() / 2,
            _val,
            f"{_val:.6f}",
            ha="center", va="bottom", fontsize=9,
        )
    _ax.set_ylabel("expected loss (conversion-rate points)")
    _ax.set_title("Expected loss by decision")
    _ax.set_ylim(0, max(losses) * 1.3 if max(losses) > 0 else 0.001)

    fig_loss.tight_layout()
    mo.as_html(fig_loss)
    return


@app.cell
def conjugate_section(mo):
    mo.md(r"""
    ## Sanity check — closed-form conjugate posterior

    Because Beta-Binomial is conjugate, the exact posterior is:
    $$p_A \mid \text{data} \sim \text{Beta}(\alpha_0 + k_A,\; \beta_0 + n_A - k_A)$$

    We can verify PyMC's MCMC samples match the analytic answer.
    This is the kind of thing you do **once** to build trust in your
    pipeline, then move on to models where the closed form doesn't exist.
    """)
    return


@app.cell
def conjugate_check(
    conversions_a,
    conversions_b,
    mo,
    n_a,
    n_b,
    np,
    p_a_samples,
    p_b_samples,
    plt,
    prior_alpha,
    prior_beta,
    stats,
):
    # Closed-form posteriors
    post_alpha_a = prior_alpha + conversions_a
    post_beta_a = prior_beta + n_a - conversions_a
    post_alpha_b = prior_alpha + conversions_b
    post_beta_b = prior_beta + n_b - conversions_b

    analytic_a = stats.beta(post_alpha_a, post_beta_a)
    analytic_b = stats.beta(post_alpha_b, post_beta_b)

    fig_conj, axes_conj = plt.subplots(1, 2, figsize=(12, 4))

    for _ax, _samples, _dist, _label, _color in [
        (axes_conj[0], p_a_samples, analytic_a, "p_A", "#4477aa"),
        (axes_conj[1], p_b_samples, analytic_b, "p_B", "#cc3311"),
    ]:
        _ax.hist(_samples, bins=60, density=True, alpha=0.5, color=_color, label="MCMC")
        _x = np.linspace(float(_dist.ppf(0.001)), float(_dist.ppf(0.999)), 300)
        _ax.plot(_x, _dist.pdf(_x), lw=2, color="black", label="analytic")
        _ax.set_title(f"{_label}: MCMC vs closed-form Beta({_dist.args[0]:.0f}, {_dist.args[1]:.0f})")
        _ax.set_xlabel("conversion rate")
        _ax.legend(fontsize=8)

    fig_conj.tight_layout()
    mo.as_html(fig_conj)
    return


@app.cell
def sample_size_section(mo):
    mo.md(r"""
    ## How much data do I need?

    One of Bayesian A/B testing's killer features: you can compute
    **expected loss as a function of sample size** by running the
    conjugate update for increasing n. No power analysis tables needed.

    The curve below shows how expected loss for the *wrong* decision
    shrinks as you collect more data. When it drops below your loss
    tolerance, you can stop the experiment.
    """)
    return


@app.cell
def sample_size_curve(
    mo,
    np,
    plt,
    prior_alpha,
    prior_beta,
    stats,
    true_p_a,
    true_p_b,
):
    """Expected loss vs sample size using conjugate closed-form."""
    sample_sizes = np.concatenate([
        np.arange(50, 500, 50),
        np.arange(500, 2001, 100),
        np.arange(2500, 10001, 500),
    ])
    rng_ss = np.random.default_rng(123)
    n_mc = 5000  # Monte Carlo draws for each sample size

    losses_b = []
    losses_a = []
    prob_b_wins = []

    for n in sample_sizes:
        # Simulate observed conversions at this sample size
        k_a = int(rng_ss.binomial(int(n), true_p_a))
        k_b = int(rng_ss.binomial(int(n), true_p_b))

        # Conjugate posterior
        post_a = stats.beta(prior_alpha + k_a, prior_beta + int(n) - k_a)
        post_b = stats.beta(prior_alpha + k_b, prior_beta + int(n) - k_b)

        # Draw from posteriors
        draws_a = post_a.rvs(n_mc, random_state=rng_ss)
        draws_b = post_b.rvs(n_mc, random_state=rng_ss)

        # Expected losses
        losses_b.append(float(np.mean(np.maximum(draws_a - draws_b, 0))))
        losses_a.append(float(np.mean(np.maximum(draws_b - draws_a, 0))))
        prob_b_wins.append(float(np.mean(draws_b > draws_a)))

    fig_ss, axes_ss = plt.subplots(1, 2, figsize=(13, 4.5))

    _ax = axes_ss[0]
    _ax.plot(sample_sizes, losses_b, lw=2, color="#cc3311", label="loss if choose B (wrong)")
    _ax.plot(sample_sizes, losses_a, lw=2, color="#4477aa", label="loss if choose A (wrong)")
    _ax.axhline(0.0001, color="grey", ls="--", lw=1, label="typical tolerance (0.01%)")
    _ax.set_xlabel("visitors per arm")
    _ax.set_ylabel("expected loss (conversion-rate points)")
    _ax.set_title("Expected loss vs sample size")
    _ax.legend(fontsize=8)
    _ax.set_yscale("log")

    _ax = axes_ss[1]
    _ax.plot(sample_sizes, prob_b_wins, lw=2, color="#228833")
    _ax.axhline(0.95, color="grey", ls="--", lw=1, label="95% threshold")
    _ax.set_xlabel("visitors per arm")
    _ax.set_ylabel("P(B > A)")
    _ax.set_title("Confidence that B wins vs sample size")
    _ax.set_ylim(0.4, 1.02)
    _ax.legend(fontsize=8)

    fig_ss.tight_layout()
    mo.as_html(fig_ss)
    return


@app.cell
def real_world_examples(mo):
    mo.md(r"""
    ## Real-world applications

    The Beta-Binomial A/B test applies anywhere you have **two
    variants and a binary outcome**. Here are concrete scenarios with
    the model you'd fit and what the data looks like.

    ### E-commerce: checkout flow redesign
    - **Arms:** current checkout (A) vs. single-page checkout (B)
    - **Metric:** completed purchase (1) vs. abandoned cart (0)
    - **Data:** `(user_id, variant, purchased)` — aggregate to
      `n_A, conv_A, n_B, conv_B`
    - **Why Bayesian:** you can monitor daily and stop early when
      expected loss is small enough, instead of waiting for a
      predetermined sample size

    ### SaaS: onboarding flow
    - **Arms:** guided tutorial (A) vs. self-serve (B)
    - **Metric:** converted from free trial to paid (1/0)
    - **Data:** `(account_id, variant, converted_to_paid)`
    - **Why Bayesian:** trial conversions take 14 days — small sample
      sizes where frequentist tests have low power, but the Bayesian
      posterior is still valid

    ### Email marketing: subject line testing
    - **Arms:** two subject lines
    - **Metric:** opened (1) vs. ignored (0)
    - **Data:** `(email_id, variant, opened)`
    - **Why Bayesian:** you typically send to a small holdout first,
      then ship the winner to the full list — expected loss tells you
      exactly when the holdout is large enough

    ### Ad creative: landing page variants
    - **Arms:** two landing page designs
    - **Metric:** form submission (1/0)
    - **Data:** `(session_id, variant, submitted_form)`
    - **Model extension:** if conversion rates vary by traffic source,
      add a hierarchical layer — Beta priors per (variant, source) with
      partial pooling across sources

    ### Paywall placement: content monetization
    - **Arms:** paywall after paragraph 3 (A) vs. after paragraph 5 (B)
    - **Metric:** subscribed (1/0)
    - **Data:** `(reader_id, variant, subscribed)`
    - **Nuance:** earlier paywall has higher conversion per-exposed-reader
      but fewer exposed readers — model both the exposure rate and the
      conditional conversion rate as a two-stage funnel

    ### Healthcare: treatment protocol comparison
    - **Arms:** standard care (A) vs. modified protocol (B)
    - **Metric:** 30-day readmission (1/0)
    - **Data:** `(patient_id, arm, readmitted_30d)`
    - **Why Bayesian:** ethical urgency — if B is clearly better after
      200 patients, you don't want to expose 800 more to the inferior
      arm just to hit a power calculation. Expected loss lets you stop
      early with a clear conscience.
    """)
    return


@app.cell
def frequentist_comparison(mo, np, stats, conversions_a, conversions_b, n_a, n_b, prob_b_better):
    """Side-by-side with the frequentist test so the buyer can see the difference."""
    # Two-proportion z-test
    p_hat_a = conversions_a / n_a
    p_hat_b = conversions_b / n_b
    p_pool = (conversions_a + conversions_b) / (n_a + n_b)
    se = float(np.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b)))
    z_stat = (p_hat_b - p_hat_a) / se if se > 0 else 0.0
    p_value = float(2 * (1 - stats.norm.cdf(abs(z_stat))))

    mo.md(
        f"""
    ## Bayesian vs frequentist — side by side

    | | Frequentist (z-test) | Bayesian |
    |---|---|---|
    | **Test statistic** | z = {z_stat:.3f} | (none needed) |
    | **p-value** | {p_value:.4f} | (not a thing) |
    | **"Significant" at 0.05?** | {"Yes" if p_value < 0.05 else "No"} | (wrong question) |
    | **P(B > A)** | (can't answer) | {prob_b_better:.4f} |
    | **Expected loss** | (can't answer) | (see above) |
    | **Can peek at results?** | No (inflates Type I error) | Yes (posterior is always valid) |
    | **Handles unequal n?** | Awkwardly | Naturally |

    The frequentist test answers: "If there's no difference, how
    surprising is this data?" The Bayesian model answers: "Given this
    data, what's the probability B is better, and how much do I lose
    if I'm wrong?" — which is what you actually want to know.
    """
    )
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    The four things you should always do for Bayesian A/B testing:

    1. **Beta priors on conversion rates** — uniform (Beta(1,1)) if you
       have no prior knowledge, informative if you do. The model handles
       unequal sample sizes naturally.
    2. **Posterior of delta = p_B - p_A** — this is the quantity you
       actually care about. Plot it, compute HDI, check if zero is
       inside the interval.
    3. **Expected loss, not p-values** — "how much do I lose by picking
       the wrong arm?" is the question stakeholders actually need
       answered. When expected loss drops below your tolerance, ship it.
    4. **ROPE for practical significance** — a 0.01% lift might be
       "statistically significant" with enough data but operationally
       meaningless. Set a minimum effect size and check if the posterior
       clears it.

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/bayesian-ab-testing/` directory and your AI agent
    will follow the same workflow on your real data.
    """)
    return


if __name__ == "__main__":
    app.run()
