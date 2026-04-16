# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo",
#     "numpy>=1.26",
#     "pandas>=2.2",
#     "matplotlib>=3.9",
#     "scipy>=1.13",
# ]
# ///
"""Worked example for the bayesian-bandits bundle.

Self-contained: simulates multi-armed bandit environments and runs
Thompson sampling, epsilon-greedy, and UCB1 head-to-head. Interactive
widgets let you configure arms, horizon, and exploration parameters.
No external data files. No PyMC (Thompson sampling on Bernoulli arms
only needs scipy.stats.beta — no MCMC required).

    marimo edit --sandbox demo.py
"""

import marimo

__generated_with = "0.23.0"
app = marimo.App(width="medium")


@app.cell
def imports():
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from scipy import stats

    return mo, np, pd, plt, stats


@app.cell
def title(mo):
    mo.md(r"""
    # Bayesian Bandits — Thompson Sampling

    Multi-armed bandits are the "explore vs exploit" problem: you have
    K slot machines (arms) with unknown reward probabilities, and you
    want to maximize total reward over T rounds. Every pull teaches you
    something, but pulling a suboptimal arm costs you.

    This notebook covers:

    1. **Thompson sampling** — the Bayesian solution: maintain a Beta
       posterior per arm, sample from each, pull the highest
    2. **Regret analysis** — how much worse are you doing vs. always
       pulling the best arm?
    3. **Head-to-head** — Thompson vs epsilon-greedy vs UCB1
    4. **Contextual bandits** — when the best arm depends on features
    """)
    return


@app.cell
def config_section(mo):
    mo.md(r"""
    ## Experiment configuration
    """)
    return


@app.cell
def config_widgets(mo):
    n_arms_slider = mo.ui.slider(
        start=2, stop=10, step=1, value=5,
        label="number of arms",
    )
    horizon_slider = mo.ui.slider(
        start=100, stop=5000, step=100, value=2000,
        label="horizon (total rounds)",
    )
    n_sims_slider = mo.ui.slider(
        start=10, stop=200, step=10, value=50,
        label="simulations (for averaged regret curves)",
    )
    epsilon_slider = mo.ui.slider(
        start=0.01, stop=0.30, step=0.01, value=0.10,
        label="epsilon (for epsilon-greedy)",
    )
    mo.vstack([n_arms_slider, horizon_slider, n_sims_slider, epsilon_slider])
    return epsilon_slider, horizon_slider, n_arms_slider, n_sims_slider


@app.cell
def setup_arms(mo, n_arms_slider, np):
    """Generate true arm probabilities — one clearly best, rest spread out."""
    _rng = np.random.default_rng(42)
    n_arms = int(n_arms_slider.value)
    true_probs = np.sort(_rng.uniform(0.1, 0.7, size=n_arms))[::-1]
    # Ensure a clear winner
    true_probs[0] = min(true_probs[0] + 0.1, 0.85)
    best_arm = 0
    best_prob = float(true_probs[0])

    _arm_table = " | ".join(
        [f"Arm {i}: **{p:.3f}**" for i, p in enumerate(true_probs)]
    )
    mo.md(
        f"""
    ## True arm probabilities (hidden from the algorithms)

    {_arm_table}

    **Best arm:** {best_arm} (p = {best_prob:.3f}).
    The gap between best and second-best is
    {true_probs[0] - true_probs[1]:.3f} — this controls how hard the
    problem is (smaller gap = harder to distinguish).
    """
    )
    return best_arm, best_prob, n_arms, true_probs


@app.cell
def algorithms_section(mo):
    mo.md(r"""
    ## The three algorithms

    **Thompson sampling (Bayesian):** Maintain a Beta(alpha, beta)
    posterior for each arm. Each round, draw a sample from every arm's
    posterior and pull the arm with the highest sample. Update the
    posterior with the result. That's it.

    **Epsilon-greedy:** With probability epsilon, pull a random arm
    (explore). Otherwise, pull the arm with the highest observed mean
    (exploit). Simple but wastes exploration budget on clearly bad arms.

    **UCB1 (Upper Confidence Bound):** Pull the arm with the highest
    $\bar{x}_i + \sqrt{\frac{2 \ln t}{n_i}}$. Optimistic in the face
    of uncertainty — always explores the arm you're least sure about.
    """)
    return


