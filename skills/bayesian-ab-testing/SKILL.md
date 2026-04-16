---
name: bayesian-ab-testing
description: Run a Bayesian A/B test on conversion data using PyMC. Use when the user wants to compare two variants (landing pages, emails, pricing, UI changes) and decide which to ship using posterior probabilities and expected loss instead of p-values. Covers Beta-Binomial model, ROPE, expected loss, sample-size guidance, and ArviZ diagnostics.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
-->

# Bayesian A/B Testing with PyMC

For comparing two variants on a conversion metric, **use Bayesian A/B
testing**. It directly answers the questions stakeholders actually ask
— "What's the probability B is better?" and "How much do we lose if
we're wrong?" — without the fragile rituals of frequentist hypothesis
testing (no p-values, no fixed sample sizes, no "don't peek" rules).

## When to use this skill

- Two variants (A/B) with a binary outcome (converted / didn't)
- You want to know **P(B > A)** and **expected loss**, not a p-value
- You want to monitor the experiment continuously without inflating
  error rates (Bayesian posteriors are always valid — peeking is free)
- You have unequal sample sizes across arms
- Stakeholders need a decision framework: "ship B", "keep A", or
  "keep collecting data"

## When NOT to use this skill

- More than two variants → extend to multi-arm (or use bandits skill)
- Continuous outcome (revenue per user, time on page) → use
  `bayesian-regression` with a Normal/LogNormal likelihood
- You want to *adaptively allocate traffic* during the experiment →
  use `bayesian-bandits` (Thompson sampling)
- The metric isn't conversion (binary) — e.g., count data (page views
  per session) → use a Poisson or Negative Binomial likelihood

## Project layout

```
<project>/
├── data/                # input parquet/csv (or generate in-notebook)
├── src/
│   ├── train.py         # PyMC model fit → MLflow log
│   ├── predict.py       # reload idata, compute decision metrics
│   └── plots.py         # posterior, trace, loss, ROPE visualizations
├── notebooks/
│   └── demo.py          # marimo walkthrough
└── mlruns/              # MLflow tracking store (gitignored)
```

## Data format

The model needs four numbers — that's it:

| Field | Type | Description |
|---|---|---|
| `n_a` | int | Visitors assigned to control (A) |
| `conversions_a` | int | Conversions in control |
| `n_b` | int | Visitors assigned to treatment (B) |
| `conversions_b` | int | Conversions in treatment |

If the buyer has row-level data (one row per visitor with a 0/1
outcome column and a variant column), aggregate first:

```python
import ibis

table = ibis.duckdb.connect().read_parquet("data/experiment.parquet")
summary = (
    table
    .group_by("variant")
    .aggregate(
        visitors=table.count(),
        conversions=table.converted.sum().cast("int64"),
    )
    .execute()
)
n_a = int(summary.loc[summary.variant == "control", "visitors"].iloc[0])
conversions_a = int(summary.loc[summary.variant == "control", "conversions"].iloc[0])
n_b = int(summary.loc[summary.variant == "treatment", "visitors"].iloc[0])
conversions_b = int(summary.loc[summary.variant == "treatment", "conversions"].iloc[0])
```

## The model — Beta-Binomial

```python
import pymc as pm

with pm.Model() as ab_model:
    # Priors — Beta(1,1) = uniform if no prior knowledge
    # Use informative priors if you have historical conversion rates
    p_a = pm.Beta("p_A", alpha=1, beta=1)
    p_b = pm.Beta("p_B", alpha=1, beta=1)

    # The quantity of interest: absolute lift
    delta = pm.Deterministic("delta", p_b - p_a)
    pm.Deterministic("relative_lift", (p_b - p_a) / p_a)

    # Likelihood — use Binomial with sufficient statistics,
    # NOT N independent Bernoulli observations
    pm.Binomial("obs_A", n=n_a, p=p_a, observed=conversions_a)
    pm.Binomial("obs_B", n=n_b, p=p_b, observed=conversions_b)

    idata = pm.sample(
        draws=2000, tune=1000, chains=4,
        random_seed=42, progressbar=False,
    )
```

**Why Binomial, not Bernoulli?** The likelihood is mathematically
identical, but the sampler operates on 4 numbers instead of
N observations. Much faster, and it documents the right move when
sufficient statistics exist.

**Why PyMC when this is conjugate?** Real A/B tests often need
non-conjugate extensions (covariates, segments, time-varying rates).
The PyMC pattern transfers unchanged. Verify against the closed-form
answer once to build trust, then move on.

## Priors — when to be informative

