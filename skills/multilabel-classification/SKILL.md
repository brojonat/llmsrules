---
name: multilabel-classification
description: Build a production-ready multilabel classifier on tabular data using XGBoost wrapped in MultiOutputClassifier. Use when each row can have multiple labels simultaneously (tags, attributes, gene functions, content moderation categories, multi-disease detection). Covers hamming loss, per-label metrics, label co-occurrence, MultiOutputClassifier vs ClassifierChain, and per-label SHAP. Default to this for any tabular multilabel problem.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
-->

# Multilabel Classification with XGBoost (Done Right)

Multilabel ≠ multiclass. Multiclass picks **one** class from N. Multilabel
predicts **any subset** of N labels — each row can have zero, one, or
many labels on simultaneously. The metrics, the model wrapping, and the
failure modes are all different.

For tabular multilabel, **default to XGBoost wrapped in
`MultiOutputClassifier`**: it fits one independent XGBoost model per
label. Simple, fast, and competitive. Switch to `ClassifierChain` only
when labels are correlated and the ordering is meaningful.

## When to use this skill

- Each row can have multiple labels (tags on a post, attributes of a
  product, diseases in a patient, content moderation categories)
- The labels are NOT mutually exclusive
- The features are tabular
- You have at least a few hundred examples per label (rare labels will
  underperform — see pitfalls)

## When NOT to use this skill

- Each row has exactly one label → see `multiclass-classification`
- Two labels exactly → see `binary-classification`
- The labels are extremely strongly correlated and you have a natural
  ordering (e.g. hierarchical taxonomies) → consider tree-based
  multi-target methods or label powerset
- Extreme multilabel (> 1000 labels) → specialized algorithms outside
  this skill's scope

## Project layout

```
<project>/
├── data/
├── src/
│   ├── train.py         # ibis read → MultiOutputClassifier(XGBClassifier) → MLflow
│   ├── predict.py       # reload, return per-row label vector + per-label probas
│   └── plots.py         # label balance, co-occurrence, per-label metrics, cardinality
├── notebooks/
│   └── demo.py
└── mlruns/
```

## Data access — same ibis pattern

```python
import ibis

table = ibis.duckdb.connect().read_parquet("data/train.parquet")
feature_cols = [c for c in table.columns if c.startswith("feature_")]
label_cols = [c for c in table.columns if c.startswith("label_")]

data = (
    table
    .select(*feature_cols, *label_cols)
    .execute()
)
X = data[feature_cols]
Y = data[label_cols].to_numpy().astype(int)  # shape: (n_samples, n_labels)
```

The target `Y` is now a **matrix**, not a vector. That's the core
shape difference from the other classification skills.

## The pipeline — `MultiOutputClassifier`

```python
from sklearn.compose import ColumnTransformer
from sklearn.multioutput import MultiOutputClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

def build_pipeline(feature_cols, seed):
    return Pipeline([
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
                random_state=seed,
                n_jobs=-1,
            ),
            n_jobs=-1,  # parallelize across labels
        )),
    ])
```

`MultiOutputClassifier` fits **one independent binary classifier per
label** and stitches them together. Each underlying XGBoost is just a
binary classifier (`binary:logistic`), so all the binary-classification
skill's lessons apply per label.

## The five things that separate this from a tutorial

### 1. **Hamming loss is the primary metric, NOT subset accuracy**

Subset accuracy is "did we predict the *exact* set of labels for this
row?" — all of them right or none. On a 6-label problem with average
2 labels per row, even getting 90% per-label accuracy gives you only
~50% subset accuracy. **Subset accuracy is brutally pessimistic and
will mislead you about model quality.**

Hamming loss is the average per-label-slot error rate:

```python
from sklearn.metrics import hamming_loss, accuracy_score

ham = hamming_loss(Y_test, Y_pred)         # primary metric, lower = better
exact_match = accuracy_score(Y_test, Y_pred)  # subset accuracy — too strict alone
```

Report both, but optimize for hamming loss + per-label F1, not subset
accuracy.

### 2. **Four F1 averages — yes, four, not three**

For multilabel, sklearn's `f1_score` supports a fourth averaging
strategy you don't have in multiclass: **`samples`**. Each averaging
strategy answers a different question:

| Average | What it computes | When to use |
|---|---|---|
| **macro** | Unweighted mean of per-label F1 | All labels matter equally — rare labels drag the average down (good) |
| **micro** | F1 over the pooled `(sample, label)` predictions | Overall correctness across all label slots |
| **weighted** | Per-label F1 weighted by support | Weights toward common labels — hides rare-label failures |
| **samples** | Per-row F1, then averaged across rows | Per-row "did we get the labels mostly right?" — useful for tagging tasks |

```python
from sklearn.metrics import f1_score

f1_macro = f1_score(Y_test, Y_pred, average="macro", zero_division=0)
f1_micro = f1_score(Y_test, Y_pred, average="micro", zero_division=0)
f1_weighted = f1_score(Y_test, Y_pred, average="weighted", zero_division=0)
f1_samples = f1_score(Y_test, Y_pred, average="samples", zero_division=0)
```

**Default to macro F1** for the same reason as multiclass: it surfaces
rare-label failures that the other averages hide.

