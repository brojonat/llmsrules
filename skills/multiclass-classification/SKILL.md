---
name: multiclass-classification
description: Build a production-ready multiclass classifier on tabular data using XGBoost. Use when the user needs to predict one of several discrete classes from tabular features (product category, sentiment level, customer segment, intent, fault type). Covers per-class metrics, confusion matrix analysis, sample weighting for imbalance, top-K accuracy, and SHAP. Default to this for any tabular multiclass problem.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
-->

# Multiclass Classification with XGBoost (Done Right)

For tabular multiclass classification, **default to XGBoost**. Same
reasoning as binary: it dominates Kaggle and real-world tabular
benchmarks, handles class imbalance with `sample_weight`, and gives
you SHAP-based explanations as a side effect.

The differences from binary are real and worth understanding:

- **`objective="multi:softprob"`** + `num_class=N` instead of
  `binary:logistic`
- **Per-class metrics**, not just accuracy. Accuracy can hide a
  catastrophic failure on a minority class.
- **`sample_weight` per row** for imbalance (no `scale_pos_weight`
  for multiclass)
- **Confusion matrix** is the most important diagnostic — *which*
  classes get confused matters more than how many
- **`predict_proba`** returns shape `(n_samples, n_classes)` and you
  often want top-K, not just argmax

## When to use this skill

- The target has > 2 discrete classes (sentiment 1-5, product
  category A-Z, intent buckets, fault types)
- The classes are mutually exclusive (each example belongs to
  exactly one class — multilabel is a different skill)
- The features are tabular
- You have at least a few hundred examples per class

## When NOT to use this skill

- Binary target → see `binary-classification`
- Multiple labels per example → see `multilabel-classification`
- Classes have natural ordering (rating 1-5) → consider an ordinal
  regression model (not XGBoost) — XGBoost will work but ignores the
  order
- Very many classes (> 100) and you only care about top-K → consider
  hierarchical softmax or learning-to-rank approaches

## Project layout

```
<project>/
├── data/                # input parquet/csv
├── src/
│   ├── train.py         # Pipeline + XGBClassifier(multi:softprob) + MLflow
│   ├── predict.py       # reload, return top-K predictions per row
│   └── plots.py         # confusion matrix, per-class metrics, ROC OvR, SHAP
├── notebooks/
│   └── demo.py          # marimo walkthrough
└── mlruns/
```

## Data access — ibis at the source

Same pattern as the other tabular bundles. Use ibis to read; materialize
once with `.execute()` for sklearn:

```python
import ibis

table = ibis.duckdb.connect().read_parquet("data/train.parquet")
feature_cols = [c for c in table.columns if c.startswith("feature_")]
data = (
    table
    .select(*feature_cols, "target")
    .execute()
)
X = data[feature_cols]
y = data["target"].astype(int)
n_classes = int(y.max()) + 1
```

## The pipeline

```python
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

def build_pipeline(feature_cols, n_classes, seed):
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
            num_class=n_classes,
            eval_metric="mlogloss",
            random_state=seed,
            n_jobs=-1,
        )),
    ])
```

The only changes from binary are `objective`, `num_class`, and
`eval_metric`.

## The five things that separate this from a tutorial

### 1. **Per-class metrics — never just accuracy**

Accuracy on a 5-class problem can be 80% while the model completely
fails on one class. You need per-class precision, recall, F1, and
support:

```python
from sklearn.metrics import precision_recall_fscore_support, classification_report

precision, recall, f1, support = precision_recall_fscore_support(
    y_test, y_pred, labels=list(range(n_classes)), zero_division=0,
)
print(classification_report(y_test, y_pred, digits=3))
```

A failing minority class shows up as **F1 ≈ 0** for that class even
when overall accuracy looks fine. **Always log per-class F1 to MLflow**,
not just the macro/micro averages.

### 2. **Macro vs micro vs weighted F1 — three different decisions**

These three averaging strategies sound similar but encode very
different priorities:

| Average | What it computes | When to use |
|---|---|---|
| **macro** | Unweighted mean of per-class F1 | All classes matter equally — minority classes drag the average down |
| **micro** | F1 over the full pooled prediction set (= accuracy on single-label multiclass) | You only care about overall correctness |
| **weighted** | Mean of per-class F1 weighted by class support | Class proportions reflect real-world frequencies; minority misses don't matter much |

```python
from sklearn.metrics import f1_score

f1_macro = f1_score(y_test, y_pred, average="macro")
f1_micro = f1_score(y_test, y_pred, average="micro")
f1_weighted = f1_score(y_test, y_pred, average="weighted")
```

**Default to macro F1** when each class is independently important.
A model with 90% accuracy and 0% F1 on a minority class is bad —
macro F1 surfaces that, weighted F1 hides it.

