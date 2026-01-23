## Principles

- Prefer `Pipeline`/`ColumnTransformer` so preprocessing travels with the model.
- Make runs deterministic: set `random_state` everywhere and seed numpy.
- Keep train/val/test separation. Use cross-validation for small datasets.
- Persist the whole pipeline with `joblib` and load it for inference.

## Suggested layout (see also project-layout.mdc)

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

## Data recipe

```python
import pandas as pd

def data_recipe(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Return a cleaned, modeling-ready dataframe."""
    df = raw_df.copy()
    # Example: trim, normalize, derive features
    # df["text"] = df["text"].str.strip()
    # df["amount_log"] = (df["amount"].clip(lower=1)).pipe(np.log)
    return df

# usage
clean_df = data_recipe(raw_df)
```

## Preprocessing and pipeline

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

## Model, training, validation

```python
import numpy as np
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.linear_model import LogisticRegression

RANDOM_STATE = 42
np.random.seed(RANDOM_STATE)

X = clean_df[numeric_features + categorical_features]
y = clean_df["target"]

model = LogisticRegression(max_iter=1000, random_state=RANDOM_STATE)
clf = Pipeline([
    ("prep", preprocess),
    ("model", model),
])

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
)

cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
cv_scores = cross_val_score(clf, X_train, y_train, cv=cv, scoring="roc_auc")
clf.fit(X_train, y_train)
```

## Hyperparameter tuning

```python
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV
from scipy.stats import loguniform

param_grid = {
    "model__C": [0.1, 0.3, 1.0, 3.0, 10.0],
    "model__penalty": ["l2"],
}

grid = GridSearchCV(
    estimator=clf,
    param_grid=param_grid,
    scoring="roc_auc",
    cv=cv,
    n_jobs=-1,
)
grid.fit(X_train, y_train)
best_clf = grid.best_estimator_
```

Random search (useful for wider sweeps):

```python
rand = RandomizedSearchCV(
    estimator=clf,
    param_distributions={"model__C": loguniform(1e-3, 1e1)},
    n_iter=25,
    scoring="roc_auc",
    cv=cv,
    random_state=RANDOM_STATE,
    n_jobs=-1,
)
rand.fit(X_train, y_train)
best_clf = rand.best_estimator_
```

## Evaluation

Classification example:

```python
from sklearn.metrics import (
    classification_report,
    roc_auc_score,
    roc_curve,
)
import json
from pathlib import Path
import matplotlib.pyplot as plt

y_pred = best_clf.predict(X_test)
y_prob = best_clf.predict_proba(X_test)[:, 1]

metrics = {
    "roc_auc": float(roc_auc_score(y_test, y_prob)),
}

print(classification_report(y_test, y_pred))

fpr, tpr, _ = roc_curve(y_test, y_prob)
plt.figure()
plt.plot(fpr, tpr, label=f"ROC AUC={metrics['roc_auc']:.3f}")
plt.plot([0, 1], [0, 1], "k--")
plt.xlabel("FPR")
plt.ylabel("TPR")
plt.legend(); Path("plots").mkdir(exist_ok=True)
plt.savefig("plots/roc_curve.png", dpi=150, bbox_inches="tight")

Path("artifacts").mkdir(exist_ok=True)
Path("artifacts/metrics.json").write_text(json.dumps(metrics, indent=2))
```

Regression example (swap estimators and scorers):

```python
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import numpy as np

y_hat = best_clf.predict(X_test)
rmse = float(np.sqrt(mean_squared_error(y_test, y_hat)))
mae = float(mean_absolute_error(y_test, y_hat))
r2 = float(r2_score(y_test, y_hat))
```

## Persistence and inference

```python
import joblib
from pathlib import Path

artifact_path = Path("artifacts/model.joblib")
joblib.dump(best_clf, artifact_path)

# ...later, for inference:
loaded = joblib.load(artifact_path)
preds = loaded.predict(X_new)
```

## Reproducibility metadata

```python
import platform, subprocess, json, sys
from pathlib import Path

metadata = {
    "python": sys.version,
    "platform": platform.platform(),
    "random_state": RANDOM_STATE,
    # If using uv/pip, capture resolved env:
    "requirements": subprocess.check_output(["uv", "pip", "freeze"]).decode(),
}
Path("artifacts").mkdir(exist_ok=True)
Path("artifacts/metadata.json").write_text(json.dumps(metadata, indent=2))
```

## MLflow tracking, evaluation, and persistence

Recommended: track experiments with MLflow so params, metrics, artifacts, and models are versioned.

```python
import os
import json
from pathlib import Path
import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
from sklearn.metrics import roc_auc_score, roc_curve, classification_report

# Configure tracking
mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns"))
mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT", "default"))

with mlflow.start_run(run_name=os.getenv("RUN_NAME", "sklearn-logreg")) as run:
    # Option 1: autolog end-to-end
    # mlflow.sklearn.autolog(log_models=True)

    # Fit the best estimator (e.g., from CV/tuning above)
    best_clf.fit(X_train, y_train)

    # Compute metrics
    y_pred = best_clf.predict(X_test)
    y_prob = best_clf.predict_proba(X_test)[:, 1]
    metrics = {
        "roc_auc": float(roc_auc_score(y_test, y_prob)),
    }

    # Log params (keep it concise)
    model_params = best_clf.named_steps["model"].get_params()
    mlflow.log_params({
        "estimator": best_clf.named_steps["model"].__class__.__name__,
        "C": model_params.get("C"),
        "penalty": model_params.get("penalty"),
        "max_iter": model_params.get("max_iter"),
        "random_state": model_params.get("random_state"),
    })

    # Log metrics
    mlflow.log_metrics(metrics)

    # Plot and log ROC curve
    fpr, tpr, _ = roc_curve(y_test, y_prob)
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot(fpr, tpr, label=f"ROC AUC={metrics['roc_auc']:.3f}")
    ax.plot([0, 1], [0, 1], "k--")
    ax.set(xlabel="FPR", ylabel="TPR")
    ax.legend()
    mlflow.log_figure(fig, "plots/roc_curve.png")

    # Log text artifacts
    mlflow.log_text(classification_report(y_test, y_pred), "reports/classification_report.txt")
    mlflow.log_dict({"feature_columns": numeric_features + categorical_features}, "artifacts/features.json")

    # Log model artifact (includes environment by default)
    mlflow.sklearn.log_model(best_clf, artifact_path="model")

    run_id = run.info.run_id
    print(f"MLflow run_id: {run_id}")
    print(f"Artifacts URI: {mlflow.get_artifact_uri()}")

# Later, load the exact model from a specific run
loaded = mlflow.sklearn.load_model(f"runs:/{run_id}/model")
preds = loaded.predict(X_new)
```

Optional: register the model in the Model Registry (when using a server-backed tracking URI):

```python
result = mlflow.register_model(
    model_uri=f"runs:/{run_id}/model",
    name=os.getenv("MLFLOW_REGISTERED_MODEL", "sklearn-logreg")
)
print(result)
```

## Tips

- Cache heavy preprocessing: `Pipeline(memory="./.cache")`.
- Use `make_scorer` for custom metrics; log both CV and holdout metrics.
- For imbalanced data, use `class_weight="balanced"` or resampling.
- Keep feature lists in one place (`src/features.py`) to avoid drift.
- You may implement features as simple table in, table out functions that you can call as part of the preprocessing using the `.pipe` method available on dataframes.