### 3. **Label co-occurrence matters — and points at when to use ClassifierChain**

If labels are independent (like make_multilabel_classification's
default), `MultiOutputClassifier` is optimal. If labels are correlated
("if label_3 is on, label_5 is also on 80% of the time"), the
independent-models assumption is suboptimal — you're throwing away
information.

The **conditional co-occurrence matrix** P(label_j | label_i) reveals
this:

```python
import numpy as np

n_labels = Y.shape[1]
cooc = np.zeros((n_labels, n_labels))
for i in range(n_labels):
    i_count = int(Y[:, i].sum())
    if i_count == 0:
        continue
    for j in range(n_labels):
        cooc[i, j] = float(((Y[:, i] == 1) & (Y[:, j] == 1)).sum() / i_count)
# cooc[i, j] = "given label_i is on, how often is label_j also on?"
```

If most off-diagonal entries hover around the marginal P(label_j),
labels are roughly independent → use `MultiOutputClassifier`. If
some off-diagonal entries are much higher than the marginals, labels
are correlated → consider `ClassifierChain`.

### 4. **`ClassifierChain` for correlated labels**

```python
from sklearn.multioutput import ClassifierChain

clf_chain = ClassifierChain(
    XGBClassifier(...),
    order=[0, 1, 2, 3, 4, 5],  # or "random" for cross-validated stability
    random_state=42,
)
```

`ClassifierChain` fits N binary classifiers in sequence, where each
classifier sees the previous classifiers' predictions as additional
features. This lets it learn label correlations like "if label_0 is
predicted, label_3 becomes more likely."

**Catch:** chain order matters. Different orders give different
results. Common practice: train multiple chains with random orders,
average their predictions (this is the "ensemble of classifier
chains" trick). For most production systems, `MultiOutputClassifier`
is good enough and much simpler — only switch to `ClassifierChain`
when you can measure that label correlations actually exist and
matter for your accuracy.

### 5. **Per-label monitoring — every label needs its own F1**

In multilabel, each label has its own positive rate, its own
imbalance, and its own difficulty. A model can have great macro F1
overall while one specific rare label is at F1 = 0.

**Always log per-label F1 to MLflow as separate metrics:**

```python
for i, lbl in enumerate(label_cols):
    f1_i = float(f1_score(Y_test[:, i], Y_pred[:, i], average="binary", zero_division=0))
    mlflow.log_metric(f"test_f1__{lbl}", f1_i)
```

This is the multilabel version of "per-class F1" from the multiclass
skill — same idea, but each label is genuinely independent so the
imbalance can vary wildly across labels.

## MLflow logging

| Kind | What |
|---|---|
| `params` | data path, n_rows, n_features, n_labels, label_columns, seed, hyperparameters |
| `metrics` | **hamming_loss** (primary), subset_accuracy, **F1 macro / micro / weighted / samples**, **per-label F1** (one metric per label), label cardinality (true vs predicted) |
| `tags` | data hash, label cardinality / density from sidecar |
| `artifacts` | model, label balance bar, co-occurrence heatmap, per-label metrics bar, label cardinality histogram (true vs pred) |

## Common pitfalls

1. **Reporting subset accuracy as the primary metric.** It's
   brutally strict and will make every model look bad. Use hamming
   loss + per-label F1.
2. **Using a per-row threshold instead of per-label.** Each label has
   its own optimal threshold. `MultiOutputClassifier`'s default is
   0.5 per label, which is rarely right for any of them. For
   cost-sensitive applications, tune per-label thresholds on a
   validation set.
3. **Not parallelizing across labels.** `MultiOutputClassifier(...,
   n_jobs=-1)` fits labels in parallel — it's free speed for
   independent labels.
4. **Forgetting `zero_division=0`.** If a label has no positives in
   the test set (or no predicted positives), F1 is undefined. The
   default is to warn; set `zero_division=0` to silently treat
   undefined F1 as 0.
5. **Imbalanced rare labels with no special handling.** Per-label
   `scale_pos_weight` works, but `MultiOutputClassifier` doesn't
   make it easy to vary per label. Either use `sample_weight` (one
   global weight per row) or train per-label models manually for
   the imbalanced labels.
6. **Confusing multilabel with multiclass.** Multilabel: `Y.shape ==
   (n_samples, n_labels)` with binary entries. Multiclass:
   `y.shape == (n_samples,)` with integer labels in `[0, n_classes)`.
   Pass the wrong shape to `f1_score` and you'll get nonsense.
7. **Ignoring the label cardinality drift.** If the true average is
   2.0 labels per row and the model predicts 1.2, it's
   under-predicting positives across the board — usually a
   threshold-tuning problem.

## Worked example

See `demo.py` (marimo notebook). It generates a 6-label tabular
classification problem with varying per-label positive rates (13% to
53%), fits XGBoost in a `MultiOutputClassifier`, and walks through:

- Per-label positive rate bar
- Label co-occurrence heatmap (so the buyer can decide if
  ClassifierChain would help)
- Hamming loss vs subset accuracy on the test set
- All four F1 averages side by side
- Per-label F1 bar chart (showing the rare labels lag)
- True vs predicted label cardinality histogram (catches over- /
  under-prediction)
