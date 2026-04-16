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
"""Worked example for the unsupervised bundle.

Self-contained: generates TWO datasets to make the algorithm-vs-shape
lesson concrete:

- make_blobs (4 convex clusters)  — KMeans wins
- make_moons (two interleaved half-moons) — DBSCAN wins, KMeans fails

Then walks through K selection via silhouette, stability check across
random seeds, and IsolationForest anomaly detection on injected
outliers. No external data files. No MLflow.

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
    from sklearn.cluster import DBSCAN, KMeans
    from sklearn.datasets import make_blobs, make_moons
    from sklearn.decomposition import PCA
    from sklearn.ensemble import IsolationForest
    from sklearn.metrics import (
        adjusted_rand_score,
        silhouette_score,
    )
    from sklearn.mixture import GaussianMixture
    from sklearn.preprocessing import StandardScaler

    return (
        DBSCAN,
        IsolationForest,
        KMeans,
        PCA,
        StandardScaler,
        adjusted_rand_score,
        make_blobs,
        make_moons,
        mo,
        np,
        pd,
        plt,
        silhouette_score,
    )


@app.cell
def title(mo):
    mo.md(r"""
    # Unsupervised Learning — Clustering, Anomalies, and Dimensionality Reduction

    Three things you can do with unlabeled tabular data:

    1. **Cluster** to find segments
    2. **Detect anomalies** to find outliers
    3. **Reduce dimensions** to visualize or denoise

    The big lesson: **no single algorithm works on all cluster shapes.**
    KMeans dominates on convex blobs and fails on concentric or moon-shaped
    clusters. DBSCAN is the opposite. This notebook shows both cases
    side by side so the difference is impossible to miss.
    """)
    return


@app.cell
def generate_blobs_data(StandardScaler, make_blobs, np, pd):
    """4 well-separated convex clusters in 8 dimensions — KMeans's home turf."""
    raw_X, raw_y = make_blobs(
        n_samples=1500,
        n_features=8,
        centers=4,
        cluster_std=0.9,
        random_state=42,
    )
    feature_cols_blobs = [f"feature_{i}" for i in range(8)]
    df_blobs = (
        pd.DataFrame(raw_X, columns=feature_cols_blobs)
        .assign(cluster=raw_y.astype(np.int16))
    )
    X_blobs = StandardScaler().fit_transform(df_blobs[feature_cols_blobs])
    y_blobs = df_blobs["cluster"].to_numpy()
    return X_blobs, df_blobs, y_blobs


@app.cell
def generate_moons_data(StandardScaler, make_moons, np, pd):
    """Two interleaved half-moons — non-convex, KMeans cannot handle."""
    moons_X, moons_y = make_moons(n_samples=600, noise=0.07, random_state=42)
    df_moons = (
        pd.DataFrame(moons_X, columns=["feature_0", "feature_1"])
        .assign(cluster=moons_y.astype(np.int16))
    )
    X_moons = StandardScaler().fit_transform(df_moons[["feature_0", "feature_1"]])
    y_moons = df_moons["cluster"].to_numpy()
    return X_moons, df_moons, y_moons


@app.cell
def datasets_summary(df_blobs, df_moons, mo):
    mo.md(
        f"""
    ## Two datasets

    | | Shape | What it tests |
    |---|---|---|
    | **blobs** | {df_blobs.shape[0]} rows × {df_blobs.shape[1] - 1} features, 4 true clusters | KMeans's strength: convex spherical clusters |
    | **moons** | {df_moons.shape[0]} rows × {df_moons.shape[1] - 1} features, 2 true clusters | KMeans's weakness: non-convex shapes |

    In production the buyer's data lives in parquet/CSV/database. Read
    it with ibis (`ibis.duckdb.connect().read_parquet(...)`) and
    materialize once via `.execute()` for the unsupervised pipeline.
    See `SKILL.md` for the pattern.
    """
    )
    return


