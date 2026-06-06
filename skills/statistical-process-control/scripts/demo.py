# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo",
#     "numpy>=1.26",
#     "pandas>=2.2",
#     "matplotlib>=3.9",
# ]
# ///
"""Worked examples for the statistical-process-control skill.

Self-contained: generates synthetic process data with known injected
signals, builds XmR (process behaviour) charts, and demonstrates the
four lessons that matter in practice:

1. XmR limits catch a spike (Rule 1) and a sustained shift (Rule 2)
2. Naive mean ± 3·std limits swallow the very shift they should catch
3. Seasonal data must be charted as a derived (deseasonalized) stream
4. The mR chart identifies a spread change as a spread change

    marimo edit --sandbox demo.py
"""

import marimo

__generated_with = "0.23.9"
app = marimo.App(width="medium")


@app.cell
def intro(mo):
    mo.md("""
    # Process Behaviour Charts (XmR) — worked examples

    Every metric wiggles. The chart answers the only question that
    matters: **did the process change, or is this routine variation?**

    Limits come from the **average moving range** of a frozen baseline
    window — never from the global standard deviation, and never
    recomputed on a rolling window. Each example below injects a known
    signal into synthetic data so you can verify the chart finds it.
    """)
    return


@app.cell
def imports():
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    return mo, np, pd, plt


@app.cell
def core_functions(np):
    def xmr_limits(baseline):
        """Natural process limits from a frozen baseline window."""
        x = np.asarray(baseline, dtype=float)
        center = x.mean()
        mr_bar = np.abs(np.diff(x)).mean()
        return {
            "center": center,
            "lnpl": center - 2.66 * mr_bar,  # 2.66 = 3/1.128; do not tune
            "unpl": center + 2.66 * mr_bar,
            "mr_bar": mr_bar,
            "mr_ucl": 3.268 * mr_bar,
        }

    def xmr_signals(values, lim):
        """Rule 1 (outside limits) and Rule 2 (run of 9 on one side)."""
        x = np.asarray(values, dtype=float)
        outside = (x > lim["unpl"]) | (x < lim["lnpl"])
        side = np.sign(x - lim["center"])
        run = np.zeros(len(x), dtype=bool)
        streak = 0
        for i in range(len(x)):
            if i > 0 and side[i] == side[i - 1] and side[i] != 0:
                streak += 1
            else:
                streak = 1
            if streak >= 9:
                run[i - 8 : i + 1] = True
        return {"outside_limits": outside, "run_of_nine": run}

    return xmr_limits, xmr_signals


@app.cell
def plot_helper(np, plt):
    def plot_xmr(values, lim, signals, baseline_n, title, ax=None):
        """X chart: values, frozen limits, flagged signals, baseline shading."""
        x = np.asarray(values, dtype=float)
        idx = np.arange(len(x))
        if ax is None:
            _, ax = plt.subplots(figsize=(10, 4))
        ax.axvspan(-0.5, baseline_n - 0.5, color="0.92", label="baseline window")
        ax.plot(idx, x, "-o", color="steelblue", ms=4, lw=1, label="value")
        ax.axhline(lim["center"], color="0.3", lw=1.2)
        ax.axhline(lim["unpl"], color="0.3", lw=1, ls="--")
        ax.axhline(lim["lnpl"], color="0.3", lw=1, ls="--")
        flagged = signals["outside_limits"] | signals["run_of_nine"]
        ax.plot(idx[flagged], x[flagged], "o", color="crimson", ms=7,
                mfc="none", mew=2, label="signal")
        ax.set_title(title)
        ax.set_xlabel("observation")
        ax.legend(loc="upper left", fontsize=8)
        return ax

    return (plot_xmr,)


@app.cell
def ex1_header(mo):
    mo.md("""
    ## Example 1 — spike and sustained shift

    A stable process (mean 50, σ 2). We inject a one-point **spike** at
    t=25 and a sustained **shift** starting at t=40. Limits are computed
    from the first 20 points (shaded) and frozen. The spike trips
    Rule 1; the shift — too small to clear the limits point-by-point —
    trips Rule 2 (nine consecutive points on one side of center).

    Drag the slider: even a shift well under one limit-width is caught
    by the run rule, just a little later.
    """)
    return