@app.cell
def run_simulations(
    epsilon_slider,
    horizon_slider,
    n_arms,
    n_sims_slider,
    np,
    true_probs,
):
    """Run all three algorithms across multiple simulations."""
    horizon = int(horizon_slider.value)
    n_sims = int(n_sims_slider.value)
    epsilon = float(epsilon_slider.value)

    # Storage: (n_sims, horizon) arrays of cumulative regret
    thompson_regret = np.zeros((n_sims, horizon))
    egreedy_regret = np.zeros((n_sims, horizon))
    ucb_regret = np.zeros((n_sims, horizon))

    # Also track arm selection counts for the last simulation
    thompson_counts = np.zeros(n_arms, dtype=int)
    thompson_alphas = np.ones(n_arms)
    thompson_betas = np.ones(n_arms)

    for sim in range(n_sims):
        _rng = np.random.default_rng(sim)

        # --- Thompson Sampling ---
        _ts_alpha = np.ones(n_arms)
        _ts_beta = np.ones(n_arms)
        _ts_cum_regret = 0.0

        for t in range(horizon):
            # Sample from each arm's posterior
            _samples = _rng.beta(_ts_alpha, _ts_beta)
            _arm = int(np.argmax(_samples))
            _reward = int(_rng.random() < true_probs[_arm])
            _ts_alpha[_arm] += _reward
            _ts_beta[_arm] += 1 - _reward
            _ts_cum_regret += true_probs[0] - true_probs[_arm]
            thompson_regret[sim, t] = _ts_cum_regret

        if sim == n_sims - 1:
            thompson_alphas = _ts_alpha.copy()
            thompson_betas = _ts_beta.copy()

        # --- Epsilon-Greedy ---
        _eg_successes = np.zeros(n_arms)
        _eg_pulls = np.zeros(n_arms)
        _eg_cum_regret = 0.0

        for t in range(horizon):
            if t < n_arms:
                _arm = t  # pull each arm once first
            elif _rng.random() < epsilon:
                _arm = int(_rng.integers(0, n_arms))
            else:
                _means = np.where(
                    _eg_pulls > 0, _eg_successes / _eg_pulls, 0.0
                )
                _arm = int(np.argmax(_means))
            _reward = int(_rng.random() < true_probs[_arm])
            _eg_successes[_arm] += _reward
            _eg_pulls[_arm] += 1
            _eg_cum_regret += true_probs[0] - true_probs[_arm]
            egreedy_regret[sim, t] = _eg_cum_regret

        # --- UCB1 ---
        _ucb_successes = np.zeros(n_arms)
        _ucb_pulls = np.zeros(n_arms)
        _ucb_cum_regret = 0.0

        for t in range(horizon):
            if t < n_arms:
                _arm = t
            else:
                _means = _ucb_successes / np.maximum(_ucb_pulls, 1)
                _bonus = np.sqrt(2 * np.log(t + 1) / np.maximum(_ucb_pulls, 1))
                _arm = int(np.argmax(_means + _bonus))
            _reward = int(_rng.random() < true_probs[_arm])
            _ucb_successes[_arm] += _reward
            _ucb_pulls[_arm] += 1
            _ucb_cum_regret += true_probs[0] - true_probs[_arm]
            ucb_regret[sim, t] = _ucb_cum_regret

    # Compute arm selection counts from the last Thompson sim
    thompson_counts = (thompson_alphas - 1 + thompson_betas - 1).astype(int)

    return (
        egreedy_regret,
        horizon,
        n_sims,
        thompson_alphas,
        thompson_betas,
        thompson_counts,
        thompson_regret,
        ucb_regret,
    )