@app.cell
def k_selection_section(mo):
    mo.md(r"""
    ## 1. Choosing K via silhouette score

    The classic "elbow method" plots inertia vs K and looks for a
    visual kink. **It's subjective.** Silhouette score is quantifiable:
    pick the K that maximizes it.

    Below: both inertia (elbow) and silhouette (the right metric) for
    the blobs dataset across K = 2..10.
    """)
    return


@app.cell
def k_selection_blobs(KMeans, X_blobs, np, silhouette_score):
    k_values = list(range(2, 11))
    inertias_blobs = []
    silhouettes_blobs = []
    for k in k_values:
        km_k = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels_k = km_k.fit_predict(X_blobs)
        inertias_blobs.append(float(km_k.inertia_))
        silhouettes_blobs.append(float(silhouette_score(X_blobs, labels_k)))
    best_k_blobs = k_values[int(np.argmax(silhouettes_blobs))]
    return best_k_blobs, inertias_blobs, k_values, silhouettes_blobs


@app.cell
def k_selection_plot(
    best_k_blobs,
    inertias_blobs,
    k_values,
    mo,
    plt,
    silhouettes_blobs,
):
    fig_k, axes_k = plt.subplots(1, 2, figsize=(11, 4))
    ax_elbow, ax_sil = axes_k

    ax_elbow.plot(k_values, inertias_blobs, marker="o", lw=2, color="#4477aa")
    ax_elbow.axvline(best_k_blobs, color="red", lw=1, ls="--",
                     label=f"chosen K = {best_k_blobs}")
    ax_elbow.set_xlabel("K (number of clusters)")
    ax_elbow.set_ylabel("inertia")
    ax_elbow.set_title("Elbow — visual but subjective")
    ax_elbow.legend(loc="best")

    ax_sil.plot(k_values, silhouettes_blobs, marker="o", lw=2, color="#cc3311")
    ax_sil.axvline(best_k_blobs, color="red", lw=1, ls="--",
                   label=f"chosen K = {best_k_blobs}")
    ax_sil.set_xlabel("K (number of clusters)")
    ax_sil.set_ylabel("silhouette score")
    ax_sil.set_title("Silhouette — quantifiable, prefer this")
    ax_sil.legend(loc="best")

    fig_k.tight_layout()
    mo.as_html(fig_k)
    return


@app.cell
def k_selection_result(best_k_blobs, mo):
    mo.md(
        f"""
    **Result:** silhouette peaks at K = **{best_k_blobs}**, which
    matches the true number of clusters (4). The elbow is also visible
    at K=4 but it's noisier — silhouette gives you a clean answer.
    """
    )
    return


@app.cell
def stability_section(mo):
    mo.md(r"""
    ## 2. Stability check across random seeds

    KMeans is sensitive to initialization. `n_init=10` runs KMeans 10
    times internally and picks the best by inertia, but **you should
    also check that the chosen labeling is stable across different
    random seeds**. Compute pairwise Adjusted Rand Index (ARI) between
    runs at the chosen K. Mean off-diagonal ARI close to 1.0 = stable;
    below 0.7 = your K is wrong or your algorithm is wrong.
    """)
    return


@app.cell
def stability_blobs(KMeans, X_blobs, adjusted_rand_score, best_k_blobs, np):
    n_runs = 6
    stab_runs = []
    for seed in range(n_runs):
        km_stab = KMeans(n_clusters=best_k_blobs, n_init=10, random_state=seed)
        stab_runs.append(km_stab.fit_predict(X_blobs))
    ari_matrix = np.zeros((n_runs, n_runs))
    for i in range(n_runs):
        for j in range(n_runs):
            ari_matrix[i, j] = adjusted_rand_score(stab_runs[i], stab_runs[j])
    ari_off_diag = float(ari_matrix[~np.eye(n_runs, dtype=bool)].mean())
    return ari_matrix, ari_off_diag, n_runs


