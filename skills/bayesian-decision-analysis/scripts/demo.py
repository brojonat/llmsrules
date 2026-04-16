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
"""Worked example for the bayesian-decision-analysis bundle.

Self-contained: builds posterior models for three business decision
scenarios, then shows how to compute expected loss, optimal actions,
expected value of perfect information (EVPI), and expected value of
sample information (EVSI). The decision layer that sits on top of
every other Bayesian bundle.

    marimo edit --sandbox demo.py

Reference: Bayesian Methods for Hackers, Chapter 5 (Loss Functions);
Raiffa & Schlaifer (1961), Applied Statistical Decision Theory.
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
    # Bayesian Decision Analysis

    Every other Bayesian bundle gives you a **posterior** — a
    probability distribution over unknowns. This bundle shows you
    what to **do** with it.

    Decision analysis is the missing link between "I have a posterior"
    and "I chose the right action." It answers:

    1. **What action minimizes expected loss?** (Bayes-optimal decision)
    2. **How much would perfect information be worth?** (EVPI)
    3. **How much would an additional N samples be worth?** (EVSI)
    4. **How do different loss functions change the optimal action?**

    We work three scenarios end-to-end:

    - **Pricing:** set the price that maximizes expected revenue
    - **Inventory:** order the quantity that minimizes over/under-stock cost
    - **Ship-or-wait:** decide whether to launch now or collect more data
    """)
    return


@app.cell
def prerequisites(mo):
    mo.md(r"""
    ## Prerequisites and expected input

    **This bundle comes AFTER you've fitted a Bayesian model.** It's
    the decision layer on top of `bayesian-ab-testing`,
    `bayesian-regression`, `bayesian-mixture-models`, or any other
    posterior-producing workflow.

    ### What you need

    | Input | Format | Where it comes from |
    |---|---|---|
    | **Posterior samples** | numpy array, shape (n_samples,) | `idata.posterior["param"].to_numpy().flatten()` |
    | **Loss function** | Python function `L(action, theta) -> float` | Business stakeholders + domain knowledge |
    | **Action space** | Array of candidate actions | Your decision context |

    If you have an ArviZ `InferenceData` object from any PyMC model,
    you already have everything you need:

    ```python
    # From bayesian-ab-testing
    delta_samples = idata.posterior["delta"].to_numpy().flatten()

    # From bayesian-regression
    slope_samples = idata.posterior["slope"].to_numpy().flatten()

    # From any model — posterior predictive samples
    y_pred = idata.posterior_predictive["y"].to_numpy().flatten()
    ```

    ### When to use this bundle

    - You have a posterior and need to choose an **action** (not just
      estimate a parameter)
    - The cost of being wrong is **asymmetric** (over vs under)
    - You need to decide whether to **collect more data or act now**
    - Stakeholders ask "what should we **do**?" not "what is the
      number?"

    ### When to use something else

    - You just need parameter estimates → use the inference bundles
    - The decision is binary classification → use threshold tuning
    - You're comparing two variants → `bayesian-ab-testing` already
      includes expected loss
    """)
    return


# ── Scenario 1: Pricing under demand uncertainty ──────────────────


@app.cell
def pricing_section(mo):
    mo.md(r"""
    ## Scenario 1: Optimal pricing under demand uncertainty

    You're launching a product. Demand depends on price, but you
    don't know the demand curve exactly — you have a posterior over
    its parameters from a pilot study. What price maximizes
    **expected revenue**?

    Model: $\text{demand}(p) = \alpha \cdot e^{-\beta \cdot p}$
    where $\alpha$ is the base demand and $\beta$ is price sensitivity.
    Revenue = price * demand(price).
    """)
    return