@app.cell
def regret_plot(
    egreedy_regret,
    horizon,
    mo,
    np,
    plt,
    thompson_regret,
    ucb_regret,
):
    """Cumulative regret curves averaged over simulations."""
    _t = np.arange(horizon)
    fig_regret, _ax = plt.subplots(figsize=(12, 5))

    for _data, _label, _color in [
        (thompson_regret, "Thompson sampling", "#228833"),
        (egreedy_regret, "Epsilon-greedy", "#cc3311"),
        (ucb_regret, "UCB1", "#4477aa"),
    ]:
        _mean = _data.mean(axis=0)
        _std = _data.std(axis=0)
        _ax.plot(_t, _mean, lw=2, label=_label, color=_color)
        _ax.fill_between(
            _t, _mean - _std, _mean + _std, alpha=0.15, color=_color,
        )

    _ax.set_xlabel("round")
    _ax.set_ylabel("cumulative regret")
    _ax.set_title(
        "Cumulative regret (mean +/- 1 std over simulations)"
    )
    _ax.legend(fontsize=10)
    fig_regret.tight_layout()
    mo.as_html(fig_regret)
    return


@app.cell
def final_regret_table(
    egreedy_regret,
    mo,
    n_sims,
    np,
    thompson_regret,
    ucb_regret,
):
    _ts_final = thompson_regret[:, -1]
    _eg_final = egreedy_regret[:, -1]
    _ucb_final = ucb_regret[:, -1]

    mo.md(
        f"""
    ## Final cumulative regret (over {n_sims} simulations)

    | Algorithm | Mean | Std | Median | 95th pct |
    |---|---|---|---|---|
    | **Thompson** | {np.mean(_ts_final):.1f} | {np.std(_ts_final):.1f} | {np.median(_ts_final):.1f} | {np.percentile(_ts_final, 95):.1f} |
    | **Epsilon-greedy** | {np.mean(_eg_final):.1f} | {np.std(_eg_final):.1f} | {np.median(_eg_final):.1f} | {np.percentile(_eg_final, 95):.1f} |
    | **UCB1** | {np.mean(_ucb_final):.1f} | {np.std(_ucb_final):.1f} | {np.median(_ucb_final):.1f} | {np.percentile(_ucb_final, 95):.1f} |

    Thompson sampling typically has the lowest regret because it
    **concentrates exploration on arms that might be best**, while
    epsilon-greedy wastes exploration on arms it already knows are bad.
    """
    )
    return


@app.cell
def posterior_section(mo):
    mo.md(r"""
    ## Thompson sampling posteriors (final state)

    After the experiment, each arm's Beta posterior reflects how much
    the algorithm has learned. Arms that were pulled more have tighter
    posteriors. The best arm should have the tightest posterior centered
    on its true value.
    """)
    return


@app.cell
def posterior_plot(
    mo,
    n_arms,
    np,
    plt,
    stats,
    thompson_alphas,
    thompson_betas,
    true_probs,
):
    _colors = plt.cm.tab10(np.linspace(0, 1, n_arms))
    _n_cols = min(n_arms, 3)
    _n_rows = (n_arms + _n_cols - 1) // _n_cols
    fig_post, _axes = plt.subplots(
        _n_rows, _n_cols, figsize=(4.5 * _n_cols, 3.5 * _n_rows),
    )
    if n_arms == 1:
        _axes = np.array([_axes])
    _axes = np.atleast_2d(_axes)

    for _i in range(n_arms):
        _r, _c = divmod(_i, _n_cols)
        _ax = _axes[_r, _c]
        _dist = stats.beta(thompson_alphas[_i], thompson_betas[_i])
        _x = np.linspace(
            max(0, float(_dist.ppf(0.001))),
            min(1, float(_dist.ppf(0.999))),
            300,
        )
        _ax.fill_between(_x, _dist.pdf(_x), alpha=0.4, color=_colors[_i])
        _ax.plot(_x, _dist.pdf(_x), lw=2, color=_colors[_i])
        _ax.axvline(
            true_probs[_i], color="red", ls="--", lw=1.5,
            label=f"true = {true_probs[_i]:.3f}",
        )
        _n_pulls = int(thompson_alphas[_i] + thompson_betas[_i] - 2)
        _ax.set_title(
            f"Arm {_i}: Beta({thompson_alphas[_i]:.0f}, "
            f"{thompson_betas[_i]:.0f}) — {_n_pulls} pulls",
            fontsize=9,
        )
        _ax.legend(fontsize=7)
        _ax.set_xlabel("reward probability")

    # Blank unused axes
    for _j in range(n_arms, _n_rows * _n_cols):
        _r, _c = divmod(_j, _n_cols)
        _axes[_r, _c].axis("off")

    fig_post.suptitle(
        "Final posteriors — best arm gets pulled most, tightest posterior",
        fontsize=11,
    )
    fig_post.tight_layout()
    mo.as_html(fig_post)
    return