### 3. **`sample_weight` per row, not `scale_pos_weight`**

XGBoost's `scale_pos_weight` only works for binary classification.
For multiclass, you pass an explicit `sample_weight` array — one
weight per row — to `fit`. The standard "balanced" choice gives each
class an equal total weight regardless of its frequency:

```python
from sklearn.utils.class_weight import compute_sample_weight

sample_weight = compute_sample_weight(class_weight="balanced", y=y_train)
pipeline.fit(X_train, y_train, clf__sample_weight=sample_weight)
```

The `clf__` prefix routes the parameter to the `clf` step of the
Pipeline. Without it, the Pipeline doesn't know which step you mean.

### 4. **Confusion matrix is the primary diagnostic**

For multiclass, the confusion matrix tells you **which** classes get
confused for which — and that's the input to feature engineering.
"Class 2 is confused with class 4 60% of the time" tells you to
look for features that distinguish those two.

```python
from sklearn.metrics import confusion_matrix

cm = confusion_matrix(y_test, y_pred, labels=list(range(n_classes)))
# Normalize by row to see "given true class i, what % goes where"
cm_norm = cm.astype(float) / cm.sum(axis=1, keepdims=True)
```

Always plot **two** confusion matrices: the raw counts and the
row-normalized version. Counts show the magnitude of errors; the
normalized version shows the per-class structure.

### 5. **Top-K accuracy + SHAP per class**

For problems with many classes, top-K accuracy is often the actual
product metric — "did the right answer appear in the top 3
suggestions?" rather than "was the top-1 prediction exactly right?":

```python
from sklearn.metrics import top_k_accuracy_score

top_3 = top_k_accuracy_score(y_test, y_proba, k=3, labels=list(range(n_classes)))
```

For SHAP, multiclass returns a **3D** array `(n_samples, n_features,
n_classes)` instead of binary's 2D. Slice to one class to plot:

```python
import shap

explainer = shap.TreeExplainer(clf)
shap_values = explainer(X_test_sample)
# shap_values.values shape: (n_samples, n_features, n_classes)

# Pick a class to explain
class_idx = 0
sliced = shap.Explanation(
    values=shap_values.values[:, :, class_idx],
    base_values=shap_values.base_values[:, class_idx],
    data=shap_values.data,
    feature_names=feature_cols,
)
shap.summary_plot(sliced, X_test_sample, feature_names=feature_cols)
```

The class-level SHAP explanation tells you "which features push
predictions toward / away from class 0?" Repeat per class for a full
picture, or focus on the class you care about most.

## MLflow logging

Every run logs:

| Kind | What |
|---|---|
| `params` | data path, n_rows, n_features, n_classes, seed, hyperparameters, **use_sample_weights** |
| `metrics` | accuracy, **F1 macro / micro / weighted** (all three), log-loss, top-K accuracy, **per-class F1** (one metric per class) |
| `tags` | data hash |
| `artifacts` | model, class balance bar, **confusion matrix (raw + normalized)**, per-class metrics bar chart, ROC OvR, SHAP summary per class |

The **per-class F1** logging is what catches the silent-minority-class
failure mode. Don't skip it.

## Common pitfalls

1. **Reporting only accuracy.** Hides minority-class failure. Use F1
   macro alongside accuracy.
2. **Skipping the confusion matrix.** It's the most informative
   single plot for multiclass debugging.
3. **Using `class_weight="balanced"` on the pipeline instead of
   passing `sample_weight` to `fit`.** XGBoost's wrapper accepts
   `sample_weight`; the older sklearn `class_weight` parameter is
   ignored.
4. **Forgetting `num_class`.** If you set `objective="multi:softprob"`
   but forget `num_class=N`, XGBoost will infer it from the labels —
   usually correctly, but explicit is safer.
5. **Treating `predict_proba` output as 2D when it's 3D for SHAP.**
   Multiclass SHAP returns one value per (sample, feature, class)
   triple. Slice before plotting.
6. **Using accuracy as the early-stopping metric on imbalanced data.**
   Use `mlogloss` or weighted F1 instead.
7. **Ignoring class order in ordinal targets.** If your classes have
   an order (1 < 2 < 3 < 4 < 5), XGBoost still treats them as
   nominal. It works but you're throwing away information. Consider
   ordinal regression for true ordinal data.

## Worked example

See `demo.py` (marimo notebook). It generates a 5-class imbalanced
synthetic dataset (the most-frequent class is 5× more common than
the rarest), fits XGBoost two ways — without and with
`sample_weight` — and shows the difference in per-class F1. The
demo's punchline is that **on imbalanced data, the minority-class
F1 is dramatically improved by `sample_weight` even though overall
accuracy barely changes** — the exact thing macro F1 catches and
weighted F1 hides.
