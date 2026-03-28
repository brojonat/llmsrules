---
name: scikit-learn
description: Build ML pipelines with scikit-learn, including preprocessing, cross-validation, hyperparameter tuning, evaluation, and MLflow tracking. Use when training models, building pipelines, or running ML experiments.
---

# scikit-learn ML Pipelines

Build reproducible ML workflows with scikit-learn Pipelines, ColumnTransformers, cross-validation, and MLflow experiment tracking.

## Principles

- Prefer `Pipeline`/`ColumnTransformer` so preprocessing travels with the model
- Make runs deterministic: set `random_state` everywhere and seed numpy
- Keep train/val/test separation; use cross-validation for small datasets
- Persist the whole pipeline with `joblib` and load it for inference

## Project Layout

```
.
    data/
        raw/ processed/
    src/
        features.py    # build features, column lists
        model.py       # build pipeline, search spaces
        train.py       # fit, evaluate, persist
        predict.py     # load artifact, predict
    plots/
        roc_curve.png  rmse_hist.png
    artifacts/
        model.joblib   metrics.json  metadata.json
```

## Preprocessing Pipeline

```python
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, StandardScaler

numeric_features = ["age", "income"]
categorical_features = ["country", "segment"]

numeric_pipe = Pipeline([
    ("impute", SimpleImputer(strategy="median")),
    ("scale", StandardScaler()),
])

categorical_pipe = Pipeline([
    ("impute", SimpleImputer(strategy="most_frequent")),
    ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
])

preprocess = ColumnTransformer([
    ("num", numeric_pipe, numeric_features),
    ("cat", categorical_pipe, categorical_features),
])
```

## Training with Cross-Validation

```python
import numpy as np
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.linear_model import LogisticRegression

RANDOM_STATE = 42
np.random.seed(RANDOM_STATE)

X = clean_df[numeric_features + categorical_features]
y = clean_df["target"]

model = LogisticRegression(max_iter=1000, random_state=RANDOM_STATE)
clf = Pipeline([("prep", preprocess), ("model", model)])

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
)

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
cv_scores = cross_val_score(clf, X_train, y_train, cv=cv, scoring="roc_auc")
clf.fit(X_train, y_train)
```

## Hyperparameter Tuning

```python
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV
from scipy.stats import loguniform

# Grid search
grid = GridSearchCV(
    estimator=clf,
    param_grid={"model__C": [0.1, 0.3, 1.0, 3.0, 10.0], "model__penalty": ["l2"]},
    scoring="roc_auc", cv=cv, n_jobs=-1,
)
grid.fit(X_train, y_train)
best_clf = grid.best_estimator_

# Random search (wider sweeps)
rand = RandomizedSearchCV(
    estimator=clf,
    param_distributions={"model__C": loguniform(1e-3, 1e1)},
    n_iter=25, scoring="roc_auc", cv=cv, random_state=RANDOM_STATE, n_jobs=-1,
)
rand.fit(X_train, y_train)
best_clf = rand.best_estimator_
```

## Evaluation

### Classification

```python
from sklearn.metrics import classification_report, roc_auc_score, roc_curve
import matplotlib.pyplot as plt
from pathlib import Path
import json

y_pred = best_clf.predict(X_test)
y_prob = best_clf.predict_proba(X_test)[:, 1]
metrics = {"roc_auc": float(roc_auc_score(y_test, y_prob))}

print(classification_report(y_test, y_pred))

fpr, tpr, _ = roc_curve(y_test, y_prob)
plt.figure()
plt.plot(fpr, tpr, label=f"ROC AUC={metrics['roc_auc']:.3f}")
plt.plot([0, 1], [0, 1], "k--")
plt.xlabel("FPR"); plt.ylabel("TPR"); plt.legend()
Path("plots").mkdir(exist_ok=True)
plt.savefig("plots/roc_curve.png", dpi=150, bbox_inches="tight")

Path("artifacts").mkdir(exist_ok=True)
Path("artifacts/metrics.json").write_text(json.dumps(metrics, indent=2))
```

### Regression

```python
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

y_hat = best_clf.predict(X_test)
rmse = float(np.sqrt(mean_squared_error(y_test, y_hat)))
mae = float(mean_absolute_error(y_test, y_hat))
r2 = float(r2_score(y_test, y_hat))
```

## Persistence

```python
import joblib
from pathlib import Path

joblib.dump(best_clf, Path("artifacts/model.joblib"))

# Later, for inference:
loaded = joblib.load("artifacts/model.joblib")
preds = loaded.predict(X_new)
```

## MLflow Tracking

```python
import mlflow
import mlflow.sklearn

mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns"))
mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT", "default"))

with mlflow.start_run(run_name=os.getenv("RUN_NAME", "sklearn-logreg")) as run:
    best_clf.fit(X_train, y_train)
    y_pred = best_clf.predict(X_test)
    y_prob = best_clf.predict_proba(X_test)[:, 1]
    metrics = {"roc_auc": float(roc_auc_score(y_test, y_prob))}

    model_params = best_clf.named_steps["model"].get_params()
    mlflow.log_params({
        "estimator": best_clf.named_steps["model"].__class__.__name__,
        "C": model_params.get("C"),
        "penalty": model_params.get("penalty"),
        "random_state": model_params.get("random_state"),
    })

    mlflow.log_metrics(metrics)
    mlflow.sklearn.log_model(best_clf, artifact_path="model")

    run_id = run.info.run_id

# Load from a specific run
loaded = mlflow.sklearn.load_model(f"runs:/{run_id}/model")
```

## Tips

- Cache heavy preprocessing: `Pipeline(memory="./.cache")`
- Use `make_scorer` for custom metrics; log both CV and holdout metrics
- For imbalanced data: `class_weight="balanced"` or resampling
- Keep feature lists in one place (`src/features.py`) to avoid drift
- Implement features as table-in/table-out functions using `.pipe()` on DataFrames