@app.cell
def arm_allocation_plot(
    mo,
    n_arms,
    np,
    plt,
    thompson_alphas,
    thompson_betas,
    true_probs,
):
    """Show how Thompson allocated pulls across arms."""
    _pulls = (thompson_alphas - 1 + thompson_betas - 1).astype(int)
    _total = int(_pulls.sum())
    _colors = plt.cm.tab10(np.linspace(0, 1, n_arms))

    fig_alloc, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(12, 4))

    _bars = _ax1.bar(range(n_arms), _pulls, color=_colors)
    for _i, (_bar, _p) in enumerate(zip(_bars, _pulls)):
        _ax1.text(
            _bar.get_x() + _bar.get_width() / 2, _p,
            f"{int(_p)}\n({int(_p) / _total:.0%})",
            ha="center", va="bottom", fontsize=8,
        )
    _ax1.set_xlabel("arm")
    _ax1.set_ylabel("pulls")
    _ax1.set_title("Pull allocation by arm")
    _ax1.set_xticks(range(n_arms))

    # Regret contribution per arm
    _regret_per_arm = _pulls * (true_probs[0] - true_probs)
    _bars2 = _ax2.bar(range(n_arms), _regret_per_arm, color=_colors)
    _ax2.set_xlabel("arm")
    _ax2.set_ylabel("regret contribution")
    _ax2.set_title("Regret contribution by arm")
    _ax2.set_xticks(range(n_arms))

    fig_alloc.tight_layout()
    mo.as_html(fig_alloc)
    return


@app.cell
def contextual_section(mo):
    mo.md(r"""
    ## Contextual bandits — when the best arm depends on features

    In many real problems, the optimal arm varies with context. A
    "young user" might respond best to arm 2, while an "older user"
    responds best to arm 0. **Contextual Thompson sampling** maintains
    a posterior per (context, arm) pair.

    The simplest version: discretize the context into bins and run
    independent Thompson sampling per bin. More sophisticated: use a
    logistic regression model per arm with Bayesian updates (Laplace
    approximation or variational inference).

    Below we simulate a 2-context, 3-arm problem where the best arm
    flips depending on context.
    """)
    return


