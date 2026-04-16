---
name: data-labeling-qa
description: Audit an untrusted labeled training set before fine-tuning. Find mislabeled examples with four complementary techniques — provenance/integrity checks (off-by-one, schema drift), cleanlab confident learning (random noise), high-loss monitoring (hard cases), and LLM-as-judge on the flagged subset (systematic confusion). Use before spending GPU on any fine-tune where you don't fully trust the labelers. Works with any classification dataset reshaped to `data` and `untrustworthy_label` columns.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
  - assets/demo.html — pre-rendered HTML preview (open in any browser)
-->

# Data Labeling QA — Done Right

If you don't trust the people who labeled your training data, **do not
fine-tune on it as-is**. Ten minutes of audit catches errors that will
otherwise silently poison your model. Bad labels don't just hurt
accuracy — they teach the model the wrong thing, and you won't find
out until production.

This skill runs four complementary audits and combines them into a
per-row trust score plus a prioritized review set. Each audit catches
a different failure mode; running only one leaves blind spots.

## When to use this skill

- You are about to fine-tune a classifier and your labels came from
  crowdsourcing, a third-party vendor, or a labeling app you don't
  fully trust
- A model's accuracy is lower than you expect and you suspect
  mislabeled training data (rather than a model or data-pipeline bug)
- You want to move to a smaller or cheaper labeling operation and
  need to quantify the quality delta
- You are migrating labels between schemas and want to spot-check
  the mapping

## When NOT to use this skill

- Labels come from a trusted, audited process and you already have
  quality metrics
- The task is generation / ranking / reward modeling (different
  audits — preference disagreement, not label noise)
- You have zero labels — this skill *judges* existing labels, it
  doesn't *create* them. For that, use a labeling tool plus the LLM
  labeling pattern in this skill's notes

## Four audits, four failure modes

| # | Audit | Catches | Cost |
|---|---|---|---|
| 1 | **Provenance / integrity** | Off-by-one, row misalignment, schema drift, null labels, duplicates with conflicting labels | Free |
| 2 | **Cleanlab confident learning** | Random label noise + low-rate systematic confusion | ~1 model training |
| 3 | **High-loss monitoring** | Genuinely hard cases *or* quiet mislabels indistinguishable from noise | Free byproduct of training |
| 4 | **LLM-as-judge on flagged subset** | Confirming cleanlab's flags, providing correct labels, and catching *high-rate* systematic confusion cleanlab can't | `K` LLM calls |

**Why all four, not just cleanlab?** Confident learning is stronger
than you'd expect — at low contamination rates (a few percent of rows
swapped in a consistent pattern) the honest majority still trains a
strong enough boundary that the flipped rows stand out. The demo
measures **93% recall on 3% systematic Sports ↔ Business swaps**
with just cleanlab. But cleanlab has three blind spots that *require*
the other audits:

1. **Structural bugs survive cleanlab.** Off-by-one, row misalignment,
   null labels, duplicate content with conflicting labels — cleanlab
   never sees these because the shifted labels look self-consistent
   to a model trained on them. Only the provenance audit catches them.
2. **High-rate systematic confusion is invisible.** Push the Sports ↔
   Business swap from 3% to 25% and the model learns the swap itself.
   Cleanlab's flagged set collapses toward zero exactly when the
   error rate is highest. The LLM judge doesn't train on the labels,
   so it sees the confusion regardless of rate.
3. **Cleanlab tells you a row is suspect but not what the correct
   label is.** The judge provides the correction, which is what you
   need to actually relabel the row. Without the judge, you're
   sending rows to a human review pile; with it, most of the pile
   becomes a drop-in fix.

## The four techniques in detail

### 1. Provenance / integrity audit — free, always first

Before any ML, audit the data *structure*. Most of these checks are
one-liners and they catch bugs that would otherwise look like label
noise:

```python
# Null / empty
df[df["data"].isnull() | (df["data"] == "")]
df[df["untrustworthy_label"].isnull()]

# Labels outside the known enum
df[~df["untrustworthy_label"].isin(VALID_LABELS)]

# Duplicate content with conflicting labels — classic off-by-one tell
(
    df.groupby("data")["untrustworthy_label"]
    .nunique()
    .loc[lambda s: s > 1]
)

# Per-class content length fingerprint — flags misalignment when
# classes have distinctive content distributions
df.groupby("untrustworthy_label")["data"].str.len().agg(["mean", "std"])
```

