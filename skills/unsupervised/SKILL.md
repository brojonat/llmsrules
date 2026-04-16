---
name: unsupervised
description: Find structure in unlabeled tabular data — clustering with KMeans / GMM / DBSCAN and proper K selection, IsolationForest anomaly detection, and PCA dimensionality reduction. Use when the user has tabular data without a target column and wants to discover segments, find anomalies, or reduce dimensions. Always run tabular-eda first to profile the data.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
-->

# Unsupervised Learning — Clustering, Anomalies, and Dimensionality Reduction

When the data has no target column, you're in unsupervised territory.
Three things you can do with it:

1. **Cluster** to find segments / groups
2. **Detect anomalies** to find outliers / fraud / failures
3. **Reduce dimensions** to visualize, denoise, or compress

Each comes with its own gotchas. The biggest one: there's no single
"accuracy" metric, so you have to be deliberate about how you evaluate.

## When to use this skill

- You have tabular data without a target column
- You want to find groups (customer segments, anomalies, behavioral
  modes)
- You want to visualize high-dimensional data
- You want to denoise or compress features before downstream modeling

## When NOT to use this skill

- You have labels — use a supervised skill (binary, multiclass, etc.)
- The data is text / images / audio / time series — different rules
- You need a single "best" cluster assignment with no validation loop —
  unsupervised always needs human judgment in the loop

## Always run `tabular-eda` first

Profile the data before clustering. The unsupervised skill assumes:
- Numeric features (categoricals must be encoded first)
- No leakage / no target column
- Scaled features (clustering algorithms are distance-based)
- Missing values handled

If you skip EDA you'll find clusters that just reflect data quality
issues (e.g. one cluster = "rows with `feature_3` missing").

## The clustering pipeline

```python
from sklearn.cluster import DBSCAN, KMeans
from sklearn.compose import ColumnTransformer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

preprocess = ColumnTransformer([("num", StandardScaler(), numeric_cols)])
X = preprocess.fit_transform(df[numeric_cols])

# 1. Choose K via silhouette score (NOT just visual elbow)
k_values = list(range(2, 11))
silhouettes = []
for k in k_values:
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    silhouettes.append(silhouette_score(X, km.fit_predict(X)))
best_k = k_values[int(np.argmax(silhouettes))]

# 2. Stability check at best K
stability_runs = []
for seed in range(8):
    km = KMeans(n_clusters=best_k, n_init=10, random_state=seed)
    stability_runs.append(km.fit_predict(X))
ari_mean = np.mean([
    adjusted_rand_score(stability_runs[i], stability_runs[j])
    for i in range(8) for j in range(i + 1, 8)
])
# If ari_mean < 0.7, the clustering is unstable — try a different K or algorithm

# 3. Final clustering
labels = KMeans(n_clusters=best_k, n_init=10, random_state=42).fit_predict(X)
```

## The five things that separate this from a tutorial

### 1. **Choose K with silhouette score, not just visual elbow**

The classic "elbow method" plots inertia (within-cluster sum of
squares) vs K and looks for the kink. **It's subjective.** Two people
can disagree on where the elbow is. The silhouette score is
quantifiable: it measures how well each point fits its assigned
cluster vs the next nearest cluster, averaged across all points.

```python
from sklearn.metrics import silhouette_score

silhouettes = []
for k in range(2, 11):
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    labels = km.fit_predict(X)
    silhouettes.append(silhouette_score(X, labels))
best_k = 2 + int(np.argmax(silhouettes))  # +2 because k starts at 2
```

A silhouette of 1.0 = perfect separation; 0 = overlapping clusters;
negative = points are closer to other clusters than their own.
**Below ~0.3 means your clustering is questionable** regardless of
which K you pick.

Plot both elbow and silhouette curves so you have both signals, but
pick K from the silhouette.

### 2. **Stability check across multiple `random_state`s**

KMeans is sensitive to initialization. Run it with several seeds and
compute pairwise Adjusted Rand Index (ARI) between runs. **If the
mean off-diagonal ARI is below ~0.7, your clustering is unstable** —
the algorithm is picking different "clusters" each time, which means
either K is wrong or the algorithm is wrong for your data.

```python
from sklearn.metrics import adjusted_rand_score
import numpy as np

n_runs = 8
labels_per_run = []
for seed in range(n_runs):
    km = KMeans(n_clusters=best_k, n_init=10, random_state=seed)
    labels_per_run.append(km.fit_predict(X))

ari_matrix = np.array([
    [adjusted_rand_score(labels_per_run[i], labels_per_run[j])
     for j in range(n_runs)] for i in range(n_runs)
])
mean_ari = ari_matrix[~np.eye(n_runs, dtype=bool)].mean()
# Stable: mean_ari ≈ 1.0
# Unstable: mean_ari < 0.7 → reconsider K or algorithm
```

`n_init=10` already runs KMeans 10 times internally and picks the best
by inertia. The stability check is **on top of that** — does the best
of those 10 differ between random seeds? If yes, no amount of `n_init`
will save you.

### 3. **KMeans assumes spherical convex clusters**

KMeans implicitly assumes:
- Clusters are convex (no concave shapes)
- Clusters are roughly the same size
- Clusters are roughly the same density
- Clusters are roughly spherical (isotropic)

When these don't hold, KMeans fails:

| Data shape | KMeans | DBSCAN | GMM |
|---|---|---|---|
| Spherical convex blobs | ✓ best | ✓ | ✓ |
| Elliptical clusters | ✗ (drags boundaries) | ✓ | ✓ best |
| Concentric circles / moons | ✗ | ✓ best | ✗ |
| Density-based clusters | ✗ | ✓ best | ✗ |
| Wildly varying cluster sizes | ✗ | ✓ | partial |
| Many noise points | ✗ | ✓ best (labels noise as -1) | ✗ |

**Default to KMeans for blob-like data; switch to DBSCAN for non-convex
or noisy data.** Use GMM when clusters are elliptical (e.g. correlated
features within each cluster).

### 4. **IsolationForest for anomaly detection**

For anomalies in tabular data, `IsolationForest` is the default. It
randomly partitions the feature space and measures how few partitions
are needed to isolate each point — outliers get isolated quickly.
Works on high-dim data, no distribution assumptions, fast.

```python
from sklearn.ensemble import IsolationForest

iso = IsolationForest(
    contamination=0.02,  # expected fraction of outliers
    random_state=42,
    n_jobs=-1,
)
predictions = iso.fit_predict(X)  # -1 = outlier, +1 = inlier
is_anomaly = (predictions == -1)
# Or get continuous scores:
scores = iso.score_samples(X)  # higher = more normal
```

The `contamination` parameter is your prior on the outlier fraction.
Set it to your best guess; if you genuinely don't know, start at 0.05
and tune. **Don't set it too high** or you'll flag normal points as
outliers.

Alternatives:
- `OneClassSVM` — older, slower, doesn't scale beyond ~10k rows
- `LocalOutlierFactor` — density-based, good for local anomalies
- `EllipticEnvelope` — assumes Gaussian, fast, breaks on non-Gaussian
  data

### 5. **PCA before clustering for high-dim data**

In high dimensions, all pairwise distances become similar — the
"curse of dimensionality." Distance-based algorithms (KMeans, DBSCAN,
LOF) lose discriminative power. The fix is PCA before clustering:

```python
from sklearn.decomposition import PCA

# Reduce to enough components to explain ~90% of variance
pca = PCA(n_components=0.90, random_state=42)
X_reduced = pca.fit_transform(X)

km = KMeans(n_clusters=best_k, n_init=10, random_state=42)
labels = km.fit_predict(X_reduced)
```

Rule of thumb: if you have more than ~20 features, PCA first. Below
that, decide based on whether your features are informative or noisy.

For visualization (always 2D or 3D), use `PCA(n_components=2)`. For
non-linear structure, use UMAP or t-SNE — but those are visualization
tools, not preprocessing for clustering (UMAP changes inter-point
distances).

## Evaluation metrics

**Without ground-truth labels** (the usual case):

| Metric | What it measures | Range | Higher is better |
|---|---|---|---|
| Silhouette score | How well points fit their cluster vs the next | [-1, 1] | yes |
| Calinski-Harabasz | Between/within cluster variance ratio | [0, ∞) | yes |
| Davies-Bouldin | Average cluster similarity | [0, ∞) | no (lower) |

**With ground-truth labels** (for validation on synthetic data):

| Metric | What it measures | Range | Higher is better |
|---|---|---|---|
| Adjusted Rand Index (ARI) | Pairwise agreement vs truth, corrected for chance | [-1, 1] | yes |
| Normalized Mutual Information (NMI) | MI between cluster labels and truth, normalized | [0, 1] | yes |
| Homogeneity / Completeness | Cluster purity / class recovery | [0, 1] | yes |

ARI is the most commonly reported "did clustering recover the true
groups" metric. Use it on synthetic data to validate the pipeline,
even though you won't have it in production.

## Common pitfalls

1. **Skipping EDA.** You'll cluster on data quality artifacts.
2. **Not standardizing features.** Distance metrics will be dominated
   by whichever feature has the largest scale. Always
   `StandardScaler` first.
3. **Trusting the elbow method alone.** Use silhouette.
4. **Ignoring stability.** A clustering that changes wildly with the
   random seed isn't a clustering — it's noise.
5. **Using KMeans on non-convex data.** Use DBSCAN.
6. **Setting `contamination` too high in IsolationForest.** You'll
   flag normal points.
7. **PCA on already-clean low-dim data.** Adds noise. Only PCA when
   you have many features.
8. **Treating cluster labels as meaningful by default.** Cluster 0
   doesn't mean anything until **you** look at its members and decide
   what it represents (e.g. "this cluster looks like 'high-value
   weekday users'"). The algorithm gives you groups; the
   interpretation is on you.

## Worked example

See `demo.py` (marimo notebook). It generates **two** synthetic
datasets to make the algorithm-vs-shape lesson concrete:

- **`make_blobs`** (4 well-separated convex clusters) — KMeans wins,
  DBSCAN also works
- **`make_moons`** (two interleaved half-moons) — KMeans **fails**
  (it can't represent non-convex clusters), DBSCAN nails it

Then it walks through K selection via silhouette, the stability
check, and IsolationForest anomaly detection on injected outliers.
The end shows the same data in PCA space colored by each method's
labels so the difference is visible.

## After unsupervised: what to do next

Cluster labels are typically used for one of:
- **Customer segmentation**: each cluster gets a persona, marketing
  uses it
- **Feature engineering for supervised models**: cluster ID becomes a
  categorical feature in a classifier
- **Anomaly triage**: flag outliers for human review
- **Data exploration**: confirm that your data has the structure you
  expected (or doesn't, which is more interesting)

Whatever you do with the labels, **always look at example members of
each cluster** before believing the clustering. The metrics tell you
"this clustering is internally consistent" — they don't tell you
"these clusters are meaningful for your problem."