@app.cell
def pricing_model(mo, np, pm, stats):
    """Simulate a pilot study and fit a demand model."""
    _rng = np.random.default_rng(42)

    # True parameters (unknown to the decision-maker)
    _true_alpha = 1000.0
    _true_beta = 0.08

    # Pilot data: 8 price points, noisy demand observations
    pilot_prices = np.array([10, 15, 20, 25, 30, 35, 40, 50], dtype=float)
    _true_demand = _true_alpha * np.exp(-_true_beta * pilot_prices)
    pilot_demand = np.maximum(
        1, _rng.poisson(_true_demand).astype(float),
    )

    # Fit Bayesian demand model
    with pm.Model() as _demand_model:
        _alpha = pm.LogNormal("alpha", mu=np.log(800), sigma=0.5)
        _beta = pm.LogNormal("beta", mu=np.log(0.05), sigma=0.5)
        _mu = _alpha * pm.math.exp(-_beta * pilot_prices)
        pm.Poisson("obs", mu=_mu, observed=pilot_demand)
        pricing_idata = pm.sample(
            draws=2000, tune=1000, chains=4,
            random_seed=42, progressbar=False,
        )

    pricing_alpha = pricing_idata.posterior["alpha"].to_numpy().flatten()
    pricing_beta = pricing_idata.posterior["beta"].to_numpy().flatten()

    mo.md(
        f"""
    **Pilot data:** {len(pilot_prices)} price points observed.

    | Price | Observed demand |
    |---|---|
    """
        + "\n".join(
            f"    | ${p:.0f} | {int(d)} |"
            for p, d in zip(pilot_prices, pilot_demand)
        )
    )
    return pilot_demand, pilot_prices, pricing_alpha, pricing_beta


@app.cell
def pricing_optimization(mo, np, plt, pricing_alpha, pricing_beta):
    """Sweep prices and compute expected revenue from posterior samples."""
    _price_grid = np.linspace(5, 60, 200)
    _n_samples = len(pricing_alpha)

    # For each posterior sample, compute revenue at each price
    # revenue(p) = p * alpha * exp(-beta * p)
    _revenue_matrix = np.zeros((_n_samples, len(_price_grid)))
    for _i in range(_n_samples):
        _demand = pricing_alpha[_i] * np.exp(-pricing_beta[_i] * _price_grid)
        _revenue_matrix[_i] = _price_grid * _demand

    _expected_revenue = _revenue_matrix.mean(axis=0)
    _rev_lo = np.percentile(_revenue_matrix, 3, axis=0)
    _rev_hi = np.percentile(_revenue_matrix, 97, axis=0)

    _best_idx = int(np.argmax(_expected_revenue))
    optimal_price = float(_price_grid[_best_idx])
    optimal_revenue = float(_expected_revenue[_best_idx])

    fig_pricing, _ax = plt.subplots(figsize=(10, 5))
    _ax.plot(_price_grid, _expected_revenue, lw=2, color="#228833", label="expected revenue")
    _ax.fill_between(
        _price_grid, _rev_lo, _rev_hi,
        alpha=0.2, color="#228833", label="94% CrI",
    )
    _ax.axvline(
        optimal_price, color="red", ls="--", lw=1.5,
        label=f"optimal = ${optimal_price:.0f} (E[rev] = ${optimal_revenue:,.0f})",
    )
    _ax.set_xlabel("price ($)")
    _ax.set_ylabel("revenue ($)")
    _ax.set_title("Expected revenue vs price (posterior-averaged)")
    _ax.legend(fontsize=9)
    fig_pricing.tight_layout()
    mo.as_html(fig_pricing)
    return optimal_price, optimal_revenue


@app.cell
def pricing_evpi(mo, np, optimal_revenue, pricing_alpha, pricing_beta):
    """Expected Value of Perfect Information for pricing."""
    _price_grid = np.linspace(5, 60, 200)

    # With perfect information: for each posterior sample (= each
    # possible true state), pick the optimal price for THAT state
    _perfect_revenues = np.zeros(len(pricing_alpha))
    for _i in range(len(pricing_alpha)):
        _demand = pricing_alpha[_i] * np.exp(-pricing_beta[_i] * _price_grid)
        _rev = _price_grid * _demand
        _perfect_revenues[_i] = float(np.max(_rev))

    expected_perfect_revenue = float(np.mean(_perfect_revenues))
    evpi = expected_perfect_revenue - optimal_revenue

    mo.md(
        f"""
    ### Expected Value of Perfect Information (EVPI)

    | Metric | Value |
    |---|---|
    | **Expected revenue (current best action)** | ${optimal_revenue:,.0f} |
    | **Expected revenue (with perfect info)** | ${expected_perfect_revenue:,.0f} |
    | **EVPI** | **${evpi:,.0f}** |

    EVPI = ${evpi:,.0f} means: if an oracle told you the exact demand
    curve, you'd earn ${evpi:,.0f} more on average. This is the
    **maximum** you should spend on market research. If a consultant
    charges more than this, their information isn't worth it — even if
    it were perfect.
    """
    )
    return evpi


# ── Scenario 2: Inventory (newsvendor) ────────────────────────────


