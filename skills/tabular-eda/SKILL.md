---
name: tabular-eda
description: Profile a new tabular dataset before modeling. Find target leakage, missing data patterns, high-cardinality categoricals, near-constant features, redundant pairs, and non-linear relationships that Pearson correlation misses. Use whenever the user hands you a CSV or parquet and asks "what should I do with this?" Always run this skill before training any model on data you haven't seen before.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
-->

# Tabular EDA — Done Right

Whenever you get handed a new tabular dataset, **stop**. Do not jump
straight to `XGBClassifier()`. Ten minutes of EDA will catch problems
that would otherwise destroy your downstream model — target leakage,
high-cardinality explosions, MAR missing data, non-linear features that
Pearson correlation says are useless. This skill is the workflow.

## When to use this skill

- You just received a new dataset and have no idea what's in it
- You're about to train a model and want to validate the data first
- A model is performing suspiciously well (or poorly) and you suspect
  a data quality issue
- The user asks "what should I do with this dataset?"

## When NOT to use this skill

- You already deeply know the dataset and have profiled it before
- The dataset is image / text / audio / time-series — different rules
- The user just wants a model trained, fast, and is OK with risk

## The workflow

```
1. Load → shape, dtypes, memory
2. Identify the target → infer problem type (binary / multiclass / regression)
3. Missing data → per-column %, overall %, patterns
4. Numeric distributions → skew, outliers, scale mismatches
5. Categorical cardinality → flag high-cardinality (OHE explosion risk)
6. Near-constant features → flag and consider dropping
7. Redundant pairs → flag features with > 0.95 mutual correlation
8. **Target leakage detection** → flag features with > 0.95 |Pearson| to target
9. **Mutual information vs Pearson** → catch non-linear features Pearson misses
10. Optional: PCA / UMAP for low-dim visualization
```

The output is a **findings report**: a list of suspicious things, each
with a feature name, the metric that flagged it, and a recommended
action. **Don't just print plots.** A list of problems with names is
what you act on.

## Five things that separate this from a tutorial

### 1. **Target leakage detection** — the single most valuable EDA check

A "leakage" feature is one that contains information about the target
that wouldn't actually be available at prediction time. The classic
examples:

- `account_balance_after_payment` for predicting `made_payment`
- `total_charges` (cumulative) for predicting `churned`
- `claim_paid_amount` for predicting `claim_was_filed`

These features are computed *after* the prediction time. Train on
them and you get 99% test accuracy and a model that completely fails
in production. The signature is **suspiciously high correlation with
the target** — anything > 0.95 is a leak suspect, anything > 0.99 is
almost certainly a leak.

```python
def find_leakage_candidates(df, target_col, numeric_cols, threshold=0.95):
    out = []
    for col in numeric_cols:
        if col == target_col:
            continue
        corr = float(df[[col, target_col]].dropna().corr().iloc[0, 1])
        if abs(corr) > threshold:
            out.append({"feature": col, "pearson": round(corr, 4)})
    return out
```

When you find a leakage candidate, **always confirm with the data
owner before dropping it**. Sometimes a feature is legitimately almost
perfectly correlated with the target (e.g. an upstream model's
prediction). But the default assumption is "this is a leak."

### 2. **Mutual information vs Pearson** — catch non-linear signal

Pearson correlation only catches **linear** relationships. A feature
that drives the target via `sin(x)` or `(x - 0.5)²` will have Pearson ≈ 0
and Pearson alone will mark it as useless. Mutual information catches
both.

```python
from sklearn.feature_selection import mutual_info_classif, mutual_info_regression

# For classification
mi_scores = mutual_info_classif(X, y, random_state=0)

# For regression
mi_scores = mutual_info_regression(X, y, random_state=0)
```

Plot |Pearson| and MI side by side as a bar chart. Features where
**MI is high but |Pearson| is low** are non-linear signal hiding from
your linear EDA. They'll be invisible to a linear model and powerful
in XGBoost.

This is the same lesson the regression bundle teaches with Friedman1's
`sin(π·x₀·x₁)` term: zero linear correlation, large mutual information,
huge contribution to the target.

### 3. **High-cardinality categorical detection**

A column like `user_id` with thousands of unique values will explode
a `OneHotEncoder` into thousands of sparse columns. Flag any
categorical with > 50 unique values:

```python
def find_high_cardinality(df, cat_cols, threshold=50):
    return [
        {"feature": c, "n_unique": int(df[c].nunique())}
        for c in cat_cols if df[c].nunique() > threshold
    ]
```

Recommended action for high-cardinality categoricals:
- **Target encoding** (smoothed mean of the target per category) —
  works well, but leaks during cross-validation if you're careless
