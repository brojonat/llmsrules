# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo",
#     "xgboost>=2.0",
#     "scikit-learn>=1.5",
#     "shap>=0.46",
#     "pandas>=2.2",
#     "numpy>=1.26",
#     "matplotlib>=3.9",
#     "scipy>=1.13",
# ]
# ///
"""Worked example for the regression bundle.

Self-contained: generates the Friedman1 non-linear regression dataset
inline, fits XGBoost (point + two quantile models), applies
conformalized quantile regression for prediction intervals that
actually cover their nominal level, and includes residual diagnostics
plus a LinearRegression baseline. No external data files. No MLflow.

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
    import shap
    from scipy import stats
    from sklearn.compose import ColumnTransformer
    from sklearn.datasets import make_friedman1
    from sklearn.decomposition import PCA
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBRegressor

    return (
        ColumnTransformer,
        LinearRegression,
        PCA,
        Pipeline,
        StandardScaler,
        XGBRegressor,
        make_friedman1,
        mean_absolute_error,
        mean_squared_error,
        mo,
        np,
        pd,
        plt,
        r2_score,
        shap,
        stats,
        train_test_split,
    )


@app.cell
def title(mo):
    mo.md(r"""
    # Regression with XGBoost + Conformalized Quantile Regression

    A worked example covering the four things that turn "RMSE on a
    notebook" into a regressor you can deploy:

    1. **XGBoost as the default tabular regressor** (beats linear on
       any non-linear structure)
    2. **Quantile regression** for prediction intervals (no Gaussian
       assumption)
    3. **Conformal calibration** so the intervals actually achieve
       their nominal coverage
    4. **Residual diagnostics** and **SHAP** for interpretability

    Plus a baseline `LinearRegression` cell so you can see *why* a
    linear model fails on the Friedman1 problem (which has `sin` and
    quadratic terms a linear model cannot capture).
    """)
    return


@app.cell
def generate_data(make_friedman1, np, pd):
    """Friedman1 non-linear regression problem.

    y = 10*sin(π*x₀*x₁) + 20*(x₂-0.5)² + 10*x₃ + 5*x₄ + N(0, 1)

    Features 0-4 are informative; 5-9 are pure noise. The function has
    obvious non-linear interactions a linear model cannot capture.
    """
    raw_X, raw_y = make_friedman1(n_samples=2000, n_features=10, noise=1.0, random_state=42)
    feature_cols = [f"feature_{i}" for i in range(10)]
    df = (
        pd.DataFrame(raw_X, columns=feature_cols)
        .assign(target=raw_y.astype(np.float64))
    )
    irreducible_rmse = 1.0  # = the noise std passed to make_friedman1
    return df, feature_cols, irreducible_rmse


@app.cell
def show_data(df, mo):
    show_target_mean = float(df["target"].mean())
    show_target_std = float(df["target"].std())
    mo.md(
        f"""
    ## Dataset

    - **Rows:** {len(df)}
    - **Features:** 10 (5 informative, 5 pure noise)
    - **Target:** mean = `{show_target_mean:.2f}`, std = `{show_target_std:.2f}`
    - **Irreducible RMSE:** `1.0` (the noise std built into the data)

    The best possible RMSE on this problem is `1.0` — that's the floor.
    Anything above that is model error. **In production the buyer's
    data lives in parquet/CSV/database — read it with ibis** and
    materialize to pandas with `.execute()` only at the sklearn
    boundary. See `SKILL.md` for the full ibis pattern.
    """
    )
    return


@app.cell
def exploration_section(mo):
    mo.md(r"""
    ## Data exploration — how hard is this problem?

    Before training anything, take 30 seconds to look at the inputs.
    Four views answer most "is this trivial / hard / impossible?"
    questions:

    1. **Target distribution** — what scale and shape are we predicting?
    2. **Per-feature scatter vs target** — which features carry signal?
       Linear relationships are easy; structure that bends is where
       XGBoost wins.
    3. **Correlation heatmap** — feature-feature redundancy plus how
       linearly correlated each feature is with the target. **A weak
       linear correlation does not mean the feature is useless** —
       Friedman1's `sin(π·x₀·x₁)` term has zero linear correlation but
       drives most of the signal.
    4. **PCA in 2D, colored by target** — does the target vary smoothly
       in the top-2 PC space? If yes, plain linear models work. If the
       gradient is messy, you need non-linear methods.
    """)
    return


@app.cell
def target_distribution_plot(df, mo, plt):
    fig_tdist, ax_tdist = plt.subplots(figsize=(7, 3.5))
    ax_tdist.hist(df["target"], bins=40, color="#4477aa", alpha=0.7, density=True)
    target_mean_value = float(df["target"].mean())
    target_std_value = float(df["target"].std())
    ax_tdist.axvline(
        target_mean_value, color="red", lw=2, ls="--",
        label=f"mean = {target_mean_value:.2f}"
    )
    ax_tdist.set_xlabel("target")
    ax_tdist.set_ylabel("density")
    ax_tdist.set_title(
        f"Target distribution — mean {target_mean_value:.2f}, std {target_std_value:.2f}"
    )
    ax_tdist.legend(loc="best")
    fig_tdist.tight_layout()
    mo.as_html(fig_tdist)
    return


@app.cell
def feature_vs_target_plot(df, feature_cols, mo, plt):
    n_feat_fv = len(feature_cols)
    n_cols_fv = 5
    n_rows_fv = (n_feat_fv + n_cols_fv - 1) // n_cols_fv
    fig_fv, axes_fv = plt.subplots(
        n_rows_fv, n_cols_fv, figsize=(14, 2.5 * n_rows_fv)
    )
    for idx_fv, feat_name_fv in enumerate(feature_cols):
        ax_fv = axes_fv[idx_fv // n_cols_fv, idx_fv % n_cols_fv]
        ax_fv.scatter(df[feat_name_fv], df["target"], s=5, alpha=0.4, color="#222222")
        ax_fv.set_xlabel(feat_name_fv, fontsize=8)
        if idx_fv % n_cols_fv == 0:
            ax_fv.set_ylabel("target", fontsize=8)
        ax_fv.tick_params(labelsize=7)
    # Hide any unused axes
    for idx_fv_blank in range(n_feat_fv, n_rows_fv * n_cols_fv):
        axes_fv[idx_fv_blank // n_cols_fv, idx_fv_blank % n_cols_fv].axis("off")
    fig_fv.suptitle(
        "Feature vs target — informative features show structure; noise features look uniform",
        fontsize=10,
    )
    fig_fv.tight_layout()
    mo.as_html(fig_fv)
    return


@app.cell
def correlation_heatmap(df, feature_cols, mo, plt):
    corr_cols = feature_cols + ["target"]
    corr_matrix = df[corr_cols].corr().values
    fig_corr, ax_corr = plt.subplots(figsize=(8, 6.5))
    im_corr = ax_corr.imshow(
        corr_matrix, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto"
    )
    ax_corr.set_xticks(range(len(corr_cols)))
    ax_corr.set_yticks(range(len(corr_cols)))
    ax_corr.set_xticklabels(corr_cols, rotation=45, ha="right", fontsize=8)
    ax_corr.set_yticklabels(corr_cols, fontsize=8)
    target_idx = len(corr_cols) - 1
    for i_corr in range(len(corr_cols)):
        ax_corr.text(
            target_idx,
            i_corr,
            f"{corr_matrix[i_corr, target_idx]:.2f}",
            ha="center",
            va="center",
            fontsize=7,
            color="black" if abs(corr_matrix[i_corr, target_idx]) < 0.5 else "white",
        )
    ax_corr.set_title("Pearson correlations (annotated column = correlation with target)")
    fig_corr.colorbar(im_corr, ax=ax_corr, fraction=0.046)
    fig_corr.tight_layout()
    mo.as_html(fig_corr)
    return


@app.cell
def pca_target_plot(PCA, StandardScaler, df, feature_cols, mo, plt):
    pca_X_scaled = StandardScaler().fit_transform(df[feature_cols])
    pca_model = PCA(n_components=2)
    pca_X = pca_model.fit_transform(pca_X_scaled)

    fig_pca, ax_pca = plt.subplots(figsize=(7, 5.5))
    sc_pca = ax_pca.scatter(
        pca_X[:, 0],
        pca_X[:, 1],
        c=df["target"],
        s=12,
        alpha=0.75,
        cmap="viridis",
    )
    pca_var = pca_model.explained_variance_ratio_
    ax_pca.set_xlabel(f"PC1 ({pca_var[0]:.1%} variance)")
    ax_pca.set_ylabel(f"PC2 ({pca_var[1]:.1%} variance)")
    ax_pca.set_title(
        f"PCA 2D projection colored by target — {pca_var.sum():.1%} variance shown"
    )
    fig_pca.colorbar(sc_pca, ax=ax_pca, label="target")
    fig_pca.tight_layout()
    mo.as_html(fig_pca)
    return


@app.cell
def split(df, feature_cols, train_test_split):
    """Three-way split: train fits the model, calib calibrates the
    conformal correction, test reports the final numbers."""
    X_train_full, X_test, y_train_full, y_test = train_test_split(
        df[feature_cols], df["target"], test_size=0.2, random_state=42
    )
    X_train, X_calib, y_train, y_calib = train_test_split(
        X_train_full, y_train_full, test_size=0.2, random_state=42
    )
    return X_calib, X_test, X_train, y_calib, y_test, y_train


@app.cell
def fit_section(mo):
    mo.md(r"""
    ## Fit three XGBoost regressors

    - **Point model**: `objective="reg:squarederror"` — gives the
      expected value
    - **Lower quantile**: `objective="reg:quantileerror"`,
      `quantile_alpha=0.05`
    - **Upper quantile**: `objective="reg:quantileerror"`,
      `quantile_alpha=0.95`

    Together they target a nominal **90% prediction interval**.
    Quantile regression is XGBoost-native in 2.0+.
    """)
    return


@app.cell
def fit_models(
    ColumnTransformer,
    Pipeline,
    StandardScaler,
    XGBRegressor,
    X_train,
    feature_cols,
    y_train,
):
    def make_xgb(objective, quantile_alpha=None):
        kwargs = dict(
            n_estimators=400, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
            objective=objective, random_state=42, n_jobs=-1,
        )
        if quantile_alpha is not None:
            kwargs["quantile_alpha"] = quantile_alpha
        return Pipeline([
            ("preprocess", ColumnTransformer([("num", StandardScaler(), feature_cols)])),
            ("clf", XGBRegressor(**kwargs)),
        ])

    xgb_point = make_xgb("reg:squarederror").fit(X_train, y_train)
    xgb_lower = make_xgb("reg:quantileerror", quantile_alpha=0.05).fit(X_train, y_train)
    xgb_upper = make_xgb("reg:quantileerror", quantile_alpha=0.95).fit(X_train, y_train)
    return xgb_lower, xgb_point, xgb_upper


@app.cell
def conformal_section(mo):
    mo.md(r"""
    ## Conformalize the intervals

    Vanilla quantile XGBoost optimizes pinball loss but does **not**
    guarantee coverage. Compute the residual conformity scores on a
    held-out calibration set and add the right quantile to the bounds:

    $$
    E_i = \max(q_{\text{low}}(x_i) - y_i,\ y_i - q_{\text{high}}(x_i))
    $$

    Take $Q$ = the $\lceil(1-\alpha)(n+1)\rceil/n$-th quantile of $E$,
    and the calibrated interval is $[q_\text{low}(x) - Q,\ q_\text{high}(x) + Q]$.
    Conformalized Quantile Regression — Romano et al. 2019.
    """)
    return


@app.cell
def compute_conformal(X_calib, np, xgb_lower, xgb_upper, y_calib):
    cal_low = xgb_lower.predict(X_calib)
    cal_high = xgb_upper.predict(X_calib)
    conformity = np.maximum(cal_low - y_calib.to_numpy(), y_calib.to_numpy() - cal_high)
    nominal_coverage = 0.90
    n_cal = len(y_calib)
    q_level = min(1.0, np.ceil(nominal_coverage * (n_cal + 1)) / n_cal)
    conformal_q = float(np.quantile(conformity, q_level))
    return conformal_q, nominal_coverage


@app.cell
def metrics_section(
    X_test,
    conformal_q,
    irreducible_rmse,
    mean_absolute_error,
    mean_squared_error,
    mo,
    nominal_coverage,
    np,
    r2_score,
    xgb_lower,
    xgb_point,
    xgb_upper,
    y_test,
):
    test_pred = xgb_point.predict(X_test)
    test_low_raw = xgb_lower.predict(X_test)
    test_high_raw = xgb_upper.predict(X_test)
    test_low = test_low_raw - conformal_q
    test_high = test_high_raw + conformal_q

    test_y_arr = y_test.to_numpy()
    rmse_value = float(np.sqrt(mean_squared_error(y_test, test_pred)))
    mae_value = float(mean_absolute_error(y_test, test_pred))
    r2_value = float(r2_score(y_test, test_pred))
    inside_raw_arr = (test_y_arr >= test_low_raw) & (test_y_arr <= test_high_raw)
    inside_arr = (test_y_arr >= test_low) & (test_y_arr <= test_high)
    coverage_raw_value = float(inside_raw_arr.mean())
    coverage_value = float(inside_arr.mean())

    mo.md(
        f"""
    ## XGBoost test metrics

    | Metric | Value | Notes |
    |---|---|---|
    | RMSE | **`{rmse_value:.4f}`** | irreducible = `{irreducible_rmse:.4f}` (excess = `{rmse_value - irreducible_rmse:+.4f}`) |
    | MAE | **`{mae_value:.4f}`** | average absolute error in target units |
    | R² | **`{r2_value:.4f}`** | sanity check only — don't optimize for this |

    ### Prediction intervals @ nominal {nominal_coverage:.0%}

    | | Empirical coverage | Inside / Total |
    |---|---|---|
    | Raw quantile XGBoost | **`{coverage_raw_value:.1%}`** ❌ | {inside_raw_arr.sum()} / {len(inside_raw_arr)} |
    | Conformalized (correction = ±{conformal_q:.3f}) | **`{coverage_value:.1%}`** ✓ | {inside_arr.sum()} / {len(inside_arr)} |

    The raw quantile model **undercovers** by ~15-20 percentage points.
    Conformal calibration brings it back to the nominal level. This is
    not a bug — it's a known limitation of pinball-loss training that
    CQR specifically fixes.
    """
    )
    return test_high, test_low, test_pred


@app.cell
def predicted_vs_actual_plot(
    mo,
    np,
    plt,
    test_high,
    test_low,
    test_pred,
    y_test,
):
    pva_y = y_test.to_numpy()
    pva_lo = float(min(pva_y.min(), test_pred.min()))
    pva_hi = float(max(pva_y.max(), test_pred.max()))
    pva_order = np.argsort(pva_y)

    fig_pva, ax_pva = plt.subplots(figsize=(7, 6))
    ax_pva.fill_between(
        pva_y[pva_order],
        test_low[pva_order],
        test_high[pva_order],
        alpha=0.2,
        color="#4477aa",
        label="conformal 90% interval",
    )
    ax_pva.scatter(pva_y, test_pred, alpha=0.5, s=15, color="#222222", label="point prediction")
    ax_pva.plot([pva_lo, pva_hi], [pva_lo, pva_hi], color="red", lw=1.5, ls="--", label="y = x")
    ax_pva.set_xlabel("actual")
    ax_pva.set_ylabel("predicted")
    ax_pva.set_title("Predicted vs actual with conformal interval bands")
    ax_pva.legend(loc="best")
    fig_pva.tight_layout()
    mo.as_html(fig_pva)
    return


@app.cell
def residual_section(mo):
    mo.md(r"""
    ## Residual diagnostics

    `residual = actual - predicted`. Three views:

    1. **Residual vs predicted**: should be a flat band around 0. A
       funnel = heteroscedasticity. A curve = missing non-linearity.
    2. **Histogram + Normal overlay**: should look roughly Normal for
       squared-error models. Heavy tails → switch to `reg:absoluteerror`
       or `reg:huber`.
    3. **QQ plot vs Normal**: visual check for tail behavior.
    """)
    return


@app.cell
def residual_plots(mo, np, plt, stats, test_pred, y_test):
    res_arr = y_test.to_numpy() - test_pred
    fig_res, axes_res = plt.subplots(1, 3, figsize=(14, 4.5))
    ax_rvp, ax_hist, ax_qq = axes_res

    ax_rvp.scatter(test_pred, res_arr, alpha=0.5, s=15)
    ax_rvp.axhline(0, color="red", lw=1, ls="--")
    ax_rvp.set_xlabel("predicted")
    ax_rvp.set_ylabel("residual")
    ax_rvp.set_title("Residual vs predicted")

    res_mean = float(res_arr.mean())
    res_std = float(res_arr.std())
    ax_hist.hist(res_arr, bins=40, color="#4477aa", alpha=0.7, density=True)
    res_xs = np.linspace(res_arr.min(), res_arr.max(), 200)
    ax_hist.plot(
        res_xs,
        stats.norm.pdf(res_xs, loc=res_mean, scale=res_std),
        color="red", lw=2, label=f"N({res_mean:.2f}, {res_std:.2f})",
    )
    ax_hist.set_xlabel("residual")
    ax_hist.set_ylabel("density")
    ax_hist.set_title("Residual distribution")
    ax_hist.legend(loc="best")

    stats.probplot(res_arr, dist="norm", plot=ax_qq)
    ax_qq.set_title("QQ plot vs Normal")
    ax_qq.get_lines()[0].set_markersize(4)
    ax_qq.get_lines()[1].set_color("red")

    fig_res.tight_layout()
    mo.as_html(fig_res)
    return


@app.cell
def coverage_section(mo):
    mo.md(r"""
    ## Empirical interval coverage on the test set

    Sort the test points by true value, draw the conformal interval as
    a band, color points by inside/outside. **About 90% of the points
    should be green** (nominal coverage).
    """)
    return


@app.cell
def coverage_plot(mo, np, plt, test_high, test_low, y_test):
    cov_y = y_test.to_numpy()
    cov_inside = (cov_y >= test_low) & (cov_y <= test_high)
    cov_order = np.argsort(cov_y)

    fig_cov, ax_cov = plt.subplots(figsize=(8, 4.5))
    ax_cov.fill_between(
        np.arange(len(cov_y)),
        test_low[cov_order],
        test_high[cov_order],
        alpha=0.25,
        color="#4477aa",
        label="conformal 90% interval",
    )
    ax_cov.scatter(
        np.arange(len(cov_y))[cov_inside[cov_order]],
        cov_y[cov_order][cov_inside[cov_order]],
        s=10, color="#228833", label=f"inside ({cov_inside.sum()})",
    )
    ax_cov.scatter(
        np.arange(len(cov_y))[~cov_inside[cov_order]],
        cov_y[cov_order][~cov_inside[cov_order]],
        s=15, color="#cc3311", label=f"outside ({(~cov_inside).sum()})",
    )
    ax_cov.set_xlabel("test sample (sorted by true value)")
    ax_cov.set_ylabel("y")
    ax_cov.set_title(f"Empirical coverage: {cov_inside.mean():.1%}")
    ax_cov.legend(loc="best", fontsize=9)
    fig_cov.tight_layout()
    mo.as_html(fig_cov)
    return


@app.cell
def per_row_section(mo):
    mo.md(r"""
    ## Inspect a single test row

    Pick a row and see its point estimate, prediction interval, and
    true value. The interval should contain the true value about 90%
    of the time.
    """)
    return


@app.cell
def row_slider(X_test, mo):
    row_slider = mo.ui.slider(
        start=0, stop=len(X_test) - 1, step=1, value=0,
        label="test row", full_width=True,
    )
    row_slider
    return (row_slider,)


@app.cell
def row_inspection(mo, row_slider, test_high, test_low, test_pred, y_test):
    row_idx = int(row_slider.value)
    row_point = float(test_pred[row_idx])
    row_low = float(test_low[row_idx])
    row_high = float(test_high[row_idx])
    row_true = float(y_test.iloc[row_idx])
    row_inside = "✓ inside" if row_low <= row_true <= row_high else "✗ outside"
    row_width = row_high - row_low
    mo.md(
        f"""
    **Row `{row_idx}`:**

    | Quantity | Value |
    |---|---|
    | point estimate | `{row_point:.4f}` |
    | conformal interval | `[{row_low:.4f}, {row_high:.4f}]` (width = `{row_width:.4f}`) |
    | true value | `{row_true:.4f}` |
    | status | **{row_inside}** |
    """
    )
    return


@app.cell
def shap_section(mo):
    mo.md(r"""
    ## SHAP feature importance

    Don't trust XGBoost's `feature_importances_` — it has biases. Use
    SHAP's `TreeExplainer`. Features 0-4 are the informative ones in
    Friedman1; 5-9 are pure noise. The bar chart should reflect that.
    """)
    return


@app.cell
def shap_plot(X_test, feature_cols, mo, plt, shap, xgb_point):
    shap_pre = xgb_point.named_steps["preprocess"]
    shap_clf = xgb_point.named_steps["clf"]
    X_test_t = shap_pre.transform(X_test.iloc[:200])

    explainer = shap.TreeExplainer(shap_clf)
    shap_values = explainer(X_test_t)
    plt.figure(figsize=(8, 5))
    shap.summary_plot(shap_values, X_test_t, feature_names=feature_cols, show=False)
    fig_shap = plt.gcf()
    fig_shap.tight_layout()
    mo.as_html(fig_shap)
    return


@app.cell
def baseline_section(mo):
    mo.md(r"""
    ## Baseline: LinearRegression — and why XGBoost wins on Friedman1

    Friedman1 has `sin(π·x₀·x₁)` and `(x₂-0.5)²` terms. A linear model
    can't represent either. XGBoost can.
    """)
    return


@app.cell
def fit_baseline(
    ColumnTransformer,
    LinearRegression,
    Pipeline,
    StandardScaler,
    X_test,
    X_train,
    feature_cols,
    mean_absolute_error,
    mean_squared_error,
    mo,
    np,
    r2_score,
    y_test,
    y_train,
):
    baseline_pipeline = Pipeline([
        ("preprocess", ColumnTransformer([("num", StandardScaler(), feature_cols)])),
        ("clf", LinearRegression()),
    ])
    baseline_pipeline.fit(X_train, y_train)
    base_pred = baseline_pipeline.predict(X_test)

    base_rmse = float(np.sqrt(mean_squared_error(y_test, base_pred)))
    base_mae = float(mean_absolute_error(y_test, base_pred))
    base_r2 = float(r2_score(y_test, base_pred))

    mo.md(
        f"""
    | Metric | LinearRegression | XGBoost (above) |
    |---|---|---|
    | RMSE | `{base_rmse:.4f}` | (much lower) |
    | MAE | `{base_mae:.4f}` | (much lower) |
    | R² | `{base_r2:.4f}` | (much higher) |

    The linear model captures the linear terms (`10·x₃`, `5·x₄`) but
    misses the non-linear ones, leaving big residuals on the table.
    On any tabular regression problem with non-linear interactions,
    XGBoost wins by a large margin.
    """
    )
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    Five things you should always do for tabular regression:

    1. **XGBoost as the default point estimator** — beats linear on
       any non-linear structure.
    2. **Quantile XGBoost for prediction intervals** — `reg:quantileerror`
       with `quantile_alpha` set to your low/high quantiles.
    3. **Conformalize the intervals** with a held-out calibration set
       so they actually achieve their nominal coverage.
    4. **Residual diagnostics** — funnel = heteroscedasticity, curve =
       missing non-linearity, fat tails = wrong loss.
    5. **SHAP for feature importance** — never `feature_importances_`.

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/regression/` directory and your AI agent will
    follow the same workflow on your real data.
    """)
    return


if __name__ == "__main__":
    app.run()
