# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo",
#     "xgboost>=2.0",
#     "scikit-learn>=1.5",
#     "pandas>=2.2",
#     "numpy>=1.26",
#     "matplotlib>=3.9",
# ]
# ///
"""Worked example for the multilabel-classification bundle.

Self-contained: generates a 6-label tabular classification dataset
with varying per-label positive rates, fits XGBoost wrapped in
MultiOutputClassifier, and walks through all the multilabel-specific
diagnostics. No external data files. No MLflow.

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
    from sklearn.compose import ColumnTransformer
    from sklearn.datasets import make_multilabel_classification
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        hamming_loss,
        precision_recall_fscore_support,
    )
    from sklearn.model_selection import train_test_split
    from sklearn.multioutput import MultiOutputClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBClassifier

    return (
        ColumnTransformer,
        MultiOutputClassifier,
        Pipeline,
        StandardScaler,
        XGBClassifier,
        accuracy_score,
        f1_score,
        hamming_loss,
        make_multilabel_classification,
        mo,
        np,
        pd,
        plt,
        precision_recall_fscore_support,
        train_test_split,
    )


@app.cell
def title(mo):
    mo.md(r"""
    # Multilabel Classification with XGBoost (Done Right)

    Multilabel ≠ multiclass. Multiclass picks **one** class from N.
    Multilabel predicts **any subset** of N labels — each row can
    have zero, one, or many labels on simultaneously.

    The metrics, the model wrapping, and the failure modes are all
    different. This notebook walks through:

    1. **`MultiOutputClassifier(XGBClassifier)`** — one model per label
    2. **Hamming loss** as the primary metric (NOT subset accuracy)
    3. **Four F1 averages** — macro / micro / weighted / **samples**
    4. **Label co-occurrence heatmap** to see if labels are correlated
    5. **Per-label F1** to catch rare-label failures
    """)
    return


@app.cell
def generate_data(make_multilabel_classification, np, pd):
    """6-label tabular classification with varying per-label positive rates."""
    raw_X, raw_Y = make_multilabel_classification(
        n_samples=2000,
        n_features=15,
        n_classes=6,
        n_labels=2,  # avg labels per row
        random_state=42,
    )
    feature_cols = [f"feature_{i}" for i in range(15)]
    label_cols = [f"label_{i}" for i in range(6)]

    df = pd.DataFrame(raw_X, columns=feature_cols)
    for gen_idx, gen_lbl in enumerate(label_cols):
        df[gen_lbl] = raw_Y[:, gen_idx].astype(np.int8)
    return df, feature_cols, label_cols


@app.cell
def show_data(df, label_cols, mo):
    show_pos_rates = {lbl: float(df[lbl].mean()) for lbl in label_cols}
    show_pos_counts = {lbl: int(df[lbl].sum()) for lbl in label_cols}
    show_table_md = "\n".join(
        f"| {lbl} | {show_pos_counts[lbl]} | {show_pos_rates[lbl]:.1%} |"
        for lbl in label_cols
    )
    show_card = float(df[label_cols].sum(axis=1).mean())
    mo.md(
        f"""
    ## Dataset

    - **Rows:** {len(df)}
    - **Features:** {len(df.columns) - len(label_cols)}
    - **Labels:** {len(label_cols)} (each independently 0/1)
    - **Mean labels per row:** `{show_card:.2f}`

    | label | positive count | positive rate |
    |---|---|---|
    {show_table_md}

    Positive rates vary across labels — that's typical and the rare
    ones will be harder. **In production, read your data via ibis**
    (`ibis.duckdb.connect().read_parquet(...)`) and materialize once
    with `.execute()` for sklearn — see `SKILL.md`.
    """
    )
    return


@app.cell
def label_balance_plot(df, label_cols, mo, plt):
    bal_rates = [float(df[lbl].mean()) for lbl in label_cols]
    bal_counts = [int(df[lbl].sum()) for lbl in label_cols]
    fig_bal, ax_bal = plt.subplots(figsize=(8, 3.5))
    bars_bal = ax_bal.barh(label_cols, bal_rates, color="#4477aa")
    for bar_b, rate, cnt in zip(bars_bal, bal_rates, bal_counts):
        ax_bal.text(
            rate, bar_b.get_y() + bar_b.get_height() / 2,
            f"  {rate:.1%}  (n={cnt})", va="center", fontsize=8,
        )
    ax_bal.set_xlabel("positive rate")
    ax_bal.set_xlim(0, max(bal_rates) * 1.3)
    ax_bal.set_title("Per-label positive rate")
    fig_bal.tight_layout()
    mo.as_html(fig_bal)
    return


@app.cell
def cooccurrence_section(mo):
    mo.md(r"""
    ## Label co-occurrence heatmap

    Conditional probability `P(label_j = 1 | label_i = 1)`. Reading the
    matrix: row `i`, column `j` = "given label_i is on, how often is
    label_j also on?" The diagonal is always 1.0.

    **Why it matters:** if off-diagonal entries are much higher than
    the marginal positive rate of label_j, your labels are correlated
    and `ClassifierChain` could help. If they hover near the marginals,
    labels are roughly independent and `MultiOutputClassifier` is
    optimal. (See SKILL.md for the chain alternative.)
    """)
    return


@app.cell
def cooccurrence_plot(df, label_cols, mo, np, plt):
    n_lbl = len(label_cols)
    Y_full = df[label_cols].to_numpy()
    cooc = np.zeros((n_lbl, n_lbl))
    for ci in range(n_lbl):
        ci_count = int(Y_full[:, ci].sum())
        if ci_count == 0:
            continue
        for cj in range(n_lbl):
            cooc[ci, cj] = float(((Y_full[:, ci] == 1) & (Y_full[:, cj] == 1)).sum() / ci_count)

    fig_cooc, ax_cooc = plt.subplots(figsize=(7.5, 6))
    im_cooc = ax_cooc.imshow(cooc, cmap="Blues", vmin=0, vmax=1)
    ax_cooc.set_xticks(range(n_lbl))
    ax_cooc.set_yticks(range(n_lbl))
    ax_cooc.set_xticklabels(label_cols, rotation=45, ha="right", fontsize=8)
    ax_cooc.set_yticklabels(label_cols, fontsize=8)
    ax_cooc.set_xlabel("label_j")
    ax_cooc.set_ylabel("label_i (conditioned on)")
    ax_cooc.set_title("Conditional co-occurrence: P(label_j | label_i)")
    for ci in range(n_lbl):
        for cj in range(n_lbl):
            ax_cooc.text(
                cj, ci, f"{cooc[ci, cj]:.2f}",
                ha="center", va="center", fontsize=7,
                color="white" if cooc[ci, cj] > 0.5 else "black",
            )
    fig_cooc.colorbar(im_cooc, ax=ax_cooc, fraction=0.046)
    fig_cooc.tight_layout()
    mo.as_html(fig_cooc)
    return


@app.cell
def split(df, feature_cols, label_cols, train_test_split):
    X_train, X_test, Y_train, Y_test = train_test_split(
        df[feature_cols],
        df[label_cols].to_numpy().astype(int),
        test_size=0.2,
        random_state=42,
    )
    return X_test, X_train, Y_test, Y_train


@app.cell
def fit_section(mo):
    mo.md(r"""
    ## Fit `MultiOutputClassifier(XGBClassifier)`

    `MultiOutputClassifier` fits one independent XGBoost per label
    (parallelized with `n_jobs=-1`). Each underlying XGBoost is just a
    binary classifier — all the binary-classification lessons apply
    per label.
    """)
    return


@app.cell
def fit_model(
    ColumnTransformer,
    MultiOutputClassifier,
    Pipeline,
    StandardScaler,
    XGBClassifier,
    X_train,
    Y_train,
    feature_cols,
):
    pipeline = Pipeline([
        ("preprocess", ColumnTransformer([("num", StandardScaler(), feature_cols)])),
        ("clf", MultiOutputClassifier(
            XGBClassifier(
                n_estimators=300,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_lambda=1.0,
                objective="binary:logistic",
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
            ),
            n_jobs=-1,
        )),
    ])
    pipeline.fit(X_train, Y_train)
    return (pipeline,)


@app.cell
def metrics_section(mo):
    mo.md(r"""
    ## Hamming loss vs subset accuracy

    **Hamming loss** is the average per-label-slot error rate — the
    primary metric. **Subset accuracy** (exact-match accuracy) is
    brutally strict: every label must match exactly for the row to
    count as "correct." On a 6-label problem, even great per-label
    performance gives mediocre subset accuracy.
    """)
    return


@app.cell
def overall_metrics(
    X_test,
    Y_test,
    accuracy_score,
    f1_score,
    hamming_loss,
    mo,
    pipeline,
):
    Y_pred = pipeline.predict(X_test)

    ham = float(hamming_loss(Y_test, Y_pred))
    subset_acc = float(accuracy_score(Y_test, Y_pred))
    f1_mac = float(f1_score(Y_test, Y_pred, average="macro", zero_division=0))
    f1_mic = float(f1_score(Y_test, Y_pred, average="micro", zero_division=0))
    f1_w = float(f1_score(Y_test, Y_pred, average="weighted", zero_division=0))
    f1_s = float(f1_score(Y_test, Y_pred, average="samples", zero_division=0))

    mo.md(
        f"""
    | Metric | Value | Notes |
    |---|---|---|
    | **Hamming loss** | **`{ham:.4f}`** | Lower = better. ~{ham:.0%} of label slots wrong on average. |
    | Subset accuracy | `{subset_acc:.4f}` | Brutally strict — all labels must match. |
    | F1 macro | `{f1_mac:.4f}` | Unweighted mean across labels. **Default for monitoring.** |
    | F1 micro | `{f1_mic:.4f}` | Pooled across all (sample, label) predictions. |
    | F1 weighted | `{f1_w:.4f}` | Weighted by label support — hides rare-label failures. |
    | F1 samples | `{f1_s:.4f}` | Per-row F1, then averaged. Multilabel-only. |

    The gap between macro and weighted F1 is the rare-label tax.
    Watch macro carefully.
    """
    )
    return (Y_pred,)


@app.cell
def per_label_section(mo):
    mo.md(r"""
    ## Per-label precision / recall / F1

    The bar chart that should appear on every multilabel model report.
    Each label is independent so positive rates and difficulty vary —
    expect rare labels to lag.
    """)
    return


@app.cell
def per_label_plot(
    Y_pred,
    Y_test,
    label_cols,
    mo,
    np,
    plt,
    precision_recall_fscore_support,
):
    n_lbl_p = len(label_cols)
    pl_prec = []
    pl_rec = []
    pl_f1 = []
    pl_sup = []
    for pli in range(n_lbl_p):
        p, r, f, _ = precision_recall_fscore_support(
            Y_test[:, pli], Y_pred[:, pli], average="binary", zero_division=0
        )
        pl_prec.append(p)
        pl_rec.append(r)
        pl_f1.append(f)
        pl_sup.append(int(Y_test[:, pli].sum()))

    x_pl = np.arange(n_lbl_p)
    width_pl = 0.25
    fig_pl, ax_pl = plt.subplots(figsize=(11, 4.5))
    ax_pl.bar(x_pl - width_pl, pl_prec, width_pl, label="precision", color="#4477aa")
    ax_pl.bar(x_pl, pl_rec, width_pl, label="recall", color="#ee8866")
    ax_pl.bar(x_pl + width_pl, pl_f1, width_pl, label="F1", color="#228833")
    ax_pl.set_xticks(x_pl)
    ax_pl.set_xticklabels(
        [f"{lbl}\n(n={pl_sup[plj]})" for plj, lbl in enumerate(label_cols)],
        fontsize=8,
    )
    ax_pl.set_ylim(0, 1.05)
    ax_pl.set_ylabel("score")
    ax_pl.set_title("Per-label precision / recall / F1")
    ax_pl.legend(loc="best", fontsize=9)
    for plk, v in enumerate(pl_f1):
        ax_pl.text(plk + width_pl, v, f"{v:.2f}", ha="center", va="bottom", fontsize=7)
    fig_pl.tight_layout()
    mo.as_html(fig_pl)
    return


@app.cell
def cardinality_section(mo):
    mo.md(r"""
    ## Label cardinality — true vs predicted

    Distribution of "labels per row" for the true labels and the model's
    predictions. If the predicted distribution is shifted left (fewer
    labels), the model is under-predicting positives across the board —
    usually a per-label threshold-tuning problem.
    """)
    return


@app.cell
def cardinality_plot(Y_pred, Y_test, mo, np, plt):
    true_card = Y_test.sum(axis=1)
    pred_card = Y_pred.sum(axis=1)
    max_c = int(max(true_card.max(), pred_card.max()))
    bins_card = np.arange(0, max_c + 2) - 0.5

    fig_card, ax_card = plt.subplots(figsize=(8, 4))
    ax_card.hist(true_card, bins=bins_card, alpha=0.6, color="#4477aa", label="true")
    ax_card.hist(pred_card, bins=bins_card, alpha=0.6, color="#cc3311", label="predicted")
    ax_card.set_xticks(range(0, max_c + 1))
    ax_card.set_xlabel("labels per row")
    ax_card.set_ylabel("count")
    ax_card.set_title(
        f"Label cardinality — true mean {true_card.mean():.2f}, pred mean {pred_card.mean():.2f}"
    )
    ax_card.legend(loc="best")
    fig_card.tight_layout()
    mo.as_html(fig_card)
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    Six things you should always do for tabular multilabel classification:

    1. **`MultiOutputClassifier(XGBClassifier(...), n_jobs=-1)`** —
       one independent model per label, parallelized
    2. **Hamming loss is the primary metric**, not subset accuracy
    3. **Log per-label F1** as separate MLflow metrics — each label
       has its own positive rate and its own difficulty
    4. **Macro F1 over weighted F1** — macro surfaces rare-label
       failures that weighted hides
    5. **Plot the label co-occurrence heatmap** before deciding on
       `MultiOutputClassifier` vs `ClassifierChain`
    6. **Watch the predicted vs true label cardinality** — if the
       predicted average is much lower, the model is under-predicting
       and per-label thresholds need tuning

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/multilabel-classification/` directory and your AI
    agent will follow the same workflow on your real data.
    """)
    return


if __name__ == "__main__":
    app.run()