- **Frequency encoding** — replace each category with its frequency
- **Hash encoding** — fixed-size hash buckets
- **Just drop it** — `user_id` is rarely a useful feature anyway

### 4. **Near-constant feature detection**

A column where one value covers > 98% of the rows has essentially no
signal. It's not always wrong to keep it (some signal beats no signal),
but it's often indicative of a data collection issue and worth flagging:

```python
def find_near_constant(df, threshold=0.98):
    return [
        {"feature": c, "top_value_freq": float(df[c].value_counts(normalize=True).iloc[0])}
        for c in df.columns
        if df[c].value_counts(normalize=True).iloc[0] > threshold
    ]
```

### 5. **Redundant feature detection**

Features with mutual correlation > 0.95 carry the same information.
Drop one of each pair to reduce multicollinearity (which messes up
linear models more than tree models, but is still wasted compute):

```python
def find_redundant_pairs(df, numeric_cols, threshold=0.95):
    corr = df[numeric_cols].corr().abs()
    out = []
    for i, c1 in enumerate(numeric_cols):
        for c2 in numeric_cols[i + 1:]:
            if float(corr.loc[c1, c2]) > threshold:
                out.append({"pair": [c1, c2], "pearson": float(corr.loc[c1, c2])})
    return out
```

## Visual checks (always include in the output)

These six plots together answer "what's in this data?" in 30 seconds:

1. **Missing data bar chart** — sorted by % missing, descending
2. **Numeric distributions grid** — histograms with skew annotated
3. **Categorical cardinality bar chart** — red bars > 50 unique values
4. **Correlation heatmap** — feature × target Pearson, with target
   column annotated with the actual numbers
5. **Mutual info vs Pearson side-by-side bar chart** — surfaces the
   non-linear signal Pearson misses
6. **Outlier box plots** — per-numeric-column with IQR-based outlier
   counts

Output a **findings.json** file alongside the plots. Each finding has
a feature name, the metric that flagged it, and a recommended action.
The list is what gets actioned; the plots are the supporting evidence.

## Type inference for the target

Before any modeling, infer the target type heuristically:

```python
def infer_target_type(y):
    if y.dtype.kind in "biu":  # bool / int
        n_unique = y.nunique()
        if n_unique == 2:
            return "binary"
        if n_unique <= 20:
            return "multiclass"
        return "regression"
    if y.dtype.kind == "f":
        return "regression"
    return "categorical"
```

This tells you which downstream skill to invoke next:

- `binary` → binary-classification skill
- `multiclass` → multiclass-classification skill
- `regression` → regression skill
- `categorical` (no obvious target) → unsupervised skill

## Common pitfalls

1. **Skipping EDA entirely.** "I'll just throw it at XGBoost." This is
   how target leakage and 99%-test-accuracy-then-broken-in-prod
   happen.
2. **Pearson-only correlation.** Misses sin / quadratic / categorical
   relationships. Always pair with mutual information.
3. **Dropping a "leakage" feature without confirming with the data
   owner.** Sometimes the feature is legitimate (an upstream model's
   prediction). Confirm before deleting.
4. **OneHotEncoding a high-cardinality categorical.** Explodes feature
   count, drowns the model in noise, slows training. Use target
   encoding, frequency encoding, or just drop the column.
5. **Not checking for duplicates.** A dataset with 50% duplicate rows
   will show inflated test metrics if duplicates land in both train
   and test.
6. **Imputing missing values without thinking.** Fill with the median
   for MCAR, but for MAR/MNAR you may need to model the missingness
   itself. Always flag the missingness pattern; don't silently impute.
7. **Treating the EDA report as ephemeral.** Log the findings JSON
   and the plots to MLflow (or wherever your experiment tracker
   lives). When a model fails six months later, you want to be able
   to look at the EDA report from when the data was first profiled.

## Worked example

See `demo.py` (marimo notebook). It generates a deliberately messy
synthetic binary classification dataset with **seven planted issues**
(target leakage, high-cardinality categorical, near-constant feature,
30% missing data, log-normal skew, 2% outliers, redundant pair) and
walks through detecting each one. The notebook ends with a
findings table summarizing what the EDA pipeline caught — and that
table is the input to "what model do I train next?"

## After EDA: what to do next

Based on the findings, decide:

- **Drop**: leakage features, near-constant features, one of each
  redundant pair
- **Encode**: high-cardinality categoricals via target/frequency/hash
- **Impute**: missing data (median for numeric, "missing" sentinel for
  categorical)
- **Transform**: skewed features (log, Box-Cox), outliers (winsorize
  or robust scaler)
- **Then**: invoke the appropriate problem-type skill
  (binary-classification, regression, multiclass-classification, etc.)