@app.cell
def ex1_slider(mo):
    shift_slider = mo.ui.slider(1.0, 8.0, step=0.5, value=3.0,
                                label="injected shift size (σ=2)")
    shift_slider
    return (shift_slider,)


@app.cell
def ex1_chart(np, plot_xmr, shift_slider, xmr_limits, xmr_signals):
    ex1_rng = np.random.default_rng(42)
    ex1_baseline_n = 20
    ex1_values = ex1_rng.normal(50, 2, 70)
    ex1_values[25] += 12.0                       # spike → Rule 1
    ex1_values[40:] += shift_slider.value        # sustained shift → Rule 2

    ex1_lim = xmr_limits(ex1_values[:ex1_baseline_n])
    ex1_sig = xmr_signals(ex1_values, ex1_lim)
    ex1_ax = plot_xmr(ex1_values, ex1_lim, ex1_sig, ex1_baseline_n,
                      f"XmR chart — spike at t=25, +{shift_slider.value:g} shift from t=40")
    ex1_ax.figure
    return ex1_lim, ex1_values


@app.cell
def ex2_header(mo):
    mo.md("""
    ## Example 2 — why not `mean ± 3·std(data)`?

    Same data, but limits computed the naive way over the *whole*
    series: the shift inflates the global standard deviation, the limits
    swell to cover the shifted data, and the chart goes blind to its own
    signal. The moving-range limits (red dashed, from Example 1) catch
    it; the global-SD limits (gray dotted) do not. **The global SD is
    contaminated by exactly the signals you are hunting.**
    """)
    return


@app.cell
def ex2_chart(ex1_lim, ex1_values, np, plt):
    ex2_naive_center = ex1_values.mean()
    ex2_naive_sd = ex1_values.std(ddof=1)
    ex2_idx = np.arange(len(ex1_values))

    ex2_fig, ex2_ax = plt.subplots(figsize=(10, 4))
    ex2_ax.plot(ex2_idx, ex1_values, "-o", color="steelblue", ms=4, lw=1)
    for _lvl in (ex1_lim["unpl"], ex1_lim["lnpl"]):
        ex2_ax.axhline(_lvl, color="crimson", lw=1.2, ls="--")
    for _lvl in (ex2_naive_center + 3 * ex2_naive_sd,
                 ex2_naive_center - 3 * ex2_naive_sd):
        ex2_ax.axhline(_lvl, color="0.4", lw=1.2, ls=":")
    ex2_ax.set_title(
        "moving-range limits (red dashed) vs naive mean±3·std (gray dotted)"
    )
    ex2_ax.set_xlabel("observation")
    ex2_fig
    return


@app.cell
def ex3_header(mo):
    mo.md("""
    ## Example 3 — derive the stream first (the most important bit)

    16 weeks of a daily metric with a strong **day-of-week effect**
    (weekend dip ≈ −15) and a real **+6 level shift in week 13**. XmR
    limits assume successive points are exchangeable — raw seasonal data
    is not. On the raw chart the weekend jumps inflate the moving range,
    the limits balloon, and the shift is invisible.

    The fix is not a fancier chart: **chart a derived stream with the
    temporal structure removed**. We subtract each weekday's median —
    computed from the baseline window only and frozen, so anomalies
    can't leak into the seasonal profile — and chart the residuals. The
    shift pops immediately.
    """)
    return


@app.cell
def ex3_data(np, pd):
    ex3_rng = np.random.default_rng(7)
    ex3_n_weeks = 16
    ex3_baseline_days = 8 * 7  # first 8 weeks
    ex3_weekday_effect = np.array([0.0, 2.0, 3.0, 3.0, 2.0, -14.0, -16.0])

    ex3_days = np.arange(ex3_n_weeks * 7)
    ex3_raw = (
        100.0
        + ex3_weekday_effect[ex3_days % 7]
        + ex3_rng.normal(0, 2, len(ex3_days))
    )
    ex3_raw[12 * 7 :] += 6.0  # real level shift in week 13

    # Per-weekday baseline medians — from the frozen baseline window ONLY.
    ex3_df = pd.DataFrame({"day": ex3_days, "value": ex3_raw,
                           "weekday": ex3_days % 7})
    ex3_profile = (
        ex3_df.iloc[:ex3_baseline_days].groupby("weekday")["value"].median()
    )
    ex3_derived = ex3_raw - ex3_profile.to_numpy()[ex3_days % 7]
    return ex3_baseline_days, ex3_derived, ex3_raw