@app.cell
def inventory_section(mo):
    mo.md(r"""
    ## Scenario 2: Inventory — the newsvendor problem

    You must order inventory **before** knowing demand. Over-ordering
    wastes money (unsold stock). Under-ordering loses revenue (missed
    sales). The optimal order quantity depends on the **asymmetry**
    of the costs and your **uncertainty about demand**.

    This is the classic newsvendor problem, solved with the full
    posterior instead of a point estimate.
    """)
    return


@app.cell
def inventory_widgets(mo):
    unit_cost_slider = mo.ui.slider(
        start=1, stop=20, step=1, value=5,
        label="unit cost (cost of ordering one item)",
    )
    unit_revenue_slider = mo.ui.slider(
        start=5, stop=50, step=1, value=20,
        label="unit revenue (revenue per item sold)",
    )
    salvage_slider = mo.ui.slider(
        start=0, stop=10, step=1, value=2,
        label="salvage value (recovery per unsold item)",
    )
    mo.vstack([unit_cost_slider, unit_revenue_slider, salvage_slider])
    return salvage_slider, unit_cost_slider, unit_revenue_slider


@app.cell
def inventory_model(mo, np, pm):
    """Posterior over demand from historical data."""
    _rng = np.random.default_rng(55)
    # Historical daily demand: Poisson-ish, 30 days
    _true_rate = 45.0
    historical_demand = _rng.poisson(_true_rate, size=30)

    with pm.Model():
        _lam = pm.Gamma("demand_rate", alpha=2, beta=0.02)
        pm.Poisson("obs", mu=_lam, observed=historical_demand)
        inv_idata = pm.sample(
            draws=2000, tune=1000, chains=4,
            random_seed=55, progressbar=False,
        )

    demand_rate_samples = inv_idata.posterior["demand_rate"].to_numpy().flatten()

    _mean_hist = float(np.mean(historical_demand))
    mo.md(
        f"""
    **Historical data:** 30 days, mean demand = {_mean_hist:.1f} units/day.
    Posterior mean demand rate = {float(np.mean(demand_rate_samples)):.1f}
    (94% CrI: [{np.percentile(demand_rate_samples, 3):.1f}, {np.percentile(demand_rate_samples, 97):.1f}])
    """
    )
    return demand_rate_samples, historical_demand


@app.cell
def inventory_optimization(
    demand_rate_samples,
    mo,
    np,
    plt,
    salvage_slider,
    unit_cost_slider,
    unit_revenue_slider,
):
    """Compute expected profit for each order quantity."""
    _cost = float(unit_cost_slider.value)
    _revenue = float(unit_revenue_slider.value)
    _salvage = float(salvage_slider.value)
    _overage_cost = _cost - _salvage  # cost per unsold unit
    _underage_cost = _revenue - _cost  # opportunity cost per missed sale

    _rng = np.random.default_rng(77)
    # Simulate actual demand from posterior predictive
    _demand_draws = _rng.poisson(demand_rate_samples)

    _order_grid = np.arange(20, 80)
    _expected_profits = np.zeros(len(_order_grid))
    _profit_lo = np.zeros(len(_order_grid))
    _profit_hi = np.zeros(len(_order_grid))

    for _i, _q in enumerate(_order_grid):
        _sold = np.minimum(_demand_draws, _q)
        _unsold = np.maximum(_q - _demand_draws, 0)
        _profits = _sold * _revenue - _q * _cost + _unsold * _salvage
        _expected_profits[_i] = float(np.mean(_profits))
        _profit_lo[_i] = float(np.percentile(_profits, 3))
        _profit_hi[_i] = float(np.percentile(_profits, 97))

    _best_idx = int(np.argmax(_expected_profits))
    optimal_order = int(_order_grid[_best_idx])
    optimal_profit = float(_expected_profits[_best_idx])

    # Critical ratio (newsvendor closed form for comparison)
    _cr = _underage_cost / (_underage_cost + _overage_cost)

    fig_inv, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(13, 5))

    _ax1.plot(
        _order_grid, _expected_profits,
        lw=2, color="#228833", label="expected profit",
    )
    _ax1.fill_between(
        _order_grid, _profit_lo, _profit_hi,
        alpha=0.2, color="#228833", label="94% CrI",
    )
    _ax1.axvline(
        optimal_order, color="red", ls="--", lw=1.5,
        label=f"optimal Q = {optimal_order} (E[profit] = ${optimal_profit:,.0f})",
    )
    _ax1.set_xlabel("order quantity")
    _ax1.set_ylabel("profit ($)")
    _ax1.set_title("Expected profit vs order quantity")
    _ax1.legend(fontsize=8)

    # Loss decomposition
    _over_losses = np.zeros(len(_order_grid))
    _under_losses = np.zeros(len(_order_grid))
    for _i, _q in enumerate(_order_grid):
        _over = np.maximum(_q - _demand_draws, 0)
        _under = np.maximum(_demand_draws - _q, 0)
        _over_losses[_i] = float(np.mean(_over * _overage_cost))
        _under_losses[_i] = float(np.mean(_under * _underage_cost))

    _ax2.plot(
        _order_grid, _over_losses, lw=2, color="#cc3311",
        label="overage loss (unsold)",
    )
    _ax2.plot(
        _order_grid, _under_losses, lw=2, color="#4477aa",
        label="underage loss (missed sales)",
    )
    _ax2.plot(
        _order_grid, _over_losses + _under_losses, lw=2,
        color="black", ls="--", label="total expected loss",
    )
    _ax2.axvline(optimal_order, color="red", ls="--", lw=1, alpha=0.5)
    _ax2.set_xlabel("order quantity")
    _ax2.set_ylabel("expected loss ($)")
    _ax2.set_title(f"Loss decomposition (critical ratio = {_cr:.2f})")
    _ax2.legend(fontsize=8)

    fig_inv.tight_layout()
    mo.as_html(fig_inv)
    return optimal_order, optimal_profit