@app.cell
def contextual_bandit(mo, np, plt, stats):
    """Contextual bandit: 2 contexts, 3 arms, best arm differs by context."""
    _rng = np.random.default_rng(99)
    _n_contexts = 2
    _n_arms_ctx = 3
    _horizon_ctx = 1500

    # True probabilities: shape (n_contexts, n_arms)
    # Context 0: arm 2 is best; Context 1: arm 0 is best
    _true_p = np.array([
        [0.2, 0.3, 0.6],  # context 0
        [0.7, 0.4, 0.15],  # context 1
    ])

    # Thompson sampling with per-context posteriors
    _alphas = np.ones((_n_contexts, _n_arms_ctx))
    _betas = np.ones((_n_contexts, _n_arms_ctx))
    _cum_regret = np.zeros(_horizon_ctx)
    _regret_so_far = 0.0

    for _t in range(_horizon_ctx):
        _ctx = int(_rng.integers(0, _n_contexts))
        _samples = _rng.beta(_alphas[_ctx], _betas[_ctx])
        _arm = int(np.argmax(_samples))
        _reward = int(_rng.random() < _true_p[_ctx, _arm])
        _alphas[_ctx, _arm] += _reward
        _betas[_ctx, _arm] += 1 - _reward
        _regret_so_far += _true_p[_ctx].max() - _true_p[_ctx, _arm]
        _cum_regret[_t] = _regret_so_far

    # Plot: posteriors per context + regret
    fig_ctx, _axes_ctx = plt.subplots(1, 3, figsize=(15, 4))

    _ctx_colors = ["#4477aa", "#cc3311", "#228833"]
    for _ctx_idx in range(_n_contexts):
        _ax = _axes_ctx[_ctx_idx]
        for _arm_idx in range(_n_arms_ctx):
            _dist = stats.beta(
                _alphas[_ctx_idx, _arm_idx],
                _betas[_ctx_idx, _arm_idx],
            )
            _x = np.linspace(
                max(0, float(_dist.ppf(0.001))),
                min(1, float(_dist.ppf(0.999))),
                200,
            )
            _pulls_ct = int(
                _alphas[_ctx_idx, _arm_idx]
                + _betas[_ctx_idx, _arm_idx] - 2
            )
            _ax.plot(
                _x, _dist.pdf(_x), lw=2, color=_ctx_colors[_arm_idx],
                label=f"arm {_arm_idx} (true={_true_p[_ctx_idx, _arm_idx]:.2f}, n={_pulls_ct})",
            )
            _ax.axvline(
                _true_p[_ctx_idx, _arm_idx], color=_ctx_colors[_arm_idx],
                ls="--", lw=1, alpha=0.5,
            )
        _best = int(np.argmax(_true_p[_ctx_idx]))
        _ax.set_title(f"Context {_ctx_idx} (best = arm {_best})")
        _ax.set_xlabel("reward probability")
        _ax.legend(fontsize=7)

    _axes_ctx[2].plot(
        np.arange(_horizon_ctx), _cum_regret,
        lw=2, color="#228833",
    )
    _axes_ctx[2].set_xlabel("round")
    _axes_ctx[2].set_ylabel("cumulative regret")
    _axes_ctx[2].set_title("Contextual Thompson — regret")

    fig_ctx.tight_layout()
    mo.as_html(fig_ctx)
    return


@app.cell
def theory_section(mo):
    mo.md(r"""
    ## Why Thompson sampling works

    Thompson sampling has **optimal** (Lai-Robbins) regret bounds for
    Bernoulli bandits: $O(\sum_i \frac{\ln T}{\text{KL}(p_i, p^*)})$
    where the sum is over suboptimal arms and KL is the
    Kullback-Leibler divergence.

    Intuitively:

    - **Early on**, posteriors are wide, so the algorithm explores
      naturally — it's genuinely uncertain about which arm is best
    - **Over time**, posteriors concentrate around the true values,
      and the probability of sampling a suboptimal arm's posterior
      above the best arm's shrinks exponentially
    - **Unlike epsilon-greedy**, it never wastes exploration on arms
      it's already confident are bad
    - **Unlike UCB**, it randomizes exploration, which makes it robust
      to adversarial settings and easier to deploy in batched/delayed
      feedback scenarios

    The connection to A/B testing is direct: a standard A/B test is a
    2-arm bandit where you fix the allocation (50/50) and only decide
    at the end. Thompson sampling **adapts allocation during the
    experiment**, sending more traffic to the arm that appears better,
    reducing the total number of users exposed to the worse variant.
    """)
    return


