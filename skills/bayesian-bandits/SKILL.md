---
name: bayesian-bandits
description: Implement Thompson sampling for multi-armed and contextual bandits. Use when the user wants to adaptively allocate traffic across variants (ads, recommendations, content, pricing) to minimize regret instead of running a fixed-allocation A/B test. Covers Bernoulli bandits, contextual bandits, regret analysis, and comparison with epsilon-greedy and UCB.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
-->

# Bayesian Bandits — Thompson Sampling

For problems where you want to **learn and exploit simultaneously**,
use multi-armed bandits with Thompson sampling. Unlike A/B testing
(which fixes traffic allocation and decides at the end), bandits
adapt allocation during the experiment — sending more traffic to
better-performing arms and reducing the total number of users exposed
to inferior variants.

## When to use this skill

- Multiple variants (ads, landing pages, recommendations, pricing
  tiers) and you want to minimize total regret, not just identify a
  winner
- You can act on results in real time (update allocation each round
  or batch)
- The cost of showing a bad variant is high enough that fixed 50/50
  allocation is wasteful
- You want an "always-on" optimization that converges to the best arm
  without a predefined stopping rule
- Contextual: the best variant depends on user features (segment,
  device, geography)

## When NOT to use this skill

- You need a clean causal estimate of treatment effect with
  pre-registered sample size → use `bayesian-ab-testing`
- The reward is delayed by days/weeks (bandits need fast feedback
  loops to adapt effectively)
- You have more than ~50 arms with sparse rewards → consider
  collaborative filtering or neural bandits
- The reward distribution changes over time (non-stationary) → use
  sliding-window or discounted Thompson sampling (not covered here)

## Project layout

```
<project>/
├── src/
│   ├── bandit.py          # BernoulliBandit, ThompsonSampler classes
│   ├── baselines.py       # EpsilonGreedy, UCB1 for comparison
│   ├── simulate.py        # Run simulations, compute regret
│   └── contextual.py      # ContextualThompson (per-bin or logistic)
├── notebooks/
│   └── demo.py            # marimo walkthrough
└── results/               # regret curves, posterior snapshots
```

## Core algorithm — Thompson sampling for Bernoulli arms

```python
import numpy as np

class ThompsonBernoulli:
    def __init__(self, n_arms: int):
        self.alphas = np.ones(n_arms)  # Beta prior: successes + 1
        self.betas = np.ones(n_arms)   # Beta prior: failures + 1

    def select_arm(self, rng: np.random.Generator) -> int:
        samples = rng.beta(self.alphas, self.betas)
        return int(np.argmax(samples))

    def update(self, arm: int, reward: int):
        self.alphas[arm] += reward
        self.betas[arm] += 1 - reward
```

That's the entire algorithm. No MCMC, no optimization, no
hyperparameters. The Beta posterior is conjugate to the Bernoulli
likelihood, so updates are exact and O(1).

## Why Thompson beats the alternatives

### vs. Epsilon-greedy

Epsilon-greedy explores uniformly — it wastes pulls on arms it
already knows are bad. Thompson concentrates exploration on arms
that *might* be best (their posterior overlaps with the current
leader).

### vs. UCB1

UCB is deterministic and optimistic — it always pulls the arm with
the highest upper confidence bound. Thompson randomizes, which makes
it:
- More robust to delayed feedback (common in production)
- Naturally handles batched updates
- Easier to parallelize across concurrent requests

### Regret bounds

Thompson sampling achieves the **Lai-Robbins lower bound** for
Bernoulli bandits:

$$R(T) = O\left(\sum_{i: p_i < p^*} \frac{\ln T}{\text{KL}(p_i \| p^*)}\right)$$

This is optimal — no algorithm can do better asymptotically.

## Contextual bandits

When the best arm depends on context (user features), maintain
separate posteriors per context:

### Simple: discrete contexts

```python
class ContextualThompson:
    def __init__(self, n_contexts: int, n_arms: int):
        self.agents = [
            ThompsonBernoulli(n_arms) for _ in range(n_contexts)
        ]

    def select_arm(self, context: int, rng) -> int:
        return self.agents[context].select_arm(rng)

    def update(self, context: int, arm: int, reward: int):
        self.agents[context].update(arm, reward)
```

### Advanced: continuous contexts (logistic Thompson)

For continuous features, model the reward probability with a
logistic regression per arm and use a Laplace approximation for the
posterior. Each round, sample coefficients from the approximate
posterior and pick the arm with the highest predicted reward. This
is "logistic Thompson sampling" — see Chapelle & Li (2011).

## Regret analysis

Always plot **cumulative regret** over time:

```python
def cumulative_regret(arm_choices, rewards, true_probs):
    best_prob = true_probs.max()
    instant_regret = best_prob - true_probs[arm_choices]
    return np.cumsum(instant_regret)
```

Run multiple simulations and plot mean +/- std to get a stable
picture. Thompson's regret curve should be **sublinear** (flattening
over time), while epsilon-greedy's is **linear** (constant
exploration waste).

## Batched Thompson sampling

In production you often can't update after every single event. With
batched updates (e.g., every 1000 impressions), Thompson still works
— just accumulate successes/failures per batch and update once:

```python
# End of batch
for arm in range(n_arms):
    agent.alphas[arm] += batch_successes[arm]
    agent.betas[arm] += batch_failures[arm]
```

The posterior is still exact. Batching only slows convergence; it
doesn't bias the algorithm.

## MLflow logging

For bandit experiments, log:

| Kind | What |
|---|---|
| `params` | n_arms, horizon, algorithm, epsilon (if egreedy), prior_alpha, prior_beta, n_contexts (if contextual) |
| `metrics` | final_cumulative_regret, mean_regret_per_round, best_arm_pull_fraction, convergence_round (round at which best arm gets >90% of pulls) |
| `tags` | true_probs (as JSON), best_arm |
| `artifacts` | regret_curve.png, posterior_snapshots.png, arm_allocation.png |

## Common pitfalls

1. **Using bandits when you need causal inference.** Bandits optimize
   allocation but don't give you a clean estimate of treatment effect.
   If regulatory or scientific rigor requires a pre-registered sample
   size and unbiased estimator, use an A/B test.
2. **Ignoring delayed feedback.** If conversions take 7 days to
   materialize, the bandit is making decisions based on stale data.
   Either shorten the feedback loop (use a proxy metric) or add a
   delay buffer before updating.
3. **Too many arms with sparse rewards.** With 100 arms and 1%
   conversion, most arms will have zero conversions for a long time.
   Thompson still works but converges very slowly — consider
   hierarchical priors or neural bandits.
4. **Non-stationary rewards.** If the true probabilities change over
   time, standard Thompson will be slow to adapt. Use a discounted
   version: decay alphas and betas each round by a factor gamma < 1.
5. **Forgetting the prior matters.** Beta(1,1) is uniform — fine for
   most problems. But if you have historical data (last month's CTR
   was 3%), initialize with Beta(3, 97) to avoid wasting the first
   few hundred pulls on exploration you don't need.
6. **Comparing regret across different arm configurations.** Regret
   depends on the gap between the best and second-best arm. A
   "higher regret" run might just have harder arms, not a worse
   algorithm. Always compare algorithms on the same arm configuration.

## Worked example

See `demo.py` (marimo notebook). It simulates a multi-armed Bernoulli
bandit, runs Thompson sampling, epsilon-greedy, and UCB1 head-to-head,
and shows interactive regret curves, posterior evolution, arm
allocation, and a contextual bandit example. Run it with:

```
marimo edit --sandbox demo.py
```