@app.cell
def inventory_evpi(
    demand_rate_samples,
    mo,
    np,
    optimal_profit,
    salvage_slider,
    unit_cost_slider,
    unit_revenue_slider,
):
    """EVPI for inventory: if you knew tomorrow's demand exactly."""
    _cost = float(unit_cost_slider.value)
    _revenue = float(unit_revenue_slider.value)
    _salvage = float(salvage_slider.value)
    _rng = np.random.default_rng(77)
    _demand_draws = _rng.poisson(demand_rate_samples)

    # With perfect info: order exactly what demand will be
    _perfect_profits = _demand_draws * (_revenue - _cost)
    _ev_perfect = float(np.mean(_perfect_profits))
    _evpi = _ev_perfect - optimal_profit

    mo.md(
        f"""
    ### EVPI for inventory

    | Metric | Value |
    |---|---|
    | **Expected profit (optimal order)** | ${optimal_profit:,.0f} |
    | **Expected profit (perfect info)** | ${_ev_perfect:,.0f} |
    | **EVPI** | **${_evpi:,.0f}** |

    EVPI = ${_evpi:,.0f}/day. This is the maximum you'd pay for a
    perfect demand forecast. If your forecasting system costs more
    than this, it's not worth it.
    """
    )
    return


# ── Scenario 3: Ship-or-wait ──────────────────────────────────────


@app.cell
def ship_section(mo):
    mo.md(r"""
    ## Scenario 3: Ship now or collect more data?

    You ran an A/B test. B looks better, but you're not sure. You
    can **ship B now** (risk it being worse) or **run the test longer**
    (delay + cost of experimentation). This is the Expected Value of
    Sample Information (EVSI) problem.

    EVSI tells you how much additional data is worth — if it's less
    than the cost of collecting it, stop the experiment and decide now.
    """)
    return


@app.cell
def ship_model(mo, np, stats):
    """A/B test scenario: current posterior from initial data."""
    # Current state: 2000 visitors per arm, observed conversions
    n_a_current = 2000
    conv_a_current = 96   # 4.8%
    n_b_current = 2000
    conv_b_current = 118  # 5.9%

    # Conjugate posteriors (no MCMC needed for this)
    post_a = stats.beta(1 + conv_a_current, 1 + n_a_current - conv_a_current)
    post_b = stats.beta(1 + conv_b_current, 1 + n_b_current - conv_b_current)

    _p_a_mean = float(post_a.mean())
    _p_b_mean = float(post_b.mean())

    mo.md(
        f"""
    **Current state:**

    | | Control (A) | Treatment (B) |
    |---|---|---|
    | Visitors | {n_a_current:,} | {n_b_current:,} |
    | Conversions | {conv_a_current} | {conv_b_current} |
    | Posterior mean | {_p_a_mean:.4f} | {_p_b_mean:.4f} |
    """
    )
    return conv_a_current, conv_b_current, n_a_current, n_b_current, post_a, post_b