@app.cell
def real_world_examples(mo):
    mo.md(r"""
    ## Real-world applications

    Thompson sampling works anywhere you repeatedly choose among
    options and observe a reward. The key requirement: **fast feedback
    loops** so the bandit can adapt allocation in real time.

    ### Ad creative rotation
    - **Arms:** 5-10 ad creatives (images, headlines, CTAs)
    - **Reward:** click (1) or no click (0)
    - **Model:** Beta-Bernoulli per creative
    - **Why bandits:** you serve millions of impressions/day — even a
      few hours of exploration is enough to identify the winner, and
      every impression on a bad creative is wasted ad spend
    - **Gotcha:** creatives fatigue over time — use a sliding window
      or discounted Thompson to adapt

    ### Dynamic pricing
    - **Arms:** 4-6 price points ($9.99, $12.99, $14.99, $19.99, ...)
    - **Reward:** purchase (1/0), or revenue ($) for continuous reward
    - **Model:** Beta-Bernoulli per price for conversion; Normal-
      InverseGamma per price for revenue
    - **Why bandits:** you want to converge to the revenue-maximizing
      price without running a month-long A/B test at each price point
    - **Extension:** contextual — optimal price may differ by user
      segment (new vs. returning, geography, device)

    ### Content recommendation (news, streaming)
    - **Arms:** top-N articles or shows to feature in the hero slot
    - **Reward:** click-through (1/0) or engagement time
    - **Model:** contextual Thompson — features include user history,
      time of day, device
    - **Why bandits:** content is perishable (news articles, trending
      shows) — you need to learn and exploit within hours, not weeks

    ### Clinical dose-finding (Phase I trials)
    - **Arms:** dose levels (10mg, 25mg, 50mg, 100mg)
    - **Reward:** efficacy without toxicity (binary or ordinal)
    - **Model:** Beta-Bernoulli per dose, with monotonicity constraint
      (higher dose = higher efficacy but also higher toxicity)
    - **Why bandits:** minimize patient exposure to ineffective or
      toxic doses — every allocation to a bad arm is an actual patient
    - **Regulatory note:** adaptive designs need pre-registration and
      simulation-based operating characteristics

    ### Notification timing
    - **Arms:** time slots (morning, afternoon, evening, night)
    - **Reward:** user opened the notification (1/0)
    - **Model:** contextual Thompson — context = user timezone, app
      usage pattern, day of week
    - **Why bandits:** optimal timing varies per user — a global A/B
      test finds the best average time, but bandits personalize

    ### Feature flag rollout
    - **Arms:** feature ON vs. feature OFF
    - **Reward:** key engagement metric (conversion, retention)
    - **Model:** Beta-Bernoulli (same as A/B test, but adaptive)
    - **Why bandits over A/B test:** if the feature is clearly better
      after 1000 users, bandits automatically ramp it to 100% without
      waiting for a predetermined sample size
    """)
    return


@app.cell
def your_data_section(mo):
    mo.md(r"""
    ## Applying to your data

    ### Expected data format

    A bandit needs an **event log** — one row per interaction:

    | Column | Type | Description |
    |---|---|---|
    | `timestamp` | datetime | When the interaction happened |
    | `arm` | str/int | Which variant was shown |
    | `reward` | 0 or 1 | Did the user convert? (Bernoulli) |
    | `context` | dict/cols | (Optional) User features for contextual bandits |

    ```python
    import ibis

    events = ibis.duckdb.connect().read_parquet("data/events.parquet")

    # Aggregate to sufficient statistics per arm
    arm_stats = (
        events
        .group_by("arm")
        .aggregate(
            successes=events.reward.sum().cast("int64"),
            trials=events.count(),
        )
        .execute()
    )

    # Initialize Thompson sampler from historical data
    for _, row in arm_stats.iterrows():
        sampler.alphas[row.arm] = 1 + row.successes
        sampler.betas[row.arm] = 1 + row.trials - row.successes
    ```

    ### When bandits are the right tool

    - You can **act on results in real time** (update allocation each
      batch or each request)
    - The feedback loop is **fast** (hours, not weeks)
    - You care about **minimizing total regret** (cumulative exposure
      to the worse variant), not just identifying a winner

    ### When to use something else

    - **You need a causal effect estimate** with pre-registered sample
      size → A/B test (`bayesian-ab-testing`)
    - **Feedback is delayed by days/weeks** → bandits can't adapt fast
      enough; use a fixed-allocation test
    - **You have > 50 arms with sparse rewards** → explore
      collaborative filtering or neural bandits
    - **Rewards change over time** → use discounted Thompson sampling
      (not covered here)
    """)
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    1. **Thompson sampling = sample from the posterior, pull the
       highest.** For Bernoulli arms, the posterior is
       Beta(1 + successes, 1 + failures). No MCMC needed.
    2. **Regret, not accuracy.** The right metric for bandits is
       cumulative regret (total reward lost vs. the oracle), not
       "which arm won." Lower regret = fewer users exposed to the
       worse arm.
    3. **Thompson beats epsilon-greedy and UCB on most practical
       problems** — it concentrates exploration where it matters and
       naturally handles unequal arm quality.
    4. **Contextual bandits** = Thompson per context. For continuous
       contexts, use logistic Thompson sampling or neural bandits.

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/bayesian-bandits/` directory and your AI agent
    will follow the same patterns on your real data.
    """)
    return


if __name__ == "__main__":
    app.run()