@app.cell
def stability_plot(ari_matrix, ari_off_diag, mo, n_runs, plt):
    fig_stab, ax_stab = plt.subplots(figsize=(5.5, 4.5))
    im_stab = ax_stab.imshow(ari_matrix, cmap="viridis", vmin=0, vmax=1)
    ax_stab.set_xticks(range(n_runs))
    ax_stab.set_yticks(range(n_runs))
    ax_stab.set_xticklabels([f"run {i}" for i in range(n_runs)], fontsize=8)
    ax_stab.set_yticklabels([f"run {i}" for i in range(n_runs)], fontsize=8)
    for i_s in range(n_runs):
        for j_s in range(n_runs):
            ax_stab.text(
                j_s, i_s, f"{ari_matrix[i_s, j_s]:.2f}",
                ha="center", va="center", fontsize=8,
                color="white" if ari_matrix[i_s, j_s] < 0.7 else "black",
            )
    ax_stab.set_title(f"Stability — mean off-diag ARI = {ari_off_diag:.3f}")
    fig_stab.colorbar(im_stab, ax=ax_stab, fraction=0.046)
    fig_stab.tight_layout()
    mo.as_html(fig_stab)
    return


@app.cell
def comparison_section(mo):
    mo.md(r"""
    ## 3. Algorithm comparison — KMeans vs DBSCAN on both datasets

    The big lesson: **no single algorithm works on all cluster shapes.**

    On the **blobs** dataset (4 convex clusters), KMeans nails it.
    On the **moons** dataset (non-convex), KMeans fails — it can only
    draw straight cluster boundaries. DBSCAN handles both.
    """)
    return


@app.cell
def cluster_blobs(
    DBSCAN,
    KMeans,
    X_blobs,
    adjusted_rand_score,
    best_k_blobs,
    y_blobs,
):
    km_b = KMeans(n_clusters=best_k_blobs, n_init=10, random_state=42)
    km_b_labels = km_b.fit_predict(X_blobs)
    dbscan_b = DBSCAN(eps=0.5, min_samples=5)
    dbscan_b_labels = dbscan_b.fit_predict(X_blobs)

    ari_km_blobs = float(adjusted_rand_score(y_blobs, km_b_labels))
    ari_dbscan_blobs = float(adjusted_rand_score(y_blobs, dbscan_b_labels))
    return ari_dbscan_blobs, ari_km_blobs, dbscan_b_labels, km_b_labels


@app.cell
def cluster_moons(DBSCAN, KMeans, X_moons, adjusted_rand_score, y_moons):
    km_m = KMeans(n_clusters=2, n_init=10, random_state=42)
    km_m_labels = km_m.fit_predict(X_moons)
    dbscan_m = DBSCAN(eps=0.25, min_samples=5)
    dbscan_m_labels = dbscan_m.fit_predict(X_moons)

    ari_km_moons = float(adjusted_rand_score(y_moons, km_m_labels))
    ari_dbscan_moons = float(adjusted_rand_score(y_moons, dbscan_m_labels))
    return ari_dbscan_moons, ari_km_moons, dbscan_m_labels, km_m_labels


@app.cell
def cluster_results_table(
    ari_dbscan_blobs,
    ari_dbscan_moons,
    ari_km_blobs,
    ari_km_moons,
    mo,
):
    mo.md(
        f"""
    ### ARI vs ground truth (higher = better, max = 1.0)

    | Dataset | KMeans | DBSCAN |
    |---|---|---|
    | **blobs** (convex) | `{ari_km_blobs:.3f}` ✓ | `{ari_dbscan_blobs:.3f}` |
    | **moons** (non-convex) | `{ari_km_moons:.3f}` ❌ | `{ari_dbscan_moons:.3f}` ✓ |

    Read across rows: KMeans dominates on blobs, DBSCAN on moons.
    Read down columns: DBSCAN handles both, KMeans only handles
    convex shapes.

    **The lesson:** match the algorithm to the cluster shape. If you
    don't know what shape your clusters have, run both and check
    silhouette + visualize in PCA space.
    """
    )
    return