| Situation | Prior | Why |
|---|---|---|
| No idea what to expect | Beta(1, 1) | Uniform on [0, 1] |
| Typical web conversion (~3-5%) | Beta(3, 97) | Concentrates around 3% |
| Strong historical data (last quarter's rate) | Beta(α, β) from method of moments | Use the data you have |

Method of moments for Beta priors from a known mean μ and sample size
proxy κ (how many "pseudo-observations" the prior is worth):

```python
alpha_0 = mu * kappa
beta_0 = (1 - mu) * kappa
```

Start with κ = 1 (weak) and increase only if you have real historical
data backing it up.

## Decision framework — the four outputs

### 1. P(B > A)

```python
delta_samples = idata.posterior["delta"].to_numpy().flatten()
prob_b_better = float(np.mean(delta_samples > 0))
```

This is the probability that B's true conversion rate exceeds A's.
Not a p-value. Not "confidence." A direct probability.

### 2. Expected loss

```python
p_a_samples = idata.posterior["p_A"].to_numpy().flatten()
p_b_samples = idata.posterior["p_B"].to_numpy().flatten()

# If you choose B but A is actually better, your loss is (p_A - p_B)
loss_choosing_b = float(np.mean(np.maximum(p_a_samples - p_b_samples, 0)))
loss_choosing_a = float(np.mean(np.maximum(p_b_samples - p_a_samples, 0)))
```

**Pick the arm with lower expected loss.** This is the Bayes-optimal
decision under absolute-error loss. When both losses are tiny
(< 0.0001), the arms are effectively equivalent — stop the experiment.

### 3. ROPE (Region of Practical Equivalence)

```python
rope = 0.005  # minimum practically significant difference
prob_b_clears_rope = float(np.mean(delta_samples > rope))
prob_equivalent = float(np.mean(np.abs(delta_samples) < rope))
```

A 0.01% lift might be "statistically significant" with enough data
but operationally meaningless. Set a ROPE and check if the posterior
clears it.

### 4. Decision rule

```python
if loss_choosing_b < loss_choosing_a and prob_b_clears_rope > 0.90:
    decision = "Ship B"
elif prob_equivalent > 0.50:
    decision = "Practically equivalent — pick the cheaper option"
else:
    decision = "Keep collecting data"
```

## ArviZ diagnostics — always check

```python
import arviz as az

# Summary table with R-hat and ESS
summary = az.summary(idata, var_names=["p_A", "p_B", "delta"])

# Trace plot — chains should mix well (fuzzy caterpillars)
az.plot_trace(idata, var_names=["p_A", "p_B", "delta"])

# Posterior with HDI
az.plot_posterior(idata, var_names=["delta"], ref_val=0)
```

**Convergence checks:**
- R-hat < 1.01 for all parameters
- ESS (bulk and tail) > 400
- Trace plot shows well-mixed chains (no trends, no stuck chains)

If any check fails, increase `draws` and `tune` before trusting the
results.

## MLflow logging

For every A/B test run, log:

| Kind | What |
|---|---|
| `params` | n_a, n_b, conversions_a, conversions_b, prior_alpha, prior_beta, draws, tune, chains, seed, rope |
| `metrics` | prob_b_better, expected_loss_a, expected_loss_b, posterior_mean_delta, hdi_94_low, hdi_94_high, rhat_max, ess_min, prob_b_clears_rope |
| `tags` | data_hash, true_p_a, true_p_b (if synthetic) |
| `artifacts` | posterior/idata.nc, plots/{posterior.png, trace.png, loss.png, rope.png} |

## Sample size guidance

Unlike frequentist power analysis, Bayesian sample size is based on
expected loss. Run the conjugate update for increasing n and plot
expected loss vs sample size:

```python
from scipy import stats as sp_stats

for n in range(100, 10001, 100):
    k_a = int(n * observed_rate_a)
    k_b = int(n * observed_rate_b)
    post_a = sp_stats.beta(alpha_0 + k_a, beta_0 + n - k_a)
    post_b = sp_stats.beta(alpha_0 + k_b, beta_0 + n - k_b)
    draws_a = post_a.rvs(5000)
    draws_b = post_b.rvs(5000)
    expected_loss = np.mean(np.maximum(draws_a - draws_b, 0))
    # Stop when expected_loss < your tolerance
```

When expected loss drops below your business tolerance (e.g., 0.01%
of conversion rate), you have enough data.

## Common pitfalls

1. **Using Bernoulli instead of Binomial.** If you have 50,000
   visitors per arm, that's 100,000 Bernoulli observations the
   sampler has to process. Use Binomial(n, k) — same likelihood,
   orders of magnitude faster.
2. **Ignoring convergence diagnostics.** If R-hat > 1.01, your
   posterior is wrong. Always check before computing decision metrics.
3. **No ROPE.** Without a minimum effect size, you'll "detect" lifts
   of 0.001% with enough data and ship changes that don't matter.
4. **Peeking guilt.** Unlike frequentist tests, Bayesian posteriors
   are valid at any sample size. You *should* monitor expected loss
   over time and stop when it's low enough.
5. **Flat priors when you have data.** If last quarter's conversion
   rate was 4.2% with tight confidence, use that as your prior. Flat
   priors waste information.
6. **Forgetting that this is just conversion.** Revenue per user,
   average order value, and time-on-site need different likelihoods
   (Normal, LogNormal, Gamma). Don't shoehorn continuous metrics into
   binary.
7. **Running the test on a non-random split.** Bayesian inference
   can't fix selection bias. If treatment users are systematically
   different from control users, the posterior is wrong no matter how
   many samples you have.

## Worked example

See `demo.py` (marimo notebook). It generates synthetic A/B test
data, fits the Beta-Binomial model with PyMC, and shows interactive
posteriors, expected loss, ROPE analysis, sample-size curves, and a
side-by-side comparison with the frequentist z-test. Run it with:

```
marimo edit --sandbox demo.py
```
