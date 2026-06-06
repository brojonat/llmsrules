---
name: statistical-process-control
description: Monitor a metric over time with process behaviour charts (XmR / control charts) to separate routine variation from real process change. Use whenever the user wants to know "is this number unusual?", set alerting thresholds on a KPI or operational metric, detect anomalies or regressions in a time series of measurements, build a control chart, or replace ad-hoc "it looks high this week" judgments with something principled. Default to this for metric monitoring and threshold-setting tasks — even when the user doesn't say "SPC" or "control chart" — including dashboards, SLO/error-rate watching, manufacturing quality data, and weekly business reviews.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked examples
-->

# Statistical Process Control (Process Behaviour Charts)

Every metric wiggles. The question that matters is never "did the number
change?" — it always changed — but **"did the process that generates the
number change?"** Statistical process control answers that one question,
and answering it wrong is expensive in both directions: chase routine
noise and you waste investigation time (and often make the process
*worse* by tampering); dismiss a real shift as noise and you miss the
regression, the fraud, the failing pump.

The default tool is the **XmR chart** (individuals + moving range, also
called a process behaviour chart). It needs no distributional
assumptions, works on almost any stream of individual measurements, and
is simple enough to compute in ten lines of numpy. Simplicity is a
feature, not a compromise: practitioners have replaced fleets of deep-net
anomaly detectors with charts like these, at 3–4 orders of magnitude
fewer parameters, because a small team can actually understand, debug,
and trust them. If the algorithm isn't simple, it's probably not worth
your time.

## When to use this skill

- A metric measured repeatedly over time (latency, defect rate, daily
  revenue, cycle time, temperature, error count) and someone needs to
  know when it *really* changed
- Setting alerting thresholds that aren't arbitrary ("page when > 500ms"
  — says who?)
- Deciding whether an intervention (deploy, process change, training)
  actually moved the needle or just coincided with noise
- Manufacturing / quality data with rational subgroups (X̄ charts)

## When NOT to use this skill

- **Forecasting** future values → time-series models (the chart tells
  you *whether* the future will look like the past, not what it will be)
- **Strongly seasonal/trending/autocorrelated data charted raw** — the
  chart still applies, but only *after* you derive a stationary stream
  (see "Derive the stream first", the most important section here)
- One-off A/B comparisons between two groups → hypothesis tests or the
  bayesian-ab-testing skill
- Root-causing *why* a signal happened — the chart only tells you *when*
  and *that* it happened

## Vocabulary (Shewhart / Wheeler)

- **Common cause (routine) variation**: the noise inherent to the
  process. Every point is different; no point has an explanation.
- **Special cause (assignable) variation**: variation with an
  identifiable, findable cause that is not part of the process.
- **Stable / predictable process**: only common causes present. Any
  given week looks statistically like any other week. You cannot explain
  individual points, but you *can* predict the range of future ones.
- **Unstable process**: assignable causes present. Prediction is
  meaningless until they're found and removed.

## The XmR chart

Given individual values x₁…xₙ from a baseline period:

```
X̄    = mean(x)
mR̄   = mean(|xᵢ − xᵢ₋₁|)          # average moving range
UNPL = X̄ + 2.66 · mR̄              # upper natural process limit
LNPL = X̄ − 2.66 · mR̄              # lower natural process limit
mR_UCL = 3.268 · mR̄               # upper limit for the mR chart itself
```

Plot the values with the center line and limits; optionally plot the
moving ranges with their own limit underneath (a spread change can show
up there before it shows in the individuals).

**Why the moving range and not the standard deviation of the data?**
The global SD measures spread of the whole dataset — if the data
contains a shift or outliers (exactly the things you're hunting), the
global SD is inflated by them, the limits swell, and the chart goes
blind to its own signals. Consecutive differences capture only the
point-to-point, common-cause component of dispersion. This is the whole
trick. Never compute limits as `mean ± 3·std(data)`.

**Why 2.66, and why it's non-negotiable.** 2.66 = 3/1.128, where 1.128
(d₂ for n=2) converts the mean moving range into a sigma estimate, so
the limits sit at ±3 sigma-equivalents. The 3 is an *economic* choice
validated by a century of practice, not a normality assumption — by
Chebyshev-type arguments the limits are conservative for *any*
distribution. People will pressure you to use 2 ("more sensitive") or
3.5 ("fewer pages"). Refuse. Tuning the constant is how a chart
degenerates back into an arbitrary threshold.

**Don't transform the data first.** No logs, no winsorizing, no
removing "obvious outliers" before computing limits. Transformations
hide exactly the signals you're looking for. The one acceptable
"transformation" is deriving a stationary stream (below) — which changes
*what* you chart, not the values' integrity.

## Detection rules — use as few as you can get away with

1. **Rule 1**: a point outside the natural process limits.
2. **Rule 2**: nine (or more) consecutive points on the same side of the
   center line — detects sustained smaller shifts.

That's it, by default. The Western Electric handbook lists more (2-of-3
beyond 2σ, etc.); every rule you add raises the false-alarm rate, and
false alarms are not free — each one consumes an investigation and
erodes trust in the chart. Add a rule only when the cost of missing its
specific pattern demonstrably exceeds the cost of its extra false
alarms.