@app.cell
def visualize_section(mo):
    mo.md(r"""
    ## 4. Visualize the clusters in 2D

    For the moons dataset, the features are already 2D so we can plot
    directly. For the blobs dataset (8D), we project to 2D via PCA
    first.
    """)
    return


@app.cell
def viz_moons(X_moons, dbscan_m_labels, km_m_labels, mo, plt, y_moons):
    fig_m, axes_m = plt.subplots(1, 3, figsize=(13, 4))
    ax_truth_m, ax_km_m, ax_db_m = axes_m

    cmap_m = plt.colormaps.get_cmap("tab10")
    for ax_m, labels_m, title_m in (
        (ax_truth_m, y_moons, "Truth (held out)"),
        (ax_km_m, km_m_labels, "KMeans (fails)"),
        (ax_db_m, dbscan_m_labels, "DBSCAN (succeeds)"),
    ):
        unique_m = sorted(set(labels_m))
        for li_m, lab_m in enumerate(unique_m):
            mask_m = labels_m == lab_m
            color_m = "#888888" if lab_m == -1 else cmap_m(li_m % 10)
            label_m_str = "noise" if lab_m == -1 else f"c{lab_m}"
            ax_m.scatter(X_moons[mask_m, 0], X_moons[mask_m, 1],
                         s=15, alpha=0.7, color=color_m, label=label_m_str)
        ax_m.set_title(title_m, fontsize=10)
        ax_m.set_xlabel("feature 0")
        ax_m.set_ylabel("feature 1")
        ax_m.legend(loc="best", fontsize=7)
    fig_m.suptitle("Moons dataset — non-convex clusters", fontsize=11)
    fig_m.tight_layout()
    mo.as_html(fig_m)
    return


@app.cell
def viz_blobs_pca(
    PCA,
    X_blobs,
    dbscan_b_labels,
    km_b_labels,
    mo,
    plt,
    y_blobs,
):
    pca_b = PCA(n_components=2, random_state=42)
    X_blobs_pca = pca_b.fit_transform(X_blobs)
    var_b = pca_b.explained_variance_ratio_

    fig_b, axes_b = plt.subplots(1, 3, figsize=(13, 4))
    ax_truth_b, ax_km_b, ax_db_b = axes_b
    cmap_b = plt.colormaps.get_cmap("tab10")
    for ax_b, labels_b, title_b in (
        (ax_truth_b, y_blobs, "Truth (held out)"),
        (ax_km_b, km_b_labels, "KMeans (succeeds)"),
        (ax_db_b, dbscan_b_labels, "DBSCAN (decent)"),
    ):
        unique_b = sorted(set(labels_b))
        for li_b, lab_b in enumerate(unique_b):
            mask_b = labels_b == lab_b
            color_b = "#888888" if lab_b == -1 else cmap_b(li_b % 10)
            label_b_str = "noise" if lab_b == -1 else f"c{lab_b}"
            ax_b.scatter(X_blobs_pca[mask_b, 0], X_blobs_pca[mask_b, 1],
                         s=12, alpha=0.7, color=color_b, label=label_b_str)
        ax_b.set_title(title_b, fontsize=10)
        ax_b.set_xlabel(f"PC1 ({var_b[0]:.0%})")
        ax_b.set_ylabel(f"PC2 ({var_b[1]:.0%})")
        ax_b.legend(loc="best", fontsize=7)
    fig_b.suptitle("Blobs dataset (8D) — projected to 2D via PCA", fontsize=11)
    fig_b.tight_layout()
    mo.as_html(fig_b)
    return