@app.cell
def evsi_computation(
    conv_a_current,
    conv_b_current,
    mo,
    n_a_current,
    n_b_current,
    np,
    plt,
    stats,
):
    """Compute EVSI: how much is running the test for N more visitors worth?"""
    _rng = np.random.default_rng(88)
    _n_mc = 3000
    _additional_sizes = np.array([0, 200, 500, 1000, 2000, 5000, 10000])

    # Current expected loss (no more data)
    _p_a_draws = _rng.beta(
        1 + conv_a_current, 1 + n_a_current - conv_a_current, size=_n_mc,
    )
    _p_b_draws = _rng.beta(
        1 + conv_b_current, 1 + n_b_current - conv_b_current, size=_n_mc,
    )
    _loss_ship_b_now = float(np.mean(np.maximum(_p_a_draws - _p_b_draws, 0)))
    _loss_keep_a_now = float(np.mean(np.maximum(_p_b_draws - _p_a_draws, 0)))
    _current_min_loss = min(_loss_ship_b_now, _loss_keep_a_now)
    _current_action = "ship B" if _loss_ship_b_now < _loss_keep_a_now else "keep A"

    # EVSI for each additional sample size
    _evsi_values = np.zeros(len(_additional_sizes))
    _min_losses_after = np.zeros(len(_additional_sizes))

    for _idx, _n_extra in enumerate(_additional_sizes):
        if _n_extra == 0:
            _min_losses_after[_idx] = _current_min_loss
            _evsi_values[_idx] = 0.0
            continue

        # Simulate: draw true p_A, p_B from current posterior,
        # then simulate n_extra observations, update posterior,
        # and compute the new optimal expected loss
        _future_min_losses = np.zeros(_n_mc)
        for _s in range(_n_mc):
            # "True" state drawn from current posterior
            _pa_true = _p_a_draws[_s]
            _pb_true = _p_b_draws[_s]

            # Simulate future data
            _new_conv_a = _rng.binomial(int(_n_extra), _pa_true)
            _new_conv_b = _rng.binomial(int(_n_extra), _pb_true)

            # Updated posterior parameters
            _alpha_a = 1 + conv_a_current + _new_conv_a
            _beta_a = 1 + (n_a_current + _n_extra) - (conv_a_current + _new_conv_a)
            _alpha_b = 1 + conv_b_current + _new_conv_b
            _beta_b = 1 + (n_b_current + _n_extra) - (conv_b_current + _new_conv_b)

            # Expected loss with updated posterior (closed-form via MC)
            _pa_post = _rng.beta(_alpha_a, _beta_a, size=200)
            _pb_post = _rng.beta(_alpha_b, _beta_b, size=200)
            _loss_b = float(np.mean(np.maximum(_pa_post - _pb_post, 0)))
            _loss_a = float(np.mean(np.maximum(_pb_post - _pa_post, 0)))
            _future_min_losses[_s] = min(_loss_b, _loss_a)

        _min_losses_after[_idx] = float(np.mean(_future_min_losses))
        _evsi_values[_idx] = _current_min_loss - _min_losses_after[_idx]

    fig_evsi, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(13, 5))

    _ax1.plot(
        _additional_sizes, _evsi_values * 100,
        lw=2, color="#228833", marker="o",
    )
    _ax1.set_xlabel("additional visitors per arm")
    _ax1.set_ylabel("EVSI (conversion-rate points, x100)")
    _ax1.set_title("Expected Value of Sample Information")
    _ax1.axhline(0, color="grey", ls=":", lw=1)

    _ax2.plot(
        _additional_sizes, _min_losses_after * 100,
        lw=2, color="#cc3311", marker="o",
    )
    _ax2.set_xlabel("additional visitors per arm")
    _ax2.set_ylabel("expected loss after decision (x100)")
    _ax2.set_title("Expected loss shrinks with more data")
    _ax2.axhline(0, color="grey", ls=":", lw=1)

    fig_evsi.tight_layout()
    mo.as_html(fig_evsi)
    return _current_action, _current_min_loss, _evsi_values, _additional_sizes


