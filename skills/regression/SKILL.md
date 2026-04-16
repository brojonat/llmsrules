---
name: regression
description: Build a production-ready regression model on tabular data using XGBoost with conformalized quantile regression for prediction intervals. Use when the user needs to predict a continuous target from tabular features (price, sales, demand, time-to-event, score) and report uncertainty alongside the point estimate. Default to this for any tabular regression task.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
-->

# Regression with XGBoost + Conformal Prediction Intervals

For tabular regression, **default to XGBoost** as the point estimator
and use **conformalized quantile regression (CQR)** to attach prediction
intervals that actually achieve their stated coverage. Point estimates
without intervals are not a model — they're a guess. This skill teaches
the workflow for shipping a regressor that a downstream system can
trust.

## When to use this skill

- The target is continuous (price, count, score, time, demand)
- The features are tabular (numbers, categories, dates) — not images,
  text, or audio
- You have at least a few hundred labeled examples
- Downstream consumers need both a point estimate **and** an interval

## When NOT to use this skill

- Classification (binary / multiclass / multilabel) → see the
  classification skills
- Time-series with strong temporal structure → use time-series methods,
  not XGBoost on a flat dataframe
- Truly linear data with < 100 rows → a regularized linear model
  (`Ridge`, `Lasso`, `ElasticNet`) will be hard to beat and gives
  closed-form coefficient interpretation
- You need a fully-Bayesian posterior over predictions (e.g. for
  decision analysis with explicit utilities) → use PyMC GLMs

## Project layout

```
<project>/
├── data/                # input parquet/csv
├── src/
│   ├── train.py         # ibis read → 3 XGBRegressors → conformal cal → MLflow
│   ├── predict.py       # reload models + conformal_q, return point + interval
│   └── plots.py         # predicted vs actual, residual diagnostics, coverage, SHAP
├── notebooks/
│   └── demo.py          # marimo walkthrough
└── mlruns/              # MLflow tracking store (gitignored)
```

## Data access — ibis at the source, pandas at the sklearn boundary

Use **ibis** (`ibis-framework[duckdb]`) to read data and compute
summaries; materialize with `.execute()` exactly once just before
sklearn:

```python
import ibis

table = ibis.duckdb.connect().read_parquet("data/train.parquet")
feature_cols = [c for c in table.columns if c.startswith("feature_")]

target_stats = (
    table
    .aggregate(
        target_mean=table.target.mean(),
        target_std=table.target.std(),
        n_total=table.count(),
    )
    .execute()
    .iloc[0]
)

data = (
    table
    .select(*feature_cols, "target")
    .execute()
)
X = data[feature_cols]
y = data["target"]
```

## The pipeline — three models, not one

For regression with intervals you fit **three** XGBoost models on the
same training data:

1. **Point estimator** — `objective="reg:squarederror"`, gives the
   expected value
2. **Lower quantile** — `objective="reg:quantileerror"`,
   `quantile_alpha=0.05` (or 0.10), gives the lower bound
3. **Upper quantile** — same, with `quantile_alpha=0.95` (or 0.90)

```python
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

def build_xgb_regressor(feature_cols, seed, *, objective="reg:squarederror", quantile_alpha=None):
    kwargs = dict(
        n_estimators=400, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
        objective=objective, random_state=seed, n_jobs=-1,
    )
    if quantile_alpha is not None:
        kwargs["quantile_alpha"] = quantile_alpha
    return Pipeline([
        ("preprocess", ColumnTransformer([("num", StandardScaler(), feature_cols)])),
        ("clf", XGBRegressor(**kwargs)),
    ])

xgb_point = build_xgb_regressor(feature_cols, seed=42)
xgb_lower = build_xgb_regressor(feature_cols, seed=42, objective="reg:quantileerror", quantile_alpha=0.05)
xgb_upper = build_xgb_regressor(feature_cols, seed=42, objective="reg:quantileerror", quantile_alpha=0.95)
```

XGBoost 2.0+ has native quantile regression via `reg:quantileerror`.
Earlier versions don't — if you're stuck on 1.x, use a different
library (`lightgbm` has supported it for years) or switch to a quantile
random forest.

## The four things that separate this from a tutorial

### 1. **Conformalized quantile regression** — intervals that actually cover

Vanilla quantile XGBoost optimizes pinball loss but **does not
guarantee** coverage. On Friedman1 with `quantile_alpha=0.05/0.95`
(nominal 90%), raw empirical coverage is typically **70-75%** — way
below target. The fix is conformal calibration.

The recipe:

```python
import numpy as np
from sklearn.model_selection import train_test_split

# 1. Split a calibration set off the training data
X_train, X_calib, y_train, y_calib = train_test_split(
    X_train_full, y_train_full, test_size=0.2, random_state=42,
)

# 2. Fit quantile models on the (smaller) train set
xgb_lower.fit(X_train, y_train)
xgb_upper.fit(X_train, y_train)

# 3. Compute conformity scores on the calibration set:
#    E_i = max(q_low(x_i) - y_i, y_i - q_high(x_i))
#    Positive when y_i is OUTSIDE the predicted interval.
cal_low = xgb_lower.predict(X_calib)
cal_high = xgb_upper.predict(X_calib)
conformity = np.maximum(cal_low - y_calib, y_calib - cal_high)

# 4. Find the appropriate quantile of the conformity scores
nominal_coverage = 0.90
n_cal = len(y_calib)
q_level = min(1.0, np.ceil(nominal_coverage * (n_cal + 1)) / n_cal)
conformal_q = float(np.quantile(conformity, q_level))

# 5. At inference time, expand the raw quantile bounds by ±conformal_q
def predict_interval(X_new):
    y_low_raw = xgb_lower.predict(X_new)
    y_high_raw = xgb_upper.predict(X_new)
    return y_low_raw - conformal_q, y_high_raw + conformal_q
```