In production add domain-specific checks: timestamp consistency,
content-hash stability, ID monotonicity, label-enum drift over time.

**A structural bug will survive both cleanlab and LLM audits.** The
confident-learning model trained on shifted labels learns the shift;
the judge sees nothing suspicious in any individual row. The only
way to catch off-by-one is to verify *how the labels got attached to
the data in the first place*.

### 2. Confident learning with `cleanlab`

Train a model on the noisy labels using **k-fold cross-validation**
so every row gets an out-of-sample prediction. Cleanlab then
compares predicted probabilities against the given labels and flags
rows where the model confidently disagrees:

```python
from cleanlab.filter import find_label_issues
from sklearn.model_selection import cross_val_predict

pred_probs = cross_val_predict(
    pipeline, X, y, cv=5, method="predict_proba", n_jobs=-1,
)

issue_order = find_label_issues(
    labels=y,
    pred_probs=pred_probs,
    return_indices_ranked_by="self_confidence",
)
```

`issue_order` is an array of row indices sorted worst-first — the
top of the list is "cleanlab is most confident this label is wrong."
The returned count is cleanlab's own budget, tuned automatically
from the predicted-probability distribution.

**Model choice doesn't have to be fancy.** TF-IDF + LogisticRegression
works well for text; a shallow XGBoost for tabular. The only
requirement is calibrated-ish probabilities from cross-validation.
Don't spend a week tuning the confident-learning model — that's
yak-shaving; the point is to find labels, not to build a classifier.

**Critical gotcha**: always use `cross_val_predict`, never
`pipeline.fit(X, y).predict_proba(X)`. The latter gives in-sample
probabilities that are memorized garbage — the model will confidently
agree with every label it was trained on, so cleanlab finds nothing.

### 3. High-loss monitoring during fine-tuning

If you're fine-tuning anyway, you get a fourth audit for free: log
per-example loss throughout training. At epoch end, examples whose
loss stays high are either *genuinely hard* or *mislabeled*, and
you can't tell without looking — but it's a cheap prioritized review
list for humans.

In transformers / TRL:

```python
from transformers import TrainerCallback

class PerExampleLossLogger(TrainerCallback):
    def __init__(self):
        self.losses_by_example = {}

    def on_log(self, args, state, control, logs=None, **kwargs):
        ...
```

Alternatively, after training, run one forward pass over the
training set and record per-example loss. Rows in the top decile of
loss that stay high across training are your audit list.

### 4. LLM-as-judge on the flagged subset

Cleanlab gives you ~2–10% of rows as its flagged set. That's the
right size to send to a premium LLM for semantic verification — way
cheaper than judging the whole dataset, and focused on the actual
suspects.

The prompt is a structured YES/NO with a correction field:

```
Valid categories: World, Sports, Business, Sci/Tech

Text: {data}

Assigned label: {untrustworthy_label}

Respond on exactly two lines:
VERDICT: YES or NO
CORRECT_LABEL: one of the valid categories, or SAME if verdict is YES
```

Parse with a strict two-line grammar; reject anything else as
`UNKNOWN` and treat those rows as "needs human review."

**Budget control.** Gate the judge behind a button (or a CLI flag)
so notebook re-runs don't silently re-spend. The demo in this
bundle uses a marimo run-button for exactly this.

**Judge model**: `gpt-4o-mini` is the right starting point —
cheap, fast, better than humans on most classification. Use a
bigger model only if the task is genuinely hard (legal, medical,
domain-specific vocabulary).

## LLM-as-judge vs LLM-as-labeler

Two strategies for fighting label noise with an LLM:

- **Judge** (this skill): keep the human labels, use the LLM to
  verify the suspicious ones. Preserves human judgment on hard /
  ambiguous cases. Spend scales with suspicion, not dataset size.
- **Labeler**: replace the human labels entirely with LLM labels.
  More consistent but throws away good human signal on hard cases,
  and hard-codes whatever bias the LLM has.

**Default to judging.** Switch to full LLM labeling only if:

- You suspect the human labelers are essentially guessing (> 30%
  error rate — at that point there's no signal to preserve)
- You have zero human labels and need to bootstrap
- The task is so consistent that an LLM beats any individual human
  (e.g. trivial keyword-based classification)

## The combined trust score

Fuse all four signals into one number per row. A simple rule:

```python
def trust_score(row):
    if not row["cleanlab_flagged"]:
        return 0.8 + 0.2 * row["self_confidence"]  # trust
    if row["verdict"] == "NO":
        return 0.05  # judge confirms mislabel
    if row["verdict"] == "YES":
        return 0.6   # judge overrules cleanlab
    return 0.3       # flagged but un-judged (needs human)
```

And a review-action recommendation:

- **`relabel`**: cleanlab flagged + judge rejected + provided correction
- **`keep (ambiguous)`**: cleanlab flagged + judge approved
- **`needs_review`**: cleanlab flagged + no judge call yet
- **`keep`**: unflagged

Export the `relabel` rows back to your labeling pipeline with the
judge's corrections. Send `needs_review` to human review. Keep
everything else in the training set, but log the `keep (ambiguous)`
rows — if training loss stays high on these at epoch end, they're
probably genuinely hard examples, not mislabels.

## Evaluating the audits

**In production you can't measure recall** — you don't know the true
label. The best you can do is:

1. Spot-check a stratified sample (say 100 rows) by hand, use that
   as a mini ground truth.
2. Measure the agreement rate between cleanlab and the judge on the
   overlapping set. High agreement → both techniques are converging
   on real errors. Low agreement → one of them is broken, investigate.
3. Track the precision of your `relabel` bucket over time. If
   downstream retraining shows the corrected labels improve accuracy,
   the audit is working.

**For a worked evaluation**, see `demo.py`. It deliberately corrupts
AG News in three ways (off-by-one, random flip, systematic Sports ↔
Business swap) so you can measure each audit technique's recall
against known ground truth. In the wild you won't have this, but it's
how you verify the pipeline before trusting it.

## Common pitfalls

1. **Skipping provenance and going straight to cleanlab.** Cleanlab
   won't catch off-by-one bugs because the shifted labels look
   self-consistent to a model trained on them. Always run
   integrity checks first.
2. **Using `pipeline.fit(X, y).predict_proba(X)` instead of
   `cross_val_predict`.** In-sample probabilities are memorized
   garbage and cleanlab will find nothing. Always cross-validate
   to get honest out-of-sample predictions.
3. **Judging the whole dataset.** LLM-as-judge on 100k rows is
   expensive and unnecessary. Judge the ~5% cleanlab flags, spot-
   check a random sample of the unflagged rest to audit false
   negatives.
4. **Letting the judge re-run on every notebook refresh.** Gate it
   behind an explicit action. Cache the results by (row_id,
   prompt_hash) so repeated runs don't re-spend.
5. **Trusting the judge's `CORRECT_LABEL` blindly.** The judge
   can be wrong too, especially on genuinely ambiguous rows.
   Treat `relabel` as "high-confidence candidate for relabel,"
   not as "definitive new label." Human review remains the
   ultimate arbiter on the margins.
6. **Using an over-fitted confident-learning model.** If your
   TF-IDF + LR has 100% training accuracy, you've leaked data or
   the task is trivial. Cleanlab needs a model that generalizes,
   not memorizes.
7. **Ignoring systematic bias in the judge.** If `gpt-4o-mini`
   has its own blind spots on your task (e.g. consistently
   confusing two classes), it will rubber-stamp cleanlab's
   confused rows. Mitigate by running two judges from different
   families and only trusting unanimous `NO` verdicts on
   high-stakes relabels.

## Worked example

See `demo.py` (marimo notebook). It loads AG News, injects three
kinds of corruption totaling ~9% of rows, then runs the full audit
pipeline: provenance checks → cleanlab confident learning → LLM
judge on the flagged subset → combined trust score and review set.
The final cell measures each audit's precision and recall against
the known injected errors, broken down by corruption type, so you
can see exactly which technique catches which failure mode.

Requires `LLM_API_KEY` (set before launching marimo). Optional
`LLM_BASE_URL` for custom OpenAI-compatible endpoints (LM Studio,
vLLM, Ollama). Uses Simon Willison's `llm` Python package under
the hood, so swapping models is a single string change.

## What to run next

After auditing:

- **Export the `relabel` set** to your labeling pipeline; re-ingest
  with the judge's corrections.
- **Run `llm-finetuning`** on the cleaned dataset — it's the next
  skill in this chain, with examples showing zero-shot vs
  fine-tuned comparison and MLflow tracking.
- **Archive the audit report** alongside your dataset version. Six
  months later when a model starts regressing, you want to be able
  to diff the audit reports across dataset versions.