@app.cell
def evsi_table(
    _additional_sizes,
    _current_action,
    _current_min_loss,
    _evsi_values,
    mo,
):
    _rows = "\n".join(
        f"    | {int(_n):,} | {_evsi * 100:.4f} |"
        for _n, _evsi in zip(_additional_sizes, _evsi_values)
    )
    mo.md(
        f"""
    ### EVSI summary

    **Current optimal action:** {_current_action}
    (expected loss = {_current_min_loss * 100:.4f} conversion-rate points x100)

    | Additional visitors/arm | EVSI (x100 conv-rate pts) |
    |---|---|
    {_rows}

    **How to use:** multiply EVSI by your traffic volume to get the
    dollar value. If you serve 1M users/month and EVSI at n=2000 is
    0.005 conversion-rate points, that's 0.005% * 1M = 50 additional
    conversions. If each conversion is worth $10, the additional data
    is worth $500. If running the test for 2000 more visitors costs
    less than $500, keep running.
    """
    )
    return


# ── Loss functions ────────────────────────────────────────────────


@app.cell
def loss_section(mo):
    mo.md(r"""
    ## Loss functions — how the cost shape changes the optimal action

    The Bayes-optimal action depends on the **loss function**. Different
    losses lead to different optimal summaries of the posterior:

    | Loss function | Optimal action | Use when |
    |---|---|---|
    | Squared error $(a - \theta)^2$ | Posterior **mean** | Symmetric cost, no outliers |
    | Absolute error $|a - \theta|$ | Posterior **median** | Robust to outliers |
    | 0-1 loss | Posterior **mode** (MAP) | Classification / discrete choice |
    | Asymmetric linear | Posterior **quantile** | Over/under-prediction have different costs |
    | Custom business loss | Compute numerically | Always the right move for real problems |

    Below: a parameter $\theta$ with a skewed posterior, and how the
    optimal point estimate changes with the loss function.
    """)
    return


@app.cell
def loss_demo(mo, np, plt, stats):
    """Demonstrate how loss function changes the optimal action."""
    # Skewed posterior (Gamma)
    _dist = stats.gamma(a=3, scale=2)
    _theta_grid = np.linspace(0, 20, 500)
    _pdf = _dist.pdf(_theta_grid)
    _samples = _dist.rvs(10000, random_state=42)

    _mean = float(np.mean(_samples))
    _median = float(np.median(_samples))
    _mode = float(_theta_grid[np.argmax(_pdf)])

    # Asymmetric loss: underprediction costs 3x overprediction
    _asym_ratio = 3.0
    _quantile = float(np.percentile(_samples, 100 * _asym_ratio / (1 + _asym_ratio)))

    fig_loss, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Left: posterior with optimal actions marked
    _ax1.fill_between(_theta_grid, _pdf, alpha=0.3, color="#4477aa")
    _ax1.plot(_theta_grid, _pdf, lw=2, color="#4477aa")
    _markers = [
        (_mean, "mean (squared loss)", "red", "-"),
        (_median, "median (absolute loss)", "#228833", "--"),
        (_mode, "mode (0-1 loss)", "#cc3311", ":"),
        (_quantile, f"q={_asym_ratio / (1 + _asym_ratio):.0%} (asymmetric)", "purple", "-."),
    ]
    for _val, _label, _color, _ls in _markers:
        _ax1.axvline(_val, color=_color, ls=_ls, lw=2, label=f"{_label} = {_val:.2f}")
    _ax1.set_xlabel("theta")
    _ax1.set_ylabel("density")
    _ax1.set_title("Skewed posterior — different losses, different actions")
    _ax1.legend(fontsize=7, loc="upper right")

    # Right: expected loss curves
    _actions = np.linspace(0, 20, 300)
    _sq_loss = np.array([float(np.mean((_samples - _a) ** 2)) for _a in _actions])
    _abs_loss = np.array([float(np.mean(np.abs(_samples - _a))) for _a in _actions])
    _asym_loss = np.array([
        float(np.mean(np.where(
            _samples > _a,
            _asym_ratio * (_samples - _a),
            (_a - _samples),
        )))
        for _a in _actions
    ])

    _ax2.plot(_actions, _sq_loss / _sq_loss.max(), lw=2, color="red", label="squared")
    _ax2.plot(_actions, _abs_loss / _abs_loss.max(), lw=2, color="#228833", label="absolute")
    _ax2.plot(_actions, _asym_loss / _asym_loss.max(), lw=2, color="purple", label="asymmetric (3:1)")
    _ax2.set_xlabel("action (point estimate)")
    _ax2.set_ylabel("normalized expected loss")
    _ax2.set_title("Expected loss curves (minima = optimal actions)")
    _ax2.legend(fontsize=9)

    fig_loss.tight_layout()
    mo.as_html(fig_loss)
    return


# ── Framework summary ─────────────────────────────────────────────