This is **conformalized quantile regression** (Romano, Patterson,
Candes 2019). It guarantees marginal coverage of at least
`nominal_coverage` on test data drawn from the same distribution as
calibration. The intervals get wider, but they're now honest.

**Always log both the raw and conformalized empirical coverage** to
MLflow so you can see the gap. If raw coverage is already at the
nominal level, your data is well-behaved and the correction is small;
if it's far off, the correction was load-bearing.

### 2. **Residual diagnostics** — what the model is missing

After training, plot the residuals (`y_true - y_pred`) three ways:

- **Residual vs predicted**: should be a flat band around 0. A funnel
  shape = heteroscedasticity (the variance depends on the prediction).
  A curve = the model is missing non-linear structure.
- **Residual histogram + Normal overlay**: should look roughly Normal
  for squared-error models. Heavy tails suggest you should use
  `reg:absoluteerror` (MAE / L1) or `reg:huber` instead.
- **QQ plot vs Normal**: quick visual check for tail behavior.

```python
import matplotlib.pyplot as plt
from scipy import stats

residuals = y_test - y_pred
fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
axes[0].scatter(y_pred, residuals, alpha=0.5)
axes[0].axhline(0, color="red", ls="--")
axes[1].hist(residuals, bins=40, density=True)
stats.probplot(residuals, dist="norm", plot=axes[2])
```

If the residuals show structure, the model is leaving signal on the
table. Add features, change the loss, or try a more flexible model.

### 3. **Honest metrics** — RMSE and MAE in domain units, not just R²

R² ("explained variance") looks great for a wide range of models and
hides important information. Always report:

- **RMSE** (root mean squared error) — same units as the target,
  penalizes large errors. The benchmark to beat is the **irreducible
  error** (the std of the noise). If RMSE ≈ noise std, the model is
  essentially perfect.
- **MAE** (mean absolute error) — same units as the target, more
  interpretable than RMSE, less sensitive to outliers. "On average my
  prediction is off by X."
- **R²** — useful as a sanity check (≥ 0?) but don't optimize for it
  in isolation. R² = 0.95 on a problem with no signal is meaningless.

```python
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import numpy as np

rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
mae = float(mean_absolute_error(y_test, y_pred))
r2 = float(r2_score(y_test, y_pred))
```

### 4. **SHAP for feature importance**

Same advice as for binary classification: **don't use
`feature_importances_`**, it has biases. Use SHAP's `TreeExplainer`:

```python
import shap

clf = pipeline.named_steps["clf"]  # the XGBRegressor
preprocessor = pipeline.named_steps["preprocess"]
X_test_t = preprocessor.transform(X_test.iloc[:200])

explainer = shap.TreeExplainer(clf)
shap_values = explainer(X_test_t)
shap.summary_plot(shap_values, X_test_t, feature_names=feature_cols)
```

SHAP also gives you per-prediction explanations (`shap.plots.waterfall`)
which are essential for any deployed model that affects users.

## MLflow logging

Every run logs:

| Kind | What |
|---|---|
| `params` | data path, n_rows, n_features, target_mean / target_std, seed, **lower_quantile**, **upper_quantile**, **nominal_coverage**, model name, hyperparameters |
| `metrics` | test_rmse, test_mae, test_r2, **irreducible_rmse** (when known), **rmse_above_irreducible**, **conformal_q**, **coverage_raw** vs **coverage_conformal**, **interval_width_raw** vs **interval_width_conformal** |
| `tags` | data hash, target distribution stats |
| `artifacts` | three models (`model_point`, `model_lower`, `model_upper`), predicted-vs-actual scatter with interval bands, residual diagnostics, interval coverage plot (raw + conformal), SHAP summary, sidecar JSON |

The most important metric is `coverage_conformal` — if it's not within
~1% of `nominal_coverage`, something is wrong with your calibration set
(too small? distribution shift?).

## Common pitfalls

1. **Reporting only R².** R² of 0.95 can be a model that's useless
   in practice. Always report RMSE/MAE in domain units alongside.
2. **Skipping conformal calibration.** Vanilla quantile XGBoost
   intervals undercover. Without CQR your "90% interval" is probably
   a 70-75% interval. This silently breaks any downstream system that
   trusts the bounds.
3. **Calibrating on the test set.** The whole point of conformal
   prediction is that the calibration set is held out from both
   training **and** evaluation. Don't peek.
4. **Heteroscedastic data with squared-error loss.** If `residual vs
   predicted` shows a funnel, your variance depends on the prediction.
   Switch to `reg:quantileerror` (which doesn't assume constant
   variance) or `reg:huber` (robust to outliers).
5. **Trusting `feature_importances_`.** Use SHAP.
6. **Ignoring the irreducible error.** If you know the noise level
   (e.g. measurement uncertainty in the target), report `RMSE -
   noise_std`. That's the model's actual error budget.
7. **Treating prediction intervals as confidence intervals.** They are
   not the same. A prediction interval covers the *next observation*;
   a confidence interval covers the *true mean*. PIs are wider.

## Worked example

See `demo.py` (marimo notebook). It generates the Friedman1 non-linear
regression dataset inline (`y = 10·sin(π·x₀·x₁) + 20·(x₂−0.5)² + 10·x₃ + 5·x₄ + ε`),
fits all three XGBoost models, applies conformal calibration, plots
residual diagnostics + interval coverage, and includes a baseline
`LinearRegression` cell so you can see *why* a linear model fails on
non-linear structure.
