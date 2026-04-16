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
"""Worked example for the multiclass-classification bundle.

Self-contained: generates an imbalanced 5-class synthetic dataset,
fits XGBoost two ways (without and with sample_weight), and shows
how sample_weight rescues minority-class F1 even though overall
accuracy barely moves. No external data files. No MLflow.

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
    from sklearn.compose import ColumnTransformer
    from sklearn.datasets import make_classification
    from sklearn.decomposition import PCA
    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        f1_score,
        precision_recall_fscore_support,
        top_k_accuracy_score,
    )
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.utils.class_weight import compute_sample_weight
    from xgboost import XGBClassifier

    return (
        ColumnTransformer,
        Pipeline,
        StandardScaler,
        XGBClassifier,
        accuracy_score,
        compute_sample_weight,
        confusion_matrix,
        f1_score,
        make_classification,
        mo,
        np,
        pd,
        plt,
        precision_recall_fscore_support,
        shap,
        top_k_accuracy_score,
        train_test_split,
    )


@app.cell
def title(mo):
    mo.md(r"""
    # Multiclass Classification with XGBoost (Done Right)

    A worked example covering the things that turn "accuracy on a
    notebook" into a multiclass classifier you can deploy:

    1. **Per-class metrics**, never just accuracy
    2. **Macro vs micro vs weighted F1** — three different decisions
    3. **`sample_weight` for class imbalance** (XGBoost has no
       `scale_pos_weight` for multiclass)
    4. **Confusion matrix** as the primary diagnostic
    5. **Top-K accuracy + per-class SHAP**

    The punchline: on imbalanced data, training without `sample_weight`
    gives high overall accuracy and **catastrophically fails** on the
    minority class — exactly what macro F1 catches and accuracy hides.
    """)
    return


@app.cell
def generate_data(make_classification, np, pd):
    """5-class imbalanced classification problem.

    Class 0 is 5× more frequent than class 4. This makes the minority
    class easy for the model to ignore unless you pass sample_weight.
    """
    raw_X, raw_y = make_classification(
        n_samples=2500,
        n_features=12,
        n_informative=8,
        n_redundant=2,
        n_classes=5,
        n_clusters_per_class=1,
        weights=[0.40, 0.25, 0.15, 0.12, 0.08],  # 40% / 25% / 15% / 12% / 8%
        class_sep=1.0,
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
    show_counts = df["target"].value_counts().sort_index()
    show_pcts = (df["target"].value_counts(normalize=True).sort_index() * 100).round(1)
    show_table_md = "\n".join(
        f"| class {i} | {int(show_counts[i])} | {show_pcts[i]:.1f}% |"
        for i in range(5)
    )
    mo.md(
        f"""
    ## Dataset

    - **Rows:** {len(df)}
    - **Features:** 12 (8 informative, 2 redundant)
    - **Classes:** 5 (imbalanced)

    | class | count | percent |
    |---|---|---|
    {show_table_md}

    The most-frequent class is **5× more common** than the rarest.
    Realistic for problems like product category prediction (a few
    bestsellers + a long tail) or fault classification (mostly normal,
    rare specific failures). **In production read your data via ibis**
    (`ibis.duckdb.connect().read_parquet(...)`) and materialize once
    with `.execute()` for sklearn — see SKILL.md.
    """
    )
    return


@app.cell
def split(df, feature_cols, train_test_split):
    X_train, X_test, y_train, y_test = train_test_split(
        df[feature_cols],
        df["target"].astype(int),
        test_size=0.2,
        random_state=42,
        stratify=df["target"],
    )
    return X_test, X_train, y_test, y_train


@app.cell
def fit_section(mo):
    mo.md(r"""
    ## Fit two XGBoost models — without and with `sample_weight`

    **Without weights:** XGBoost optimizes log-loss across all rows
    equally, so common classes dominate the gradient and the model
    learns to ignore the rare ones.

    **With weights:** `sample_weight = compute_sample_weight("balanced", y_train)`
    rescales each row so each class has the same total weight. The
    rare classes now contribute as much to the loss as the common
    ones.
    """)
    return


@app.cell
def make_pipeline_helper(
    ColumnTransformer,
    Pipeline,
    StandardScaler,
    XGBClassifier,
    feature_cols,
):
    def build_xgb(seed):
        return Pipeline([
            ("preprocess", ColumnTransformer([("num", StandardScaler(), feature_cols)])),
            ("clf", XGBClassifier(
                n_estimators=300,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_lambda=1.0,
                objective="multi:softprob",
                num_class=5,
                eval_metric="mlogloss",
                random_state=seed,
                n_jobs=-1,
            )),
        ])

    return (build_xgb,)


@app.cell
def fit_unweighted(X_train, build_xgb, y_train):
    pipeline_unweighted = build_xgb(seed=42)
    pipeline_unweighted.fit(X_train, y_train)
    return (pipeline_unweighted,)


@app.cell
def fit_weighted(X_train, build_xgb, compute_sample_weight, y_train):
    sample_weight_arr = compute_sample_weight(class_weight="balanced", y=y_train)
    pipeline_weighted = build_xgb(seed=42)
    pipeline_weighted.fit(X_train, y_train, clf__sample_weight=sample_weight_arr)
    return (pipeline_weighted,)


@app.cell
def metric_compare_section(mo):
    mo.md(r"""
    ## Side-by-side metrics — overall vs per-class

    Watch what happens to **macro F1** and the **minority-class F1**
    when sample weighting kicks in. The overall accuracy barely moves,
    but the rare-class F1 jumps significantly. **This is the failure
    mode that accuracy hides and macro F1 catches.**
    """)
    return


@app.cell
def compute_metrics(
    X_test,
    accuracy_score,
    f1_score,
    mo,
    pipeline_unweighted,
    pipeline_weighted,
    precision_recall_fscore_support,
    top_k_accuracy_score,
    y_test,
):
    def metrics_for(pipeline_in):
        proba_in = pipeline_in.predict_proba(X_test)
        pred_in = proba_in.argmax(axis=1)
        per_class_f1 = precision_recall_fscore_support(
            y_test, pred_in, labels=list(range(5)), zero_division=0
        )[2]
        return {
            "accuracy": float(accuracy_score(y_test, pred_in)),
            "f1_macro": float(f1_score(y_test, pred_in, average="macro")),
            "f1_micro": float(f1_score(y_test, pred_in, average="micro")),
            "f1_weighted": float(f1_score(y_test, pred_in, average="weighted")),
            "top_3": float(top_k_accuracy_score(y_test, proba_in, k=3, labels=list(range(5)))),
            "per_class_f1": per_class_f1,
            "pred": pred_in,
            "proba": proba_in,
        }

    metrics_uw = metrics_for(pipeline_unweighted)
    metrics_w = metrics_for(pipeline_weighted)

    def fmt(uw_val, w_val):
        delta = w_val - uw_val
        sign = "+" if delta >= 0 else ""
        return f"`{uw_val:.4f}` → `{w_val:.4f}` ({sign}{delta:.4f})"

    rows_md = "\n".join([
        f"| accuracy | {fmt(metrics_uw['accuracy'], metrics_w['accuracy'])} |",
        f"| F1 macro | {fmt(metrics_uw['f1_macro'], metrics_w['f1_macro'])} |",
        f"| F1 micro | {fmt(metrics_uw['f1_micro'], metrics_w['f1_micro'])} |",
        f"| F1 weighted | {fmt(metrics_uw['f1_weighted'], metrics_w['f1_weighted'])} |",
        f"| top-3 accuracy | {fmt(metrics_uw['top_3'], metrics_w['top_3'])} |",
    ])
    per_class_rows = "\n".join([
        f"| class {i} | {fmt(metrics_uw['per_class_f1'][i], metrics_w['per_class_f1'][i])} |"
        for i in range(5)
    ])

    mo.md(
        f"""
    ### Overall metrics (unweighted → weighted)

    | Metric | Change |
    |---|---|
    {rows_md}

    ### Per-class F1 (unweighted → weighted)

    | Class | Change |
    |---|---|
    {per_class_rows}

    Look at **class 4** (the rarest, ~8% of data). The unweighted
    model often gets ~0.4 F1 there because it almost never predicts
    that class. With sample weighting, F1 jumps significantly even
    though accuracy is essentially unchanged.
    """
    )
    return (metrics_w,)


@app.cell
def confusion_section(mo):
    mo.md(r"""
    ## Confusion matrices — which classes get confused for which?

    The single most informative diagnostic for multiclass. Two views:

    - **Raw counts** — magnitude of errors
    - **Row-normalized** — given true class `i`, what fraction goes where?
      The diagonal is per-class recall.
    """)
    return


@app.cell
def confusion_plots(confusion_matrix, metrics_w, mo, plt, y_test):
    cm_raw = confusion_matrix(y_test, metrics_w["pred"], labels=list(range(5)))
    cm_norm = cm_raw.astype(float) / cm_raw.sum(axis=1, keepdims=True)

    fig_cm, axes_cm = plt.subplots(1, 2, figsize=(12, 5))
    for ax_cm, mat, fmt_str, title in (
        (axes_cm[0], cm_raw, "d", "Counts (weighted model)"),
        (axes_cm[1], cm_norm, ".2f", "Row-normalized = per-class recall"),
    ):
        im = ax_cm.imshow(mat, cmap="Blues")
        ax_cm.set_xticks(range(5))
        ax_cm.set_yticks(range(5))
        ax_cm.set_xticklabels([f"c{i}" for i in range(5)])
        ax_cm.set_yticklabels([f"c{i}" for i in range(5)])
        ax_cm.set_xlabel("predicted")
        ax_cm.set_ylabel("true")
        ax_cm.set_title(title)
        thresh = mat.max() / 2
        for i_cm in range(5):
            for j_cm in range(5):
                ax_cm.text(
                    j_cm, i_cm, format(mat[i_cm, j_cm], fmt_str),
                    ha="center", va="center", fontsize=10,
                    color="white" if mat[i_cm, j_cm] > thresh else "black",
                )
        fig_cm.colorbar(im, ax=ax_cm, fraction=0.046)
    fig_cm.tight_layout()
    mo.as_html(fig_cm)
    return


@app.cell
def per_class_section(mo):
    mo.md(r"""
    ## Per-class precision / recall / F1

    The bar chart that should appear on every multiclass model report.
    Catches "high accuracy but a class is dead" failures at a glance.
    """)
    return


@app.cell
def per_class_plot(
    metrics_w,
    mo,
    np,
    plt,
    precision_recall_fscore_support,
    y_test,
):
    pc_prec, pc_rec, pc_f1, pc_sup = precision_recall_fscore_support(
        y_test, metrics_w["pred"], labels=list(range(5)), zero_division=0
    )
    x_pc = np.arange(5)
    width_pc = 0.25
    fig_pc, ax_pc = plt.subplots(figsize=(9, 4))
    ax_pc.bar(x_pc - width_pc, pc_prec, width_pc, label="precision", color="#4477aa")
    ax_pc.bar(x_pc, pc_rec, width_pc, label="recall", color="#ee8866")
    ax_pc.bar(x_pc + width_pc, pc_f1, width_pc, label="F1", color="#228833")
    ax_pc.set_xticks(x_pc)
    ax_pc.set_xticklabels([f"class {i}\n(n={int(pc_sup[i])})" for i in range(5)])
    ax_pc.set_ylim(0, 1.05)
    ax_pc.set_ylabel("score")
    ax_pc.set_title("Per-class precision / recall / F1 — weighted model")
    ax_pc.legend(loc="best", fontsize=9)
    fig_pc.tight_layout()
    mo.as_html(fig_pc)
    return


@app.cell
def shap_section(mo):
    mo.md(r"""
    ## SHAP feature importance — per class

    Multiclass SHAP returns a 3D array `(n_samples, n_features,
    n_classes)`. Slice to one class to plot. Below is the SHAP summary
    for **class 4** (the rarest one) — it tells you which features
    push predictions toward / away from the minority class.
    """)
    return


@app.cell
def shap_plot(X_test, feature_cols, mo, pipeline_weighted, plt, shap):
    shap_pre = pipeline_weighted.named_steps["preprocess"]
    shap_clf = pipeline_weighted.named_steps["clf"]
    X_test_t = shap_pre.transform(X_test.iloc[:200])

    explainer = shap.TreeExplainer(shap_clf)
    shap_values_obj = explainer(X_test_t)

    class_to_explain = 4
    sliced = shap.Explanation(
        values=shap_values_obj.values[:, :, class_to_explain],
        base_values=(
            shap_values_obj.base_values[:, class_to_explain]
            if shap_values_obj.base_values.ndim > 1
            else shap_values_obj.base_values
        ),
        data=shap_values_obj.data,
        feature_names=feature_cols,
    )
    plt.figure(figsize=(8, 5))
    shap.summary_plot(sliced, X_test_t, feature_names=feature_cols, show=False)
    fig_shap = plt.gcf()
    fig_shap.suptitle(f"SHAP summary — class {class_to_explain} (rarest)", fontsize=10)
    fig_shap.tight_layout()
    mo.as_html(fig_shap)
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    Six things you should always do for tabular multiclass classification:

    1. **`objective="multi:softprob"`** with explicit `num_class=N`
    2. **`sample_weight = compute_sample_weight("balanced", y_train)`**
       for any class imbalance — never accept the default
    3. **Log per-class F1**, not just macro / micro / weighted
       averages. The averages hide minority-class failures.
    4. **Confusion matrix is the primary diagnostic** — log both raw
       counts and row-normalized versions.
    5. **Top-K accuracy** when you care about "right answer in the
       top 3" rather than exact-match.
    6. **Per-class SHAP** for explainability — slice the 3D
       `shap_values.values` array to one class at a time.

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/multiclass-classification/` directory and your AI
    agent will follow the same workflow on your real data.
    """)
    return


if __name__ == "__main__":
    app.run()