@app.cell
def framework_section(mo):
    mo.md(r"""
    ## The decision analysis framework

    Every Bayesian decision problem follows the same three steps:

    ### Step 1: Posterior
    Fit a model to get $P(\theta \mid \text{data})$. This is what the
    other bundles give you — A/B testing, regression, mixture models,
    etc.

    ### Step 2: Loss function
    Define $L(a, \theta)$ — the cost of taking action $a$ when the
    true state is $\theta$. This is the **business input** — it comes
    from stakeholders, not from the data.

    ### Step 3: Minimize expected loss
    The Bayes-optimal action is:

    $$a^* = \arg\min_a \; \mathbb{E}_{\theta \sim \text{posterior}}[L(a, \theta)]$$

    With posterior samples, this is just:

    ```python
    actions = np.linspace(low, high, 1000)
    expected_losses = [
        np.mean(loss_fn(a, theta_samples))
        for a in actions
    ]
    optimal_action = actions[np.argmin(expected_losses)]
    ```

    ### EVPI and EVSI
    - **EVPI** = E[loss with current best action] - E[loss with
      perfect information]. The maximum value of any information.
    - **EVSI(n)** = E[loss now] - E[loss after n more observations].
      The value of running the experiment longer.

    Both are computed by Monte Carlo: simulate future states and/or
    future data, compute the optimal action in each simulation, and
    average.
    """)
    return


@app.cell
def optimization_section(mo):
    mo.md(r"""
    ## PyMC as an optimization engine

    People don't usually think of PyMC as an optimization tool, but
    that's exactly what Bayesian decision analysis is: **build a
    generative model of the system, get a posterior over unknowns,
    then optimize your action over that posterior.**

    The workflow is:

    ```
    Real system → PyMC generative model → Posterior samples
         → Sweep action space → Expected loss per action
         → Pick the action that minimizes expected loss
    ```

    This is more powerful than classical optimization because:

    1. **Your objective function has uncertainty** — you're not
       optimizing a known function, you're optimizing the *expected
       value* of an uncertain function
    2. **You get risk-adjusted decisions** — the optimal action under
       uncertainty is different from the optimal action if you knew
       the parameters exactly
    3. **You can quantify the value of reducing uncertainty** — EVPI
       and EVSI tell you whether it's worth investing in better data
       before optimizing

    The hard part is always **building the right generative model**.
    Below are realistic examples with model sketches.
    """)
    return


@app.cell
def real_world_examples(mo):
    mo.md(r"""
    ## Real-world optimization problems

    Each of these follows the same pattern: build a PyMC model of
    the system, get a posterior, optimize the action.

    ### Marketing budget allocation
    - **Decision:** how to split $100K across 4 channels (search, social,
      email, display)
    - **Model:** revenue per channel follows a saturating curve
      (diminishing returns):
      `revenue_k = alpha_k * (1 - exp(-beta_k * spend_k))`
    - **Priors:** LogNormal on alpha (ceiling) and beta (saturation rate),
      informed by last quarter's data
    - **Loss:** negative total revenue
    - **Action space:** all allocations that sum to $100K
    - **What you get:** the budget split that maximizes expected
      revenue, plus a credible interval on total revenue — and EVPI
      tells you how much a marketing attribution study is worth

    ### Clinical trial stopping rules
    - **Decision:** stop the trial and declare the drug effective,
      stop and declare it ineffective, or enroll more patients
    - **Model:** Beta-Binomial on response rate in treatment vs.
      control (same as A/B testing)
    - **Loss:** asymmetric — approving an ineffective drug is much
      worse than delaying an effective one. Define costs for each
      error type: `L(approve | ineffective) = $500M`,
      `L(delay | effective) = $50M/month`
    - **EVSI:** how many more patients do we need to enroll before
      the expected loss of deciding drops below the cost of continued
      enrollment?

    ### Insurance pricing (pure premium)
    - **Decision:** what premium to charge for a policy class
    - **Model:** hierarchical — claim frequency ~ Poisson(lambda),
      claim severity ~ LogNormal(mu, sigma), both varying by risk
      class with partial pooling
    - **Loss:** asymmetric — underpricing loses money, overpricing
      loses customers. Define as:
      `L(premium, true_cost) = max(true_cost - premium, 0) * 2 + max(premium - true_cost, 0) * 0.3`
    - **What you get:** the premium that balances loss ratio against
      competitive pricing, with uncertainty

    ### Workforce scheduling
    - **Decision:** how many staff to schedule for each shift
    - **Model:** demand ~ Poisson(rate), where rate varies by day of
      week, time of day, and season. Fit with PyMC on 6 months of
      historical demand.
    - **Loss:** understaffing costs $50/hour/person (overtime, poor
      service), overstaffing costs $15/hour/person (idle labor)
    - **Optimal:** order at the 77th percentile of the posterior
      predictive demand (= 50 / (50+15) quantile — the newsvendor
      solution)
    - **Extension:** EVSI — is it worth instrumenting a demand sensor,
      or is the current forecast good enough?

    ### Supply chain: safety stock optimization
    - **Decision:** how much safety stock to hold for each SKU
    - **Model:** lead_time ~ LogNormal, demand_during_lead_time ~
      Poisson(rate * lead_time). Both with posterior uncertainty from
      historical shipment data.
    - **Loss:** stockout cost (lost revenue + expediting) vs. holding
      cost (warehousing + capital)
    - **What you get:** the safety stock level per SKU that minimizes
      total expected cost — and EVPI tells you how much better
      forecasting would save vs. better inventory policy

    ### Dynamic auction bidding
    - **Decision:** how much to bid on each ad impression
    - **Model:** P(conversion | impression) ~ Beta, informed by
      historical bid-win-conversion data. Value per conversion is
      known.
    - **Loss:** bid too low = miss the impression, bid too high =
      win but overpay
    - **Optimal:** bid = expected_value_per_impression = P(conversion)
      * value_per_conversion, computed from posterior samples
    - **Contextual:** condition on user features for personalized
      bid prices

    ### Experiment design: optimal sample allocation
    - **Decision:** given a fixed total sample budget of N, how many
      to allocate to treatment vs. control?
    - **Model:** posterior from a pilot study (Beta-Binomial on each arm)
    - **Loss:** expected posterior variance of the treatment effect
      (you want the most informative allocation)
    - **What you get:** the allocation ratio that minimizes expected
      posterior uncertainty — not always 50/50 (if one arm has higher
      variance, give it more samples)
    """)
    return


