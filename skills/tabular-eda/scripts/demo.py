# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marimo",
#     "scikit-learn>=1.5",
#     "pandas>=2.2",
#     "numpy>=1.26",
#     "matplotlib>=3.9",
# ]
# ///
"""Worked example for the tabular-eda bundle.

Self-contained: generates a deliberately messy binary classification
dataset with seven planted issues, then walks through detecting each
one. No external data files. No MLflow. The end of the notebook is a
findings table — the input to "what model do I train next?"

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
    from sklearn.datasets import make_classification
    from sklearn.feature_selection import mutual_info_classif

    return make_classification, mo, mutual_info_classif, np, pd, plt


@app.cell
def title(mo):
    mo.md(r"""
    # Tabular EDA — Find Leakage, Quality Issues, and Hidden Signal

    The workflow you should run on **every** new dataset before
    training anything. Ten minutes of EDA catches problems that would
    otherwise destroy your model in production.

    This notebook generates a deliberately messy synthetic dataset with
    **seven planted issues** and walks through detecting each one. The
    end is a findings table — the input to "what model do I train next?"

    ### Planted issues (don't peek)

    1. Target leakage feature
    2. High-cardinality categorical
    3. Near-constant feature
    4. 30% missing data in one column
    5. Heavily skewed distribution
    6. 2% outliers in one column
    7. Redundant feature pair

    Scroll down to see how many the EDA pipeline catches.
    """)
    return


@app.cell
def generate_messy_data(make_classification, np, pd):
    """Synthetic binary classification with seven planted EDA issues.

    In production the buyer's data lives in parquet/CSV/database. Read
    it with ibis (`ibis.duckdb.connect().read_parquet(...)`) and
    materialize once for the EDA workflow. See SKILL.md for the pattern.
    """
    rng = np.random.default_rng(42)
    n_samples = 2000

    # Clean baseline
    X_clean, y = make_classification(
        n_samples=n_samples, n_features=6, n_informative=4, n_redundant=1,
        n_classes=2, weights=[0.85, 0.15], class_sep=1.0, random_state=42,
    )
    df = (
        pd.DataFrame(X_clean, columns=[f"feature_{i}" for i in range(6)])
        .assign(target=y.astype(np.int8))
    )

    # 1. Target leakage
    df["account_balance_post_action"] = df["target"] * 100.0 + rng.normal(0, 1, n_samples)
    # 2. High-cardinality categorical
    df["user_id"] = [f"user_{i % (n_samples // 3)}" for i in range(n_samples)]
    # 3. Near-constant
    df["fraud_blocklist"] = rng.choice([0, 1], size=n_samples, p=[0.99, 0.01]).astype(np.int8)
    # 4. MCAR missing
    df.loc[rng.random(n_samples) < 0.30, "feature_0"] = np.nan
    # 5. Skewed
    df["transaction_amount"] = rng.lognormal(mean=5.0, sigma=2.0, size=n_samples)
    # 6. Outliers
    base_lat = rng.normal(100, 20, n_samples)
    out_mask = rng.random(n_samples) < 0.02
    base_lat[out_mask] = rng.uniform(1500, 5000, int(out_mask.sum()))
    df["latency_ms"] = base_lat
    # 7. Redundant
    df["feature_1_copy"] = df["feature_1"] + rng.normal(0, 0.01, n_samples)
    # Bonus: a useful low-card categorical
    df["region"] = rng.choice(["north", "south", "east", "west"], size=n_samples)
    return (df,)


@app.cell
def shape_section(df, mo):
    n_num = sum(1 for c in df.columns if df[c].dtype.kind in "biuf")
    n_cat = sum(1 for c in df.columns if df[c].dtype == object)
    mo.md(
        f"""
    ## 1. Shape and dtypes

    - **Rows:** {len(df)}
    - **Columns:** {len(df.columns)} ({n_num} numeric, {n_cat} categorical)
    - **Memory:** {df.memory_usage(deep=True).sum() / 1024:.1f} KB

    First five rows:
    """
    )
    return


@app.cell
def head_table(df, mo):
    mo.ui.table(df.head(5))
    return


@app.cell
def target_section(df, mo):
    target_dtype = df["target"].dtype
    target_unique = int(df["target"].nunique())
    if target_unique == 2:
        target_type_str = "binary"
    elif target_unique <= 20:
        target_type_str = "multiclass"
    elif target_dtype.kind == "f":
        target_type_str = "regression"
    else:
        target_type_str = "high-cardinality int (likely regression)"
    target_balance = df["target"].value_counts(normalize=True).sort_index()
    mo.md(
        f"""
    ## 2. Target inference

    - **Target column:** `target`
    - **Dtype:** `{target_dtype}`
    - **Unique values:** {target_unique}
    - **Inferred type:** **{target_type_str}**
    - **Balance:** class 0 = `{target_balance[0]:.1%}`, class 1 = `{target_balance[1]:.1%}`

    → This is a **binary classification** problem with mild class
    imbalance. The downstream skill is `binary-classification`.
    """
    )
    return


@app.cell
def missing_section(mo):
    mo.md(r"""
    ## 3. Missing data

    Per-column missing %, sorted descending. Anything > 0% deserves a
    decision: impute, drop, or model the missingness. Anything > 50%
    is usually a drop.
    """)
    return


@app.cell
def missing_plot(df, mo, plt):
    miss_pct = (df.isna().mean() * 100).sort_values(ascending=True)
    fig_miss, ax_miss = plt.subplots(figsize=(8, max(3, 0.3 * len(miss_pct))))
    bars_miss = ax_miss.barh(miss_pct.index, miss_pct.values, color="#cc3311")
    for bar_m, val_m in zip(bars_miss, miss_pct.values):
        if val_m > 0:
            ax_miss.text(val_m, bar_m.get_y() + bar_m.get_height() / 2,
                         f"  {val_m:.1f}%", va="center", fontsize=8)
    ax_miss.set_xlabel("missing %")
    ax_miss.set_title("Missing data per column")
    ax_miss.set_xlim(0, max(100, miss_pct.max() * 1.15))
    fig_miss.tight_layout()
    mo.as_html(fig_miss)
    return


@app.cell
def numeric_dist_section(mo):
    mo.md(r"""
    ## 4. Numeric distributions

    Histograms of every numeric column. Each title shows the **skew**:
    `|skew| > 1` means the distribution is heavily asymmetric and you
    should consider a log or Box-Cox transform before training.
    """)
    return


@app.cell
def numeric_dist_plot(df, mo, np, plt):
    num_cols_dist = [c for c in df.columns if df[c].dtype.kind in "biuf" and c != "target"]
    n_dist = len(num_cols_dist)
    n_dist_cols = 4
    n_dist_rows = (n_dist + n_dist_cols - 1) // n_dist_cols
    fig_nd, axes_nd = plt.subplots(n_dist_rows, n_dist_cols, figsize=(12, 2.4 * n_dist_rows))
    axes_nd = np.atleast_2d(axes_nd)
    for idx_nd, col_nd in enumerate(num_cols_dist):
        ax_nd = axes_nd[idx_nd // n_dist_cols, idx_nd % n_dist_cols]
        vals_nd = df[col_nd].dropna()
        ax_nd.hist(vals_nd, bins=40, color="#4477aa", alpha=0.7)
        skew_nd = float(vals_nd.skew())
        title_nd = f"{col_nd}\nskew={skew_nd:+.2f}"
        if abs(skew_nd) > 1.0:
            title_nd += " ⚠"
        ax_nd.set_title(title_nd, fontsize=8)
        ax_nd.tick_params(labelsize=7)
    for idx_blank in range(n_dist, n_dist_rows * n_dist_cols):
        axes_nd[idx_blank // n_dist_cols, idx_blank % n_dist_cols].axis("off")
    fig_nd.suptitle("Numeric distributions (⚠ marks |skew| > 1)", fontsize=10)
    fig_nd.tight_layout()
    mo.as_html(fig_nd)
    return


@app.cell
def cardinality_section(mo):
    mo.md(r"""
    ## 5. Categorical cardinality

    Bar chart of unique-value counts per categorical column. **Red bars
    > 50** are high-cardinality and would explode a `OneHotEncoder` —
    use target encoding, frequency encoding, or hashing instead.
    """)
    return


@app.cell
def cardinality_plot(df, mo, pd, plt):
    cat_cols_card = [c for c in df.columns if df[c].dtype == object]
    cat_counts = pd.Series({c: int(df[c].nunique()) for c in cat_cols_card}).sort_values(ascending=True)
    fig_card, ax_card = plt.subplots(figsize=(8, max(2, 0.4 * len(cat_counts))))
    cat_colors = ["#cc3311" if v > 50 else "#4477aa" for v in cat_counts.values]
    bars_card = ax_card.barh(cat_counts.index, cat_counts.values, color=cat_colors)
    for bar_c, val_c in zip(bars_card, cat_counts.values):
        ax_card.text(val_c, bar_c.get_y() + bar_c.get_height() / 2,
                     f"  {val_c}", va="center", fontsize=8)
    ax_card.axvline(50, color="black", lw=1, ls="--", alpha=0.5)
    ax_card.set_xlabel("unique value count")
    ax_card.set_title("Categorical cardinality (red = > 50, OHE explosion risk)")
    fig_card.tight_layout()
    mo.as_html(fig_card)
    return


@app.cell
def correlation_section(mo):
    mo.md(r"""
    ## 6. Correlation heatmap (Pearson)

    Pearson correlations of every numeric feature with every other
    numeric feature, with the **target column** annotated. Watch for
    two things:

    - **|Pearson| > 0.95 with the target** → target leakage suspect
    - **|Pearson| > 0.95 between two features** → redundant pair
    """)
    return


@app.cell
def correlation_plot(df, mo, plt):
    corr_num = [c for c in df.columns if df[c].dtype.kind in "biuf"]
    corr_mat = df[corr_num].corr().values
    fig_cm, ax_cm = plt.subplots(figsize=(9, 7))
    im_cm = ax_cm.imshow(corr_mat, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax_cm.set_xticks(range(len(corr_num)))
    ax_cm.set_yticks(range(len(corr_num)))
    ax_cm.set_xticklabels(corr_num, rotation=45, ha="right", fontsize=8)
    ax_cm.set_yticklabels(corr_num, fontsize=8)
    target_idx_cm = corr_num.index("target")
    for i_cm in range(len(corr_num)):
        ax_cm.text(
            target_idx_cm, i_cm, f"{corr_mat[i_cm, target_idx_cm]:.2f}",
            ha="center", va="center", fontsize=7,
            color="black" if abs(corr_mat[i_cm, target_idx_cm]) < 0.5 else "white",
        )
    ax_cm.set_title("Pearson correlations (annotated column = correlation with target)")
    fig_cm.colorbar(im_cm, ax=ax_cm, fraction=0.046)
    fig_cm.tight_layout()
    mo.as_html(fig_cm)
    return


@app.cell
def mi_section(mo):
    mo.md(r"""
    ## 7. Mutual information vs Pearson — catch non-linear signal

    Pearson only catches **linear** relationships. A feature that drives
    the target via `sin(x)` or `(x - 0.5)²` will have Pearson ≈ 0 and
    look useless to a linear EDA. Mutual information catches both.

    **Look for features where MI is high but |Pearson| is low** —
    those are non-linear signal hiding from your linear analysis. They
    will be invisible to a linear model and powerful in XGBoost.
    """)
    return


@app.cell
def mi_plot(df, mo, mutual_info_classif, np, plt):
    num_cols_mi = [c for c in df.columns if df[c].dtype.kind in "biuf" and c != "target"]
    # MI requires no missing values; impute with median for the score
    X_mi = df[num_cols_mi].copy()
    for col_mi in num_cols_mi:
        if X_mi[col_mi].isna().any():
            X_mi[col_mi] = X_mi[col_mi].fillna(X_mi[col_mi].median())
    mi_scores = mutual_info_classif(X_mi.values, df["target"].values, random_state=0)
    pearson_abs_arr = (
        df[num_cols_mi + ["target"]].corr()["target"].drop("target").abs().values
    )

    x_arr = np.arange(len(num_cols_mi))
    width = 0.4
    fig_mi, ax_mi = plt.subplots(figsize=(11, 4))
    ax_mi.bar(x_arr - width / 2, pearson_abs_arr, width, label="|Pearson|", color="#4477aa")
    ax_mi.bar(x_arr + width / 2, mi_scores, width, label="Mutual Info", color="#ee8866")
    ax_mi.set_xticks(x_arr)
    ax_mi.set_xticklabels(num_cols_mi, rotation=45, ha="right", fontsize=8)
    ax_mi.set_title("Linear vs non-linear relationship with target (MI catches what Pearson misses)")
    ax_mi.legend(loc="best")
    fig_mi.tight_layout()
    mo.as_html(fig_mi)
    return


@app.cell
def findings_section(mo):
    mo.md(r"""
    ## 8. Findings — what the EDA pipeline caught

    The detector functions below are exactly what the SKILL.md
    describes. Each returns a list of suspicious things; the union of
    all findings is the actionable output of EDA.
    """)
    return


@app.cell
def detect_findings(df, np, pd):
    """Run all the detectors and return a structured findings dict."""
    target_col_f = "target"
    numeric_f = [c for c in df.columns if df[c].dtype.kind in "biuf"]
    cat_f = [c for c in df.columns if df[c].dtype == object]

    # Leakage: features with |Pearson| > 0.95 to target
    leakage_f = []
    for col_f in numeric_f:
        if col_f == target_col_f:
            continue
        try:
            corr_val = float(df[[col_f, target_col_f]].dropna().corr().iloc[0, 1])
        except Exception:
            continue
        if np.isfinite(corr_val) and abs(corr_val) > 0.95:
            leakage_f.append({"feature": col_f, "pearson": round(corr_val, 4),
                              "issue": "target leakage suspect"})

    # High cardinality: categoricals with > 50 unique values
    high_card_f = []
    for col_f in cat_f:
        n_unique_f = int(df[col_f].nunique())
        if n_unique_f > 50:
            high_card_f.append({"feature": col_f, "n_unique": n_unique_f,
                                "issue": "high cardinality (OHE explosion risk)"})

    # Near constant: top value > 98%
    near_const_f = []
    for col_f in df.columns:
        try:
            top_freq_f = float(df[col_f].value_counts(normalize=True).iloc[0])
        except Exception:
            continue
        if top_freq_f > 0.98:
            near_const_f.append({"feature": col_f, "top_value_freq": round(top_freq_f, 4),
                                 "issue": "near-constant"})

    # Redundant pairs: |Pearson| > 0.95 between numeric features
    feature_num_f = [c for c in numeric_f if c != target_col_f]
    redundant_f = []
    if len(feature_num_f) >= 2:
        corr_abs_f = df[feature_num_f].corr().abs()
        for i_f, c1_f in enumerate(feature_num_f):
            for c2_f in feature_num_f[i_f + 1:]:
                v_f = float(corr_abs_f.loc[c1_f, c2_f])
                if v_f > 0.95:
                    redundant_f.append({"pair": [c1_f, c2_f], "pearson": round(v_f, 4),
                                        "issue": "redundant pair"})

    # Missing data
    missing_f = []
    for col_f in df.columns:
        pct_miss = float(df[col_f].isna().mean())
        if pct_miss > 0.0:
            missing_f.append({"feature": col_f, "missing_pct": round(pct_miss, 4),
                              "issue": "missing data"})

    # Skewed
    skewed_f = []
    for col_f in feature_num_f:
        skew_val = float(df[col_f].dropna().skew())
        if abs(skew_val) > 1.0:
            skewed_f.append({"feature": col_f, "skew": round(skew_val, 4),
                             "issue": "skewed distribution"})

    # Outliers (IQR-based)
    outliers_f = []
    for col_f in feature_num_f:
        vals_o = df[col_f].dropna()
        q1, q3 = float(vals_o.quantile(0.25)), float(vals_o.quantile(0.75))
        iqr = q3 - q1
        n_out = int(((vals_o < q1 - 1.5 * iqr) | (vals_o > q3 + 1.5 * iqr)).sum())
        out_pct = n_out / len(vals_o)
        if out_pct > 0.01:
            outliers_f.append({"feature": col_f, "n_outliers": n_out,
                               "outlier_pct": round(out_pct, 4),
                               "issue": "outliers"})

    all_findings = (
        leakage_f + high_card_f + near_const_f + redundant_f
        + missing_f + skewed_f + outliers_f
    )
    findings_df = pd.DataFrame(all_findings) if all_findings else pd.DataFrame(columns=["issue", "feature"])
    return (findings_df,)


@app.cell
def show_findings(findings_df, mo):
    mo.vstack(
        [
            mo.md(f"### Found **{len(findings_df)}** issues across {findings_df['feature'].nunique() if 'feature' in findings_df.columns else 0} columns"),
            mo.ui.table(findings_df),
        ]
    )
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    Run this workflow on **every** new tabular dataset before training
    anything. Ten minutes of EDA catches:

    1. **Target leakage** — features that look too good to be true
    2. **High-cardinality categoricals** — OHE explosion risk
    3. **Near-constant features** — no signal
    4. **Redundant pairs** — multicollinearity
    5. **Missing data patterns** — impute, drop, or model
    6. **Skewed distributions** — log or Box-Cox transform
    7. **Outliers** — robust scaler or winsorize
    8. **Non-linear signal Pearson misses** — flagged by mutual info

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/tabular-eda/` directory and your AI agent will run
    this workflow on any new dataset automatically. The findings table
    is the input to "what model do I train next?"
    """)
    return


if __name__ == "__main__":
    app.run()
