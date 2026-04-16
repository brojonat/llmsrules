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
# ]
# ///
"""Worked example for the binary-classification bundle.

Self-contained: generates its own synthetic data, fits XGBoost with all
the production essentials, and lets you interactively explore the
threshold tradeoff. No external data files. No MLflow. No datagen.

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
    from sklearn.calibration import calibration_curve
    from sklearn.compose import ColumnTransformer
    from sklearn.datasets import make_classification
    from sklearn.decomposition import PCA
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        f1_score,
        roc_auc_score,
    )
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBClassifier

    return (
        ColumnTransformer,
        LogisticRegression,
        PCA,
        Pipeline,
        StandardScaler,
        XGBClassifier,
        average_precision_score,
        brier_score_loss,
        calibration_curve,
        f1_score,
        make_classification,
        mo,
        np,
        pd,
        plt,
        roc_auc_score,
        shap,
        train_test_split,
    )


@app.cell
def title(mo):
    mo.md(r"""
    # Binary Classification with XGBoost (Done Right)

    A worked example covering the four things that turn "ROC-AUC on a
    notebook" into a model you can deploy:

    1. **`scale_pos_weight`** for class imbalance (no resampling)
    2. **Threshold tuning** for the metric your business actually cares about
    3. **Calibration verification** — Brier score + reliability diagram
    4. **SHAP** for feature importance (not the biased built-in)

    Plus a baseline `LogisticRegression` cell so you can see *why* XGBoost
    wins on this kind of problem.
    """)
    return


@app.cell
def generate_data(make_classification, np, pd):
    """Synthetic 15%-positive imbalanced binary classification problem.

    In a real bundle the buyer would read parquet via ibis (see SKILL.md).
    Here the data is generated in memory, so we use pandas via a single
    chained operation — same fluent style, no detour through a temp file.
    """
    raw_X, raw_y = make_classification(
        n_samples=2000,
        n_features=12,
        n_informative=6,
        n_redundant=2,
        n_classes=2,
        weights=[0.85, 0.15],  # 15% positive
        class_sep=0.9,
        random_state=42,
    )
    feature_cols = [f"feature_{i}" for i in range(12)]
    df = (
        pd.DataFrame(raw_X, columns=feature_cols)
        .assign(target=raw_y.astype(np.int8))
    )
    return df, feature_cols


@app.cell
def show_data(df, mo):
    show_pos_rate = float(df["target"].mean())
    show_n_pos = int(df["target"].sum())
    mo.md(
        f"""
    ## Dataset

    - **Rows:** {len(df)}
    - **Features:** 12 (6 informative, 2 redundant, 4 noise)
    - **Positive class:** {show_n_pos} / {len(df)} (**{show_pos_rate:.1%}**) — realistic imbalance

    This is the kind of split you see in churn prediction, fraud detection,
    conversion modeling, etc. **In production the buyer's data lives in
    parquet/CSV/database — read it with ibis** (`ibis.duckdb.connect().read_parquet(...)`)
    and materialize to pandas with `.execute()` only at the sklearn boundary.
    See `SKILL.md` for the full ibis pattern.
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

    1. **Class balance** — am I about to train a model on a 99/1 split?
    2. **Per-feature distributions by class** — which features actually
       carry signal vs which are noise?
    3. **Correlation heatmap** — are features redundant? Does any single
       feature have a strong linear relationship to the target?
    4. **PCA in 2D** — are the classes separable with just two linear
       combinations of features? If yes, the problem is trivial. If
       not, you'll need a non-linear model (like XGBoost).
    """)
    return


@app.cell
def class_balance_plot(df, mo, plt):
    bal_counts = df["target"].value_counts().sort_index()
    fig_bal, ax_bal = plt.subplots(figsize=(5, 3.5))
    bars_bal = ax_bal.bar(
        ["class 0 (negative)", "class 1 (positive)"],
        bal_counts.values,
        color=["#4477aa", "#cc3311"],
    )
    for bar_b, val_b in zip(bars_bal, bal_counts.values):
        ax_bal.text(
            bar_b.get_x() + bar_b.get_width() / 2,
            val_b,
            str(int(val_b)),
            ha="center",
            va="bottom",
        )
    ax_bal.set_ylabel("count")
    ax_bal.set_title(
        f"Class balance — {bal_counts[1] / bal_counts.sum():.1%} positive"
    )
    fig_bal.tight_layout()
    mo.as_html(fig_bal)
    return


@app.cell
def feature_distributions_plot(df, feature_cols, mo, plt):
    n_feat_dist = len(feature_cols)
    n_cols_dist = 4
    n_rows_dist = (n_feat_dist + n_cols_dist - 1) // n_cols_dist
    fig_dist, axes_dist = plt.subplots(
        n_rows_dist, n_cols_dist, figsize=(12, 2.2 * n_rows_dist)
    )
    pos_dist = df["target"] == 1
    for idx_dist, feat_name in enumerate(feature_cols):
        ax_d = axes_dist[idx_dist // n_cols_dist, idx_dist % n_cols_dist]
        ax_d.hist(
            df.loc[~pos_dist, feat_name],
            bins=30,
            alpha=0.55,
            label="0",
            color="#4477aa",
            density=True,
        )
        ax_d.hist(
            df.loc[pos_dist, feat_name],
            bins=30,
            alpha=0.55,
            label="1",
            color="#cc3311",
            density=True,
        )
        ax_d.set_title(feat_name, fontsize=9)
        ax_d.tick_params(labelsize=7)
        if idx_dist == 0:
            ax_d.legend(fontsize=7, title="class")
    # blank out unused axes
    for idx_blank in range(n_feat_dist, n_rows_dist * n_cols_dist):
        axes_dist[idx_blank // n_cols_dist, idx_blank % n_cols_dist].axis("off")
    fig_dist.suptitle(
        "Feature distributions by class — overlapping = uninformative, separated = signal",
        fontsize=10,
    )
    fig_dist.tight_layout()
    mo.as_html(fig_dist)
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
    # Annotate the target row + column with the correlation values
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
def pca_class_plot(PCA, StandardScaler, df, feature_cols, mo, plt):
    pca_X_scaled = StandardScaler().fit_transform(df[feature_cols])
    pca_model = PCA(n_components=2)
    pca_X = pca_model.fit_transform(pca_X_scaled)

    fig_pca, ax_pca = plt.subplots(figsize=(7, 5.5))
    pos_pca = df["target"].to_numpy() == 1
    ax_pca.scatter(
        pca_X[~pos_pca, 0],
        pca_X[~pos_pca, 1],
        s=10,
        alpha=0.5,
        color="#4477aa",
        label="class 0",
    )
    ax_pca.scatter(
        pca_X[pos_pca, 0],
        pca_X[pos_pca, 1],
        s=10,
        alpha=0.7,
        color="#cc3311",
        label="class 1",
    )
    pca_var = pca_model.explained_variance_ratio_
    ax_pca.set_xlabel(f"PC1 ({pca_var[0]:.1%} variance)")
    ax_pca.set_ylabel(f"PC2 ({pca_var[1]:.1%} variance)")
    ax_pca.set_title(
        f"PCA 2D projection — {pca_var.sum():.1%} of variance shown"
    )
    ax_pca.legend(loc="best")
    fig_pca.tight_layout()
    mo.as_html(fig_pca)
    return


@app.cell
def split(df, feature_cols, train_test_split):
    """Split into train/test in a single chained expression."""
    X_train, X_test, y_train, y_test = train_test_split(
        df[feature_cols],
        df["target"].astype(int),
        test_size=0.2,
        random_state=42,
        stratify=df["target"],
    )
    return X_test, X_train, y_test, y_train


@app.cell
def imbalance_section(mo):
    mo.md(r"""
    ## 1. Class imbalance via `scale_pos_weight`

    XGBoost rescales the gradient contribution of positive examples so they
    matter as much as the negatives — without resampling.

    $$\text{scale\_pos\_weight} = \frac{n_\text{negative}}{n_\text{positive}}$$
    """)
    return


@app.cell
def compute_spw(mo, y_train):
    n_pos_train = int(y_train.sum())
    n_neg_train = int(len(y_train) - n_pos_train)
    scale_pos_weight = n_neg_train / n_pos_train
    mo.md(
        f"""
    - `n_positive_train` = {n_pos_train}
    - `n_negative_train` = {n_neg_train}
    - **`scale_pos_weight` = {scale_pos_weight:.3f}**
    """
    )
    return (scale_pos_weight,)


@app.cell
def fit_xgb(
    ColumnTransformer,
    Pipeline,
    StandardScaler,
    XGBClassifier,
    X_train,
    feature_cols,
    scale_pos_weight,
    y_train,
):
    """Fit XGBoost in a sklearn Pipeline so preprocessing travels with the model."""
    xgb_pipeline = Pipeline(
        [
            ("preprocess", ColumnTransformer([("num", StandardScaler(), feature_cols)])),
            (
                "clf",
                XGBClassifier(
                    n_estimators=300,
                    max_depth=4,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    reg_lambda=1.0,
                    scale_pos_weight=scale_pos_weight,
                    objective="binary:logistic",
                    eval_metric="logloss",
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    xgb_pipeline.fit(X_train, y_train)
    return (xgb_pipeline,)


@app.cell
def xgb_metrics(
    X_test,
    average_precision_score,
    brier_score_loss,
    f1_score,
    mo,
    roc_auc_score,
    xgb_pipeline,
    y_test,
):
    xgb_proba = xgb_pipeline.predict_proba(X_test)[:, 1]
    xgb_pred_default = (xgb_proba >= 0.5).astype(int)

    xgb_roc_auc = float(roc_auc_score(y_test, xgb_proba))
    xgb_pr_auc = float(average_precision_score(y_test, xgb_proba))
    xgb_brier = float(brier_score_loss(y_test, xgb_proba))
    xgb_f1 = float(f1_score(y_test, xgb_pred_default))

    test_pos_rate = float(y_test.mean())
    mo.md(
        f"""
    ## XGBoost test metrics (default threshold = 0.5)

    | Metric | Value | Notes |
    |---|---|---|
    | ROC-AUC | **{xgb_roc_auc:.4f}** | Discrimination quality |
    | PR-AUC | **{xgb_pr_auc:.4f}** | Baseline = {test_pos_rate:.4f} (positive rate). Honest metric for imbalanced data. |
    | Brier score | **{xgb_brier:.4f}** | Lower = better calibrated |
    | F1 @ 0.5 | **{xgb_f1:.4f}** | About to be improved by threshold tuning |
    """
    )
    return (xgb_proba,)


@app.cell
def threshold_section(mo):
    mo.md(r"""
    ## 2. Threshold tuning — 0.5 is rarely the right answer

    XGBoost (like every probabilistic classifier) defaults to a 0.5 cutoff.
    **Almost always wrong.** The right threshold depends on the relative
    cost of false positives vs false negatives, which is a business
    decision, not a modeling one.

    Use the slider below to see precision, recall, and F1 vary with the
    threshold. The marker shows the F1-optimal threshold.
    """)
    return


@app.cell
def threshold_curves(np, xgb_proba, y_test):
    """Compute precision/recall/F1 across all thresholds (vectorized)."""
    sweep_thresholds = np.linspace(0.01, 0.99, 99)
    sweep_precisions = []
    sweep_recalls = []
    sweep_f1s = []
    sweep_y_arr = y_test.to_numpy()
    for t in sweep_thresholds:
        sweep_pred = (xgb_proba >= t).astype(int)
        sweep_tp = int(((sweep_pred == 1) & (sweep_y_arr == 1)).sum())
        sweep_fp = int(((sweep_pred == 1) & (sweep_y_arr == 0)).sum())
        sweep_fn = int(((sweep_pred == 0) & (sweep_y_arr == 1)).sum())
        prec = sweep_tp / (sweep_tp + sweep_fp) if (sweep_tp + sweep_fp) > 0 else 0.0
        rec = sweep_tp / (sweep_tp + sweep_fn) if (sweep_tp + sweep_fn) > 0 else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        sweep_precisions.append(prec)
        sweep_recalls.append(rec)
        sweep_f1s.append(f1)
    sweep_precisions = np.array(sweep_precisions)
    sweep_recalls = np.array(sweep_recalls)
    sweep_f1s = np.array(sweep_f1s)
    best_f1_idx = int(np.argmax(sweep_f1s))
    best_f1_threshold = float(sweep_thresholds[best_f1_idx])
    return (
        best_f1_threshold,
        sweep_f1s,
        sweep_precisions,
        sweep_recalls,
        sweep_thresholds,
    )


@app.cell
def threshold_slider(best_f1_threshold, mo):
    threshold_ui = mo.ui.slider(
        start=0.01,
        stop=0.99,
        step=0.01,
        value=best_f1_threshold,
        label=f"decision threshold (F1-optimal = {best_f1_threshold:.2f})",
        full_width=True,
    )
    threshold_ui
    return (threshold_ui,)


@app.cell
def threshold_plot(
    best_f1_threshold,
    mo,
    plt,
    sweep_f1s,
    sweep_precisions,
    sweep_recalls,
    sweep_thresholds,
    threshold_ui,
):
    fig_thresh, ax_thresh = plt.subplots(figsize=(8, 4.5))
    ax_thresh.plot(sweep_thresholds, sweep_precisions, lw=2, label="precision")
    ax_thresh.plot(sweep_thresholds, sweep_recalls, lw=2, label="recall")
    ax_thresh.plot(sweep_thresholds, sweep_f1s, lw=2, label="F1")
    ax_thresh.axvline(0.5, color="grey", lw=1, ls=":", label="default 0.5")
    ax_thresh.axvline(
        best_f1_threshold, color="red", lw=1, ls="--", label=f"best F1 = {best_f1_threshold:.2f}"
    )
    ax_thresh.axvline(
        threshold_ui.value,
        color="black",
        lw=2,
        alpha=0.7,
        label=f"slider = {threshold_ui.value:.2f}",
    )
    ax_thresh.set_xlabel("decision threshold")
    ax_thresh.set_ylabel("metric")
    ax_thresh.set_title("Precision / Recall / F1 vs threshold")
    ax_thresh.set_xlim(0, 1)
    ax_thresh.set_ylim(0, 1.05)
    ax_thresh.legend(loc="best", fontsize=9)
    fig_thresh.tight_layout()
    mo.as_html(fig_thresh)
    return


@app.cell
def threshold_metrics_at_slider(mo, threshold_ui, xgb_proba, y_test):
    cur_threshold = float(threshold_ui.value)
    cur_pred = (xgb_proba >= cur_threshold).astype(int)
    cur_y_arr = y_test.to_numpy()
    cur_tp = int(((cur_pred == 1) & (cur_y_arr == 1)).sum())
    cur_fp = int(((cur_pred == 1) & (cur_y_arr == 0)).sum())
    cur_tn = int(((cur_pred == 0) & (cur_y_arr == 0)).sum())
    cur_fn = int(((cur_pred == 0) & (cur_y_arr == 1)).sum())
    cur_prec = cur_tp / (cur_tp + cur_fp) if (cur_tp + cur_fp) > 0 else 0.0
    cur_rec = cur_tp / (cur_tp + cur_fn) if (cur_tp + cur_fn) > 0 else 0.0
    cur_f1 = 2 * cur_prec * cur_rec / (cur_prec + cur_rec) if (cur_prec + cur_rec) > 0 else 0.0
    mo.md(
        f"""
    **At threshold = {cur_threshold:.2f}:**

    | | Pred 0 | Pred 1 |
    |---|---|---|
    | **True 0** | {cur_tn} | {cur_fp} |
    | **True 1** | {cur_fn} | {cur_tp} |

    - precision = `{cur_prec:.3f}`
    - recall = `{cur_rec:.3f}`
    - F1 = `{cur_f1:.3f}`
    """
    )
    return


@app.cell
def calibration_section(mo):
    mo.md(r"""
    ## 3. Calibration — does P=0.8 actually mean 80%?

    A model can have great ROC-AUC and still be miscalibrated. The
    **reliability diagram** bins predictions by probability and plots
    predicted vs observed. Should hug the diagonal.

    The **Brier score** is the mean squared error between predicted
    probabilities and binary outcomes. Lower = better calibrated. Below ~0.1
    is usually fine.
    """)
    return


@app.cell
def calibration_diagram(calibration_curve, mo, plt, xgb_proba, y_test):
    cal_frac, cal_pred_mean = calibration_curve(
        y_test, xgb_proba, n_bins=10, strategy="quantile"
    )
    fig_cal, axes_cal = plt.subplots(1, 2, figsize=(11, 4.5))
    ax_rel, ax_hist = axes_cal

    ax_rel.plot([0, 1], [0, 1], color="grey", ls="--", lw=1, label="perfect")
    ax_rel.plot(cal_pred_mean, cal_frac, marker="o", lw=2, label="XGBoost")
    ax_rel.set_xlabel("mean predicted P(positive)")
    ax_rel.set_ylabel("observed fraction positive")
    ax_rel.set_title("Reliability diagram")
    ax_rel.set_xlim(0, 1)
    ax_rel.set_ylim(0, 1)
    ax_rel.legend(loc="best")

    ax_hist.hist(xgb_proba, bins=30, color="#4477aa", alpha=0.7)
    ax_hist.set_xlabel("predicted P(positive)")
    ax_hist.set_ylabel("count")
    ax_hist.set_title("Predicted probability histogram")

    fig_cal.tight_layout()
    mo.as_html(fig_cal)
    return


@app.cell
def shap_section(mo):
    mo.md(r"""
    ## 4. SHAP feature importance

    Don't use XGBoost's built-in `feature_importances_` — it has biases
    toward high-cardinality features. Use SHAP's `TreeExplainer` instead;
    it's fast for tree models and produces both global and local
    explanations.
    """)
    return


@app.cell
def shap_summary_plot(X_test, feature_cols, mo, plt, shap, xgb_pipeline):
    """SHAP beeswarm on a 200-sample subset (fast for trees)."""
    shap_preprocessor = xgb_pipeline.named_steps["preprocess"]
    shap_clf = xgb_pipeline.named_steps["clf"]
    X_test_t = shap_preprocessor.transform(X_test.iloc[:200])

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
    ## Baseline: LogisticRegression — and why XGBoost wins

    For comparison, here's a regularized logistic regression on the same
    data. Same Pipeline shape, same `scale_pos_weight` semantics (via
    `class_weight="balanced"`). XGBoost should outperform on every metric.
    """)
    return