## Compute limits once, then freeze them

Compute limits from a **baseline window** (~20 points is comfortable;
even 10–15 is usable — imperfect limits now beat perfect limits never).
Then **extend them indefinitely**. A stable process is exactly a process
where next month looks like the baseline, so the limits don't expire.

Recompute only when the process itself verifiably changed:
- you found and removed an assignable cause, or
- you made a deliberate system improvement and the chart confirms a new
  sustained level.

**Never recompute limits on a rolling window.** Rolling limits absorb
every anomaly into the baseline — the chart adapts to the disease and
stops reporting it. This is the central tension of automated monitoring:
make the limits too robust to outliers and the system never adapts to a
legitimate new normal; make them too adaptive and anomalies tarnish the
thresholds and you drown in misses or false alarms. Frozen limits +
deliberate, human-confirmed re-baselining is the simple resolution, and
it's the right default. If you automate re-baselining at scale, exclude
signal-flagged points from the new baseline and require the new level to
persist before adopting it.

## Derive the stream first (the most important bit)

XmR limits assume successive points are exchangeable — no trend, no
seasonality, no strong autocorrelation. Raw operational telemetry is
almost never like this (day-of-week effects, time-of-day cycles,
growth). Charting it raw produces either constant false alarms or
limits so wide they catch nothing.

The fix is not a fancier chart; it's **charting a derived stream that
no longer has temporal structure**. Practitioners who run thousands of
these charts report this is the most important part of the whole
system. Standard derivations:

| Raw stream problem | Derived stream to chart |
|---|---|
| Day-of-week / hour-of-day seasonality | residual vs. per-period baseline median (e.g. value − median for that weekday) |
| Trend / growth | first differences, or % change period-over-period |
| Too noisy / high frequency | per-period statistic: daily mean, daily p95, daily spread — then chart *that* |
| Care about spread, not level | chart the per-period IQR or SD as its own stream |
| Multiplicative seasonality | ratio to same-period-last-cycle |

Compute the per-period baseline (the weekday medians, etc.) from the
**baseline window only** and freeze it along with the limits — otherwise
anomalies leak into the seasonal profile. Pick the derived statistic to
match the question: "did the mean change?", "did the spread change?",
"did the tail (p95) change?" are different charts. Often you run more
than one per stream.

## When the data is too ugly for 3-sigma: go nonparametric

If points-per-baseline is large and the distribution is heavy-tailed,
multimodal, or just slow to converge to anything Gaussian-ish, skip the
sigma machinery: set limits at empirical quantiles of the frozen
baseline (e.g. 0.5% / 99.5%), chosen by your **appetite for false
alarms** (quantile q → expect ~(1−q) of in-control points to alarm; at
one point/day, a 99.5% limit alarms about twice a year per stream by
chance — scale that by your stream count). Everything else — freeze the
limits, derive the stream first, minimal rules — stays the same. This is
"nonparametric SPC"; the literature is deep but the algorithms worth
using stay simple.

## Subgrouped charts (X̄, when you have rational subgroups)

When measurements come in natural batches (20 samples per lot, per
shift, per site), chart the subgroup means with limits from the
**within-subgroup** variation:

```
σ̂_w  = sqrt( Σ (nᵢ−1)·sᵢ² / Σ (nᵢ−1) )    # pooled within-subgroup SD
CL   = mean of subgroup means
UCL  = CL + 3·σ̂_w/√n̄ ,  LCL = CL − 3·σ̂_w/√n̄
```

Same trick as the moving range, one level up: within-subgroup spread
estimates common-cause variation untainted by between-subgroup shifts —
which are the signals. This only works with **rational subgroups**:
units within a subgroup produced under essentially the same conditions.
If a subgroup spans the thing that varies (e.g. "this week's data" when
the shift happened Wednesday), the signal averages away — the
report-card effect. When in doubt, fall back to the XmR chart on
individual values or per-period statistics; it's almost always
serviceable.

## Acting on the chart

The two charts demand opposite responses, and mixing them up is the
classic failure mode:

- **Stable process, point you don't like**: do *not* react to the
  point. Adjusting a stable process in response to individual outcomes
  is **tampering**, and it provably increases variation (Deming's funnel
  experiment). The only way to improve a stable process is to change
  the *system* — and prefer reducing variation before moving the mean;
  variation has direct costs people underestimate.
- **Unstable process**: find and remove assignable causes first. Don't
  start systematic improvement, capability claims, or forecasts on an
  unstable process — there is no "the process" to improve yet.
- **Limits vs. targets**: the limits are the *process telling you what
  it is capable of*. You don't get to pick them. A target/spec line can
  go on the chart, but if the target is outside the natural limits, no
  amount of exhortation will hit it reliably — only system change will.
  Setting goals without a method is wishful thinking, and it makes
  things worse via demotivation or gaming.

## Common mistakes

1. **`mean ± 3·std(data)` limits.** Inflated by the very signals you
   want to catch. Use the moving range (or pooled within-subgroup SD).
2. **Rolling/auto-recomputed limits.** The chart adapts to anomalies and
   goes silent. Freeze the baseline.
3. **Charting raw seasonal/trending data.** Derive a stationary stream
   first.
4. **Too many detection rules.** Each added rule buys sensitivity with
   false alarms; investigations are expensive.
5. **Transforming or "cleaning" data before charting.** Hides signals.
6. **Tampering**: adjusting a stable process point-by-point. Increases
   variation.
7. **Treating two points as a trend.** "Up from last week" or "above
   average" carries almost no information — half of all points are above
   average by construction. This is most of what business reporting does;
   the chart is the antidote.
8. **Fitting a distribution first.** You don't need normality, and
   assuming a distribution makes you blind to the mixed/interleaved
   processes the chart would otherwise reveal.
9. **Over-aggregating.** One company-wide super-metric averages away
   every actionable signal. Chart processes at the level where causes
   live.

## Implementation

Plain numpy/pandas/matplotlib — no SPC library needed, and the
transparency is worth more than the convenience:

```python
import numpy as np

def xmr_limits(baseline: np.ndarray) -> dict:
    """Natural process limits from a frozen baseline window."""
    x = np.asarray(baseline, dtype=float)
    center = x.mean()
    mr_bar = np.abs(np.diff(x)).mean()
    return {
        "center": center,
        "lnpl": center - 2.66 * mr_bar,   # 2.66 = 3/1.128; do not tune
        "unpl": center + 2.66 * mr_bar,
        "mr_bar": mr_bar,
        "mr_ucl": 3.268 * mr_bar,
    }

def xmr_signals(values: np.ndarray, lim: dict) -> dict:
    """Rule 1 (outside limits) and Rule 2 (run of 9 on one side)."""
    x = np.asarray(values, dtype=float)
    outside = (x > lim["unpl"]) | (x < lim["lnpl"])
    side = np.sign(x - lim["center"])
    run = np.zeros(len(x), dtype=bool)
    streak = 0
    for i in range(len(x)):
        streak = streak + 1 if i > 0 and side[i] == side[i - 1] and side[i] != 0 else 1
        if streak >= 9:
            run[i - 8 : i + 1] = True
    return {"outside_limits": outside, "run_of_nine": run}
```

Chart rendering: plot values as a connected line with dots, center line
solid, limits dashed, signals highlighted in red, and shade or mark the
baseline window so readers know what the limits were computed from.
Always show the limits' provenance — a chart whose limits can't be
traced to a baseline is just decoration.

## Worked example

See `scripts/demo.py` (marimo notebook, `marimo edit --sandbox demo.py`).
It builds, from synthetic data with known injected signals:

1. An XmR chart catching a spike (Rule 1) and a sustained shift (Rule 2)
2. The same data with naive `mean ± 3·std` limits — demonstrating how
   the global SD swallows the shift
3. A day-of-week seasonal stream where the raw chart is useless and a
   deseasonalized derived stream catches the injected level change
4. The mR chart catching a variance increase the X chart misses

## Sources

- Kjetil Halvorsen, *Statistical Process Control: A Practitioner's
  Guide* (entropicthoughts.com) — XmR-first approach, frozen limits,
  minimal rules
- Timothy Fraser, *Statistical Process Control in Python*
  (timothyfraser.com/sigma) — subgrouped charts, pooled-SD mechanics
- HN discussion (news.ycombinator.com/item?id=46055421), comments by
  srean — nonparametric SPC at scale, deriving stationary streams,
  robustness-vs-adaptivity of thresholds
- Donald Wheeler, *Understanding Variation* — the canonical book-length
  treatment