@app.cell
def custom_loss_section(mo):
    mo.md(r"""
    ## Defining your own loss function

    The three scenarios above use built-in loss functions. For your
    real problem, you'll need to define your own. Here's the recipe:

    ### Step 1: Ask stakeholders three questions

    1. **What actions can you take?** (set price, order quantity, ship
       or wait, allocate budget across channels)
    2. **What does it cost when you're wrong?** Get specific: "if we
       set the price $5 too high, we lose X; if $5 too low, we lose Y"
    3. **Is the cost symmetric?** (Over-ordering vs under-ordering
       almost never cost the same)

    ### Step 2: Write it as a Python function

    ```python
    def my_loss(action, theta_samples):
        \"\"\"
        action: the candidate decision (scalar)
        theta_samples: posterior samples of the unknown (array)
        Returns: array of losses, one per sample
        \"\"\"
        # Example: staffing problem
        # Understaffing costs $50/hour/person (overtime + lost service)
        # Overstaffing costs $15/hour/person (idle labor)
        understaffed = np.maximum(theta_samples - action, 0)
        overstaffed = np.maximum(action - theta_samples, 0)
        return 50 * understaffed + 15 * overstaffed
    ```

    ### Step 3: Sweep actions and minimize

    ```python
    actions = np.arange(10, 100)
    expected_losses = [np.mean(my_loss(a, samples)) for a in actions]
    optimal = actions[np.argmin(expected_losses)]
    ```

    That's it. The pattern is always the same — only the loss function
    changes. **The loss function is the entire business input** to
    Bayesian decision analysis. Everything else is mechanical.
    """)
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    1. **A posterior without a decision is just a picture.** Decision
       analysis is how you turn uncertainty into action.
    2. **The loss function is the business input.** Getting it right
       matters more than getting the model right. An OK model with the
       right loss function beats a perfect model with squared error.
    3. **EVPI tells you the ceiling.** If the maximum value of perfect
       information is $500, don't spend $5000 on a better forecast.
    4. **EVSI tells you when to stop.** If additional data is worth
       less than the cost of collecting it, decide now.
    5. **Different losses, different actions.** The posterior mean is
       optimal for squared loss. The median for absolute loss. A
       quantile for asymmetric costs. For real problems, always define
       a custom loss and compute the optimum numerically.

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/bayesian-decision-analysis/` directory and your
    AI agent will follow the same framework on your real problems.
    """)
    return


if __name__ == "__main__":
    app.run()
