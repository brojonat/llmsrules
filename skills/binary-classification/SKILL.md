---
name: binary-classification
description: Build a production-ready binary classifier on tabular data using XGBoost. Use when the user needs to predict a binary outcome from tabular features (churn, fraud, conversion, default, click). Covers class imbalance, threshold tuning, calibration verification, and SHAP feature importance. Default to this for any binary classification task on tabular data.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
-->

# Binary Classification with XGBoost (Done Right)

For tabular binary classification, **default to XGBoost**. It dominates
Kaggle and real-world benchmarks for tabular data, handles missing
values and mixed feature types essentially for free, and gives you
SHAP-based explanations as a side effect. This skill covers the four
things that separate "ROC-AUC on a notebook" from "a model you can
deploy and trust."

## When to use this skill

- The target is binary (0/1, yes/no, churned/retained, fraud/legit)
- The features are tabular (numbers, categories, dates) — not images,
  text, or audio
- You have at least a few hundred labeled examples
- You care about both **discrimination** (ranking positives above
  negatives) and **calibration** (probabilities mean what they say)

## When NOT to use this skill

- Multi-class or multi-label problems → see those skills
- Tiny datasets (< 100 rows) → use a regularized linear model with CV
- Time-series with strong temporal structure → use time-series methods,
  not XGBoost on a flat dataframe
- You want a fully-Bayesian posterior over predictions for downstream
  decision analysis → use PyMC, not XGBoost

## Project layout

```
<project>/
├── data/                # input parquet/csv
├── src/
│   ├── train.py         # ibis read → Pipeline + XGBClassifier → MLflow log
│   ├── predict.py       # reload model, apply tuned threshold
│   └── plots.py         # ROC, PR, calibration, threshold sweep, SHAP
├── notebooks/
│   └── demo.py          # marimo walkthrough
└── mlruns/              # MLflow tracking store (gitignored)
```

## Data access — ibis at the source, pandas at the sklearn boundary

Use **ibis** (`ibis-framework[duckdb]`) to read data, compute summaries
like class balance, and do any feature engineering. Materialize with
`.execute()` exactly once, just before passing data to sklearn:

```python
import ibis

table = ibis.duckdb.connect().read_parquet("data/train.parquet")
feature_cols = [c for c in table.columns if c.startswith("feature_")]

# Class balance via an ibis aggregation (pushed down to DuckDB)
class_stats = (
    table
    .aggregate(
        n_pos=table.target.sum().cast("int64"),
        n_total=table.count(),
    )
    .execute()
    .iloc[0]
)
n_pos = int(class_stats["n_pos"])
scale_pos_weight = (int(class_stats["n_total"]) - n_pos) / n_pos

# Materialize features + target — the ibis → pandas boundary
data = (
    table
    .select(*feature_cols, "target")
    .execute()
)
X = data[feature_cols]
y = data["target"].astype(int)
```

Sklearn estimators accept pandas DataFrames and numpy arrays but
**not** ibis Table objects directly — the `.execute()` call is the
deliberate handoff. For data already in memory (e.g.
`make_classification` in a tutorial / demo), pandas via a chained
expression is fine; ibis only earns its keep when the source is a file
or database.

Always prefer **fluent chained style** over imperative mutations:

```python
# GOOD — single chain, reads as a recipe
data = (
    table
    .filter(table.target.notnull())
    .select(*feature_cols, "target")
    .execute()
)

# BAD — fragmented across mutations
table = table.filter(table.target.notnull())
table = table.select(*feature_cols, "target")
data = table.execute()
```

## The pipeline

Always wrap preprocessing inside the sklearn `Pipeline` so it travels
with the model on save/load:

```python
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from xgboost import XGBClassifier

def build_pipeline(scale_pos_weight: float, seed: int) -> Pipeline:
    return Pipeline([
        ("preprocess", ColumnTransformer([
            ("num", StandardScaler(), numeric_cols),
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_cols),
        ])),
        ("clf", XGBClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            scale_pos_weight=scale_pos_weight,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=seed,
            n_jobs=-1,
        )),
    ])
```

XGBoost doesn't *need* feature scaling, but keeping the StandardScaler
in the pipeline lets you swap in a logistic-regression baseline without
changing anything else. Pipelines are about consistency, not speed.

## The four things that separate this from a tutorial

### 1. Class imbalance — `scale_pos_weight`, not resampling

If your positive class is 5% of the data, the loss function will mostly
be driven by the negative class and the model will under-predict
positives. The XGBoost-native fix:

```python
n_pos = int(y_train.sum())
n_neg = int(len(y_train) - n_pos)
scale_pos_weight = n_neg / n_pos
```

This rescales the gradient contribution of positive examples so they
matter as much as the negatives, **without** discarding data
(undersampling) or fabricating it (SMOTE). For most tabular problems
this is all you need.

Don't use SMOTE on tabular data unless you've measured that it helps —
synthetic minority points often degrade calibration.

### 2. Threshold tuning — 0.5 is rarely the right cutoff

`predict()` uses 0.5 as the decision threshold. **You almost never
want this.** Sweep thresholds and pick the one that optimizes the
metric your business actually cares about:

```python
import numpy as np
from sklearn.metrics import f1_score, precision_score, recall_score

proba = pipeline.predict_proba(X_val)[:, 1]
thresholds = np.linspace(0.01, 0.99, 99)

# Optimize for F1 (balanced precision and recall)
f1s = [f1_score(y_val, (proba >= t).astype(int)) for t in thresholds]
best_threshold = thresholds[int(np.argmax(f1s))]
```

Cost-weighted variants (when false positives and false negatives have
different dollar costs):

```python
# E.g. fraud detection where each FN costs $100 and each FP costs $5
def expected_cost(y_true, y_pred, fp_cost, fn_cost):
    fp = ((y_pred == 1) & (y_true == 0)).sum()
    fn = ((y_pred == 0) & (y_true == 1)).sum()
    return fp * fp_cost + fn * fn_cost

best_threshold = min(
    thresholds,
    key=lambda t: expected_cost(y_val, (proba >= t).astype(int), 5, 100),
)
```

**Tune the threshold on a held-out validation set**, never on the test
set you'll use to report final numbers. (For brevity the worked example
in `demo.py` uses the test set; in production keep them separate.)

### 3. Calibration verification — Brier score + reliability diagram

A model can have great ROC-AUC and still be miscalibrated (predicted
P=0.8 doesn't actually mean 80% of those examples are positive). Check
two things:

- **Brier score**: mean squared error between predicted probabilities
  and binary outcomes. Lower is better. Below ~0.1 is usually fine for
  most problems.
- **Reliability diagram**: bin predictions by probability, plot
  predicted vs observed. Should hug the diagonal.

```python
from sklearn.metrics import brier_score_loss
from sklearn.calibration import calibration_curve

brier = brier_score_loss(y_test, proba)
frac_pos, mean_pred = calibration_curve(y_test, proba, n_bins=10, strategy="quantile")
```

XGBoost with `objective="binary:logistic"` is usually well-calibrated
out of the box. If it isn't, wrap in `CalibratedClassifierCV`:

```python
from sklearn.calibration import CalibratedClassifierCV
calibrated = CalibratedClassifierCV(pipeline, method="isotonic", cv="prefit")
calibrated.fit(X_val, y_val)
```

Use `method="sigmoid"` for tiny validation sets, `"isotonic"` for
larger ones (>1000 examples).

### 4. SHAP for feature importance

Don't use XGBoost's built-in `feature_importances_` — it has a bunch
of known biases (high-cardinality features look more important than
they are). Use SHAP instead, which has a fast `TreeExplainer` for tree
models:

```python
import shap

# Use the underlying XGBClassifier (not the Pipeline)
clf = pipeline.named_steps["clf"]
preprocessor = pipeline.named_steps["preprocess"]
X_test_t = preprocessor.transform(X_test.iloc[:200])

explainer = shap.TreeExplainer(clf)
shap_values = explainer(X_test_t)

# Global summary (beeswarm)
shap.summary_plot(shap_values, X_test_t, feature_names=feature_cols)

# Local explanation for a single prediction
shap.plots.waterfall(shap_values[0])
```

For deployment: log SHAP values alongside predictions. If a model
denies a loan, you should be able to explain *which features* drove
that decision.

## MLflow logging

For every run, log:

| Kind | What |
|---|---|
| `params` | data path, n_rows, n_features, **scale_pos_weight**, **best_f1_threshold** (after tuning), seed, hyperparameters |
| `metrics` | ROC-AUC, **PR-AUC** (more honest than ROC-AUC for imbalanced), log-loss, **Brier score**, F1 at default 0.5, F1 at tuned threshold, precision and recall at tuned threshold |
| `tags` | data hash, imbalance ratio |
| `artifacts` | model (`mlflow.sklearn.log_model`), ROC + PR plot, calibration plot, threshold sweep, confusion matrix at tuned threshold, SHAP summary plot |

PR-AUC is more honest than ROC-AUC for imbalanced problems — a model
can have ROC-AUC = 0.95 while being almost useless on a 1% positive
class. Always log both.

## Common pitfalls

1. **Using `accuracy` as the metric.** On a 95/5 split, predicting
   "always negative" gets 95% accuracy and is completely useless.
   Use ROC-AUC, PR-AUC, or F1 with a tuned threshold.
2. **Tuning the threshold on the test set.** This leaks information
   into your reported numbers. Use a separate validation set.
3. **Skipping calibration check.** A miscalibrated model's "P=0.7"
   isn't 70% — it might be 50%. This breaks any downstream code that
   uses the probability for thresholds, expected utility, or risk
   scoring.
4. **Trusting `feature_importances_`.** Use SHAP instead.
5. **Using SMOTE on tabular data without measuring impact.** Often
   degrades calibration and rarely helps over `scale_pos_weight`.
6. **Letting features leak the target.** If a feature is computed
   *after* the prediction time (e.g. `total_charges` for a churn
   prediction made before churn), you'll get suspiciously high AUC in
   training and a useless model in production.
7. **Not stratifying the train/test split.** Use
   `train_test_split(..., stratify=y)` to keep the class balance
   consistent across splits.

## Worked example

See `demo.py` (marimo notebook). It generates a synthetic binary
classification dataset with 15% positive class, fits XGBoost with
`scale_pos_weight`, tunes the threshold for F1, plots calibration and
SHAP, and includes a baseline `LogisticRegression` cell so you can see
*why* XGBoost wins on this problem.