@app.cell
def ex3_chart(
    ex3_baseline_days,
    ex3_derived,
    ex3_raw,
    plot_xmr,
    plt,
    xmr_limits,
    xmr_signals,
):
    ex3_fig, ex3_axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    ex3_lim_raw = xmr_limits(ex3_raw[:ex3_baseline_days])
    ex3_sig_raw = xmr_signals(ex3_raw, ex3_lim_raw)
    plot_xmr(ex3_raw, ex3_lim_raw, ex3_sig_raw, ex3_baseline_days,
             "raw daily values — weekend swings inflate mR̄, shift invisible",
             ax=ex3_axes[0])

    ex3_lim_der = xmr_limits(ex3_derived[:ex3_baseline_days])
    ex3_sig_der = xmr_signals(ex3_derived, ex3_lim_der)
    plot_xmr(ex3_derived, ex3_lim_der, ex3_sig_der, ex3_baseline_days,
             "derived stream (value − frozen weekday median) — shift caught",
             ax=ex3_axes[1])
    ex3_axes[1].set_xlabel("day")
    ex3_fig.tight_layout()
    ex3_fig
    return


@app.cell
def ex4_header(mo):
    mo.md("""
    ## Example 4 — the mR chart sees spread changes for what they are

    The level stays at 50 but the noise **doubles** at t=40. The X chart
    eventually throws Rule-1 signals, but it reads like erratic level
    excursions. The **mR chart** underneath tells the true story: the
    moving ranges jump past their own limit (3.268·mR̄), i.e. *the
    spread changed, not the level*. That distinction matters — a level
    shift and a variance increase have different causes and different
    fixes. Variation has a direct cost of its own; reduce it before
    chasing the mean.
    """)
    return


@app.cell
def ex4_chart(np, plot_xmr, plt, xmr_limits, xmr_signals):
    ex4_rng = np.random.default_rng(3)
    ex4_baseline_n = 20
    ex4_values = np.concatenate([
        ex4_rng.normal(50, 1, 40),
        ex4_rng.normal(50, 2, 30),  # variance doubles, level unchanged
    ])
    ex4_lim = xmr_limits(ex4_values[:ex4_baseline_n])
    ex4_sig = xmr_signals(ex4_values, ex4_lim)

    ex4_fig, ex4_axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    plot_xmr(ex4_values, ex4_lim, ex4_sig, ex4_baseline_n,
             "X chart — erratic excursions, level unchanged", ax=ex4_axes[0])

    ex4_mr = np.abs(np.diff(ex4_values))
    ex4_mr_idx = np.arange(1, len(ex4_values))
    ex4_axes[1].axvspan(-0.5, ex4_baseline_n - 0.5, color="0.92")
    ex4_axes[1].plot(ex4_mr_idx, ex4_mr, "-o", color="steelblue", ms=4, lw=1)
    ex4_axes[1].axhline(ex4_lim["mr_bar"], color="0.3", lw=1.2)
    ex4_axes[1].axhline(ex4_lim["mr_ucl"], color="0.3", lw=1, ls="--")
    ex4_over = ex4_mr > ex4_lim["mr_ucl"]
    ex4_axes[1].plot(ex4_mr_idx[ex4_over], ex4_mr[ex4_over], "o",
                     color="crimson", ms=7, mfc="none", mew=2)
    ex4_axes[1].set_title("mR chart — moving ranges breach 3.268·mR̄: a spread change")
    ex4_axes[1].set_xlabel("observation")
    ex4_fig.tight_layout()
    ex4_fig
    return


@app.cell
def outro(mo):
    mo.md("""
    ## Takeaways

    - Limits from the **moving range of a frozen baseline**, never from
      the global SD, never rolling. 2.66 is not a tuning knob.
    - Two rules by default: outside the limits, or nine in a row on one
      side of center. Every extra rule buys sensitivity with false
      alarms.
    - **Derive a stationary stream before charting** anything seasonal,
      trending, or autocorrelated — this is the most important step in
      any real deployment.
    - Stable process → improve the *system* (reduce variation first);
      don't tamper with individual points. Unstable process → remove
      assignable causes before doing anything else.
    """)
    return


if __name__ == "__main__":
    app.run()