@app.cell
def fit_baseline(
    ColumnTransformer,
    LogisticRegression,
    Pipeline,
    StandardScaler,
    X_test,
    X_train,
    average_precision_score,
    brier_score_loss,
    f1_score,
    feature_cols,
    mo,
    roc_auc_score,
    y_test,
    y_train,
):
    baseline_pipeline = Pipeline(
        [
            ("preprocess", ColumnTransformer([("num", StandardScaler(), feature_cols)])),
            ("clf", LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)),
        ]
    )
    baseline_pipeline.fit(X_train, y_train)
    base_proba = baseline_pipeline.predict_proba(X_test)[:, 1]
    base_pred = (base_proba >= 0.5).astype(int)

    base_roc = float(roc_auc_score(y_test, base_proba))
    base_pr = float(average_precision_score(y_test, base_proba))
    base_brier = float(brier_score_loss(y_test, base_proba))
    base_f1 = float(f1_score(y_test, base_pred))

    mo.md(
        f"""
    | Metric | LogisticRegression | (XGBoost was…) |
    |---|---|---|
    | ROC-AUC | `{base_roc:.4f}` | (above) |
    | PR-AUC | `{base_pr:.4f}` | |
    | Brier score | `{base_brier:.4f}` | |
    | F1 @ 0.5 | `{base_f1:.4f}` | |

    XGBoost captures the non-linear interactions in the synthetic data;
    the linear model can't. On a *very* small dataset (< 200 rows) or one
    with truly linear structure, the gap closes — but for most real
    tabular problems with > 1000 rows, XGBoost wins.
    """
    )
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    The four things you should always do for binary classification on tabular data:

    1. **`scale_pos_weight = n_neg / n_pos`** — class imbalance handled.
    2. **Tune the threshold** for the metric your business cares about. 0.5 is a default, not a recommendation.
    3. **Check calibration** with Brier score + reliability diagram.
    4. **SHAP for feature importance** — never `feature_importances_`.

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/binary-classification/` directory and your AI agent
    will follow the same workflow on your real data.
    """)
    return


if __name__ == "__main__":
    app.run()