@app.cell
def anomaly_section(mo):
    mo.md(r"""
    ## 5. Anomaly detection with IsolationForest

    `IsolationForest` works on tabular data of any dimension. It
    randomly partitions the feature space and measures how few
    partitions are needed to isolate each point — outliers get
    isolated quickly.

    To make this concrete: inject 30 far-away points into the blobs
    dataset and see whether IsolationForest catches them.
    """)
    return


@app.cell
def anomaly_inject(IsolationForest, X_blobs, np):
    rng_anom = np.random.default_rng(42)
    n_anom = 30
    outliers_anom = rng_anom.uniform(low=-15, high=15, size=(n_anom, X_blobs.shape[1]))
    X_with_anom = np.vstack([X_blobs, outliers_anom])
    y_anom_truth = np.concatenate([np.zeros(len(X_blobs)), np.ones(n_anom)])

    iso = IsolationForest(contamination=0.02, random_state=42, n_jobs=-1)
    iso_pred = iso.fit_predict(X_with_anom)
    is_anom = (iso_pred == -1).astype(int)
    return X_with_anom, is_anom, n_anom, y_anom_truth


@app.cell
def anomaly_metrics(is_anom, mo, n_anom, y_anom_truth):
    tp_a = int(((is_anom == 1) & (y_anom_truth == 1)).sum())
    fp_a = int(((is_anom == 1) & (y_anom_truth == 0)).sum())
    fn_a = int(((is_anom == 0) & (y_anom_truth == 1)).sum())
    prec_a = tp_a / (tp_a + fp_a) if (tp_a + fp_a) > 0 else 0.0
    rec_a = tp_a / (tp_a + fn_a) if (tp_a + fn_a) > 0 else 0.0
    mo.md(
        f"""
    | | Value |
    |---|---|
    | planted outliers | `{n_anom}` |
    | flagged outliers | `{int(is_anom.sum())}` |
    | precision | `{prec_a:.3f}` |
    | recall | `{rec_a:.3f}` |

    With `contamination=0.02` (matching our injection rate),
    IsolationForest finds essentially all the outliers with a small
    number of false positives.
    """
    )
    return


@app.cell
def anomaly_plot(PCA, X_with_anom, is_anom, mo, plt):
    pca_anom = PCA(n_components=2, random_state=42)
    X_anom_pca = pca_anom.fit_transform(X_with_anom)

    fig_a, ax_a = plt.subplots(figsize=(7, 5.5))
    normal_mask_a = is_anom == 0
    ax_a.scatter(
        X_anom_pca[normal_mask_a, 0], X_anom_pca[normal_mask_a, 1],
        s=10, alpha=0.5, color="#4477aa", label=f"normal ({normal_mask_a.sum()})",
    )
    ax_a.scatter(
        X_anom_pca[~normal_mask_a, 0], X_anom_pca[~normal_mask_a, 1],
        s=50, alpha=0.9, color="#cc3311", marker="x",
        label=f"anomaly ({(~normal_mask_a).sum()})",
    )
    ax_a.set_xlabel("PC1")
    ax_a.set_ylabel("PC2")
    ax_a.set_title("IsolationForest anomaly detection in PCA space")
    ax_a.legend(loc="best")
    fig_a.tight_layout()
    mo.as_html(fig_a)
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    The unsupervised checklist:

    1. **Run `tabular-eda` first** — clustering on dirty data finds
       garbage clusters
    2. **Standardize features** before any distance-based algorithm
    3. **Choose K with silhouette score**, not visual elbow
    4. **Stability-check across random seeds** with pairwise ARI
    5. **Match the algorithm to the cluster shape** — KMeans for
       convex, DBSCAN for non-convex / noisy
    6. **`IsolationForest` for tabular anomaly detection**
    7. **PCA before clustering** when you have many features
       (curse of dimensionality)
    8. **Always look at example members of each cluster** — metrics
       say "internally consistent," not "meaningful"

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/unsupervised/` directory and your AI agent will
    follow the same workflow on your real unlabeled data.
    """)
    return


if __name__ == "__main__":
    app.run()
