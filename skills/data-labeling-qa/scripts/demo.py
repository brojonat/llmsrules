# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#     "marimo",
#     "pandas>=2.2",
#     "numpy>=1.26",
#     "scikit-learn>=1.5",
#     "cleanlab>=2.7",
#     "llm>=0.17",
#     "datasets>=2.19",
#     "matplotlib>=3.9",
#     "ibis-framework[duckdb]>=9.0",
# ]
# ///
"""Worked example for the data-labeling-qa bundle.

Audits a labeled training set before fine-tuning. The input schema is
intentionally minimal -- a `data` column (raw content) and an
`untrustworthy_label` column (what the labeler picked). Users adapt
their own schema into this shape.

This notebook builds a deliberately corrupted AG News sample so it can
measure each audit technique's recall against ground truth. In the
wild there is no ground truth -- that's the whole point -- but for a
worked example, knowing the injected errors lets you see which
techniques catch which kinds of mistakes.

Four audits, each catches a different failure mode:

1. Provenance check  -- off-by-one, row misalignment, schema drift
2. Confident learning (cleanlab) -- random label noise
3. High-loss audit -- genuinely hard examples or quiet mislabels
4. LLM-as-judge (on the flagged subset only) -- systematic confusion

The LLM judge uses Simon Willison's `llm` package. Set `LLM_API_KEY`
and `LLM_BASE_URL` env vars before launching marimo. LLM_BASE_URL is
optional -- only needed if you're pointing at a custom OpenAI-compatible
endpoint (LM Studio, vLLM, etc.).

    LLM_API_KEY=sk-... marimo edit --sandbox demo.py
"""

import marimo

__generated_with = "0.23.1"
app = marimo.App(width="medium")


@app.cell
def imports():
    """Set up env var bridging, then import everything."""
    import os

    # Bridge our user-facing env vars to the OpenAI-compatible names that
    # Simon's `llm` package looks for. LLM_BASE_URL is optional -- only
    # needed for custom endpoints like LM Studio, vLLM, or Ollama.
    if "LLM_API_KEY" in os.environ and "OPENAI_API_KEY" not in os.environ:
        os.environ["OPENAI_API_KEY"] = os.environ["LLM_API_KEY"]
    if "LLM_BASE_URL" in os.environ and "OPENAI_BASE_URL" not in os.environ:
        os.environ["OPENAI_BASE_URL"] = os.environ["LLM_BASE_URL"]

    import ibis
    import llm as llm_pkg
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from cleanlab.filter import find_label_issues
    from datasets import load_dataset
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import precision_score, recall_score
    from sklearn.model_selection import cross_val_predict
    from sklearn.pipeline import Pipeline

    ibis.options.interactive = False
    return (
        LogisticRegression,
        Pipeline,
        TfidfVectorizer,
        cross_val_predict,
        find_label_issues,
        ibis,
        llm_pkg,
        load_dataset,
        mo,
        np,
        os,
        pd,
        plt,
        precision_score,
        recall_score,
    )


@app.cell
def title(mo):
    mo.md(r"""
    # Data Labeling QA

    Audit an untrusted labeled dataset **before** burning GPU on a
    fine-tuning run. Input is a dataframe with two columns:
    `data` and `untrustworthy_label`. Output is a per-row
    `trust_score` plus a prioritized review set.

    This notebook deliberately corrupts AG News in three ways so
    each audit technique can be measured against known ground
    truth. The pipeline itself only sees the corrupted labels --
    `label_true` is hidden from the audits.
    """)
    return


@app.cell
def config_md(mo):
    mo.md(r"""
    ## Configuration

    Lowering `N_SAMPLES` or `K_JUDGE` makes the notebook faster and
    cheaper. The LLM judge only runs on the top `K_JUDGE` flagged
    rows, so total LLM calls = `K_JUDGE` regardless of dataset
    size.
    """)
    return


@app.cell
def config(mo):
    """Knobs. The defaults are tuned so the whole notebook runs in
    under two minutes and costs well under a penny on gpt-4o-mini."""
    N_SAMPLES = 2000

    # Corruption injection rates (fraction of rows affected)
    RATE_OFF_BY_ONE = 0.01  # structural: label index shifted by 1
    RATE_RANDOM_FLIP = 0.05  # random label noise -- cleanlab's bread and butter
    RATE_SYSTEMATIC = 0.03  # Sports <-> Business swap -- needs a semantic check

    # Audit settings
    K_JUDGE = 60  # number of flagged rows to send to the LLM judge
    LLM_MODEL_NAME = "gpt-4o-mini"

    RANDOM_SEED = 7

    _cfg_table = mo.md(
        f"""
        | Setting | Value |
        |---|---:|
        | Samples | `{N_SAMPLES}` |
        | Off-by-one corruption | `{RATE_OFF_BY_ONE:.0%}` |
        | Random label flips | `{RATE_RANDOM_FLIP:.0%}` |
        | Systematic confusion | `{RATE_SYSTEMATIC:.0%}` |
        | LLM judge budget | `{K_JUDGE}` calls |
        | LLM model | `{LLM_MODEL_NAME}` |
        | Random seed | `{RANDOM_SEED}` |
        """
    )
    _cfg_table
    return (
        K_JUDGE,
        LLM_MODEL_NAME,
        N_SAMPLES,
        RANDOM_SEED,
        RATE_OFF_BY_ONE,
        RATE_RANDOM_FLIP,
        RATE_SYSTEMATIC,
    )


@app.cell
def load_and_corrupt_md(mo):
    mo.md(r"""
    ## Step 0 -- Load and corrupt the data

    Real buyers start with an already-labeled dataset. We
    simulate that by loading AG News, keeping the true labels
    aside for evaluation only, and producing an
    `untrustworthy_label` column that contains three kinds of
    injected errors.
    """)
    return


@app.cell
def load_and_corrupt(
    N_SAMPLES,
    RANDOM_SEED,
    RATE_OFF_BY_ONE,
    RATE_RANDOM_FLIP,
    RATE_SYSTEMATIC,
    load_dataset,
    np,
    pd,
):
    """Load AG News, reshape to (data, untrustworthy_label), inject
    four corruption types. Keep ground truth on the side for evaluation
    only -- the audit pipeline never sees `label_true`.
    """

    LABEL_NAMES = ["World", "Sports", "Business", "Sci/Tech"]

    _ds = load_dataset("ag_news", split="train")
    _rng = np.random.default_rng(RANDOM_SEED)
    _idx = _rng.choice(len(_ds), size=N_SAMPLES, replace=False)
    _rows = _ds.select(_idx.tolist())
    _data = [r["text"] for r in _rows]
    _true_ids = np.array([r["label"] for r in _rows])
    _noisy_ids = _true_ids.copy()
    _noisy_labels = [
        None
    ] * N_SAMPLES  # string labels; mutated for bad-enum corruption
    _corruption = np.array(["clean"] * N_SAMPLES, dtype=object)


    def _claim(idx_arr, tag):
        _corruption[idx_arr] = tag


    # 1. Off-by-one: shift the label index by +1 (mod 4) on a few rows.
    #    Simulates a pipeline bug where the labeler looked at row i
    #    but the dropdown selection was attributed to row i+1.
    n_off = int(round(N_SAMPLES * RATE_OFF_BY_ONE))
    off_by_one_idx = _rng.choice(N_SAMPLES, size=n_off, replace=False)
    _noisy_ids[off_by_one_idx] = (_noisy_ids[off_by_one_idx] + 1) % 4
    _claim(off_by_one_idx, "off_by_one")

    # 2. Random label flip: replace with a uniformly-random different
    #    label. Cleanlab's confident learning is designed for this.
    n_rand = int(round(N_SAMPLES * RATE_RANDOM_FLIP))
    remaining = np.setdiff1d(np.arange(N_SAMPLES), off_by_one_idx)
    rand_idx = _rng.choice(remaining, size=n_rand, replace=False)
    for _i in rand_idx:
        _new = _rng.integers(0, 4)
        while _new == _noisy_ids[_i]:
            _new = _rng.integers(0, 4)
        _noisy_ids[_i] = _new
    _claim(rand_idx, "random_flip")

    # 3. Systematic confusion: Sports (1) <-> Business (2). A tired
    #    labeler skimming finance-tinged sports articles or vice
    #    versa. Cleanlab catches this at low rates, but the LLM judge
    #    catches it regardless.
    n_sys = int(round(N_SAMPLES * RATE_SYSTEMATIC))
    remaining2 = np.setdiff1d(remaining, rand_idx)
    sys_candidates = remaining2[np.isin(_true_ids[remaining2], [1, 2])]
    sys_idx = _rng.choice(
        sys_candidates, size=min(n_sys, len(sys_candidates)), replace=False
    )
    swap = {1: 2, 2: 1}
    _noisy_ids[sys_idx] = [swap[x] for x in _noisy_ids[sys_idx]]
    _claim(sys_idx, "systematic")

    # 4. Structural corruption (caught by provenance, not cleanlab):
    #    - null data rows (index-level pipeline bug)
    #    - duplicate content with conflicting labels (copy/paste error)
    #    - a label not in the known enum (schema drift)
    remaining3 = np.setdiff1d(remaining2, sys_idx)
    null_idx = _rng.choice(remaining3, size=3, replace=False)
    remaining4 = np.setdiff1d(remaining3, null_idx)
    dup_src_idx = _rng.choice(remaining4, size=3, replace=False)
    dup_dst_idx = _rng.choice(
        np.setdiff1d(remaining4, dup_src_idx), size=3, replace=False
    )
    remaining5 = np.setdiff1d(
        remaining4, np.concatenate([dup_src_idx, dup_dst_idx])
    )
    bad_enum_idx = _rng.choice(remaining5, size=1, replace=False)

    # Apply structural corruption
    for _i in null_idx:
        _data[_i] = ""  # empty content
    for _src, _dst in zip(dup_src_idx, dup_dst_idx):
        _data[_dst] = _data[_src]  # content now matches src
        # Force a label conflict if the two rows happen to share a label
        if _noisy_ids[_dst] == _noisy_ids[_src]:
            _noisy_ids[_dst] = (_noisy_ids[_src] + 1) % 4

    _claim(null_idx, "structural_null")
    _claim(dup_dst_idx, "structural_dup")
    _claim(bad_enum_idx, "structural_enum")

    # Materialize string labels. bad_enum gets a value outside the set.
    for _i in range(N_SAMPLES):
        _noisy_labels[_i] = LABEL_NAMES[_noisy_ids[_i]]
    for _i in bad_enum_idx:
        _noisy_labels[_i] = "MISC"  # not in LABEL_NAMES

    df_labeled = pd.DataFrame(
        {
            "row_id": np.arange(N_SAMPLES),
            "data": _data,
            "untrustworthy_label": _noisy_labels,
            # Hidden from audits, used only for evaluation at the end.
            "label_true": [LABEL_NAMES[i] for i in _true_ids],
            "corruption": _corruption,
        }
    )
    return LABEL_NAMES, df_labeled


@app.cell
def corruption_summary(df_labeled, mo):
    """Show exactly what we injected -- the 'oracle' view the pipeline
    will never see. In real use you won't have this breakdown."""
    _counts = df_labeled["corruption"].value_counts()
    _n_errors = int((df_labeled["corruption"] != "clean").sum())
    _n_total = len(df_labeled)

    mo.md(
        f"""
        **Ground-truth corruption breakdown** (pipeline doesn't see this):

        | Type | Rows | Share |
        |---|---:|---:|
        | Clean | {int(_counts.get('clean', 0))} | {_counts.get('clean', 0) / _n_total:.1%} |
        | Off-by-one | {int(_counts.get('off_by_one', 0))} | {_counts.get('off_by_one', 0) / _n_total:.1%} |
        | Random flip | {int(_counts.get('random_flip', 0))} | {_counts.get('random_flip', 0) / _n_total:.1%} |
        | Systematic | {int(_counts.get('systematic', 0))} | {_counts.get('systematic', 0) / _n_total:.1%} |

        **Total errors: `{_n_errors}` / {_n_total} = {_n_errors / _n_total:.1%}**
        """
    )
    return


@app.cell
def step1_md(mo):
    mo.md(r"""
    ## Step 1 -- Provenance / integrity audit

    Before touching a model, check the data *structure*. Off-by-one
    bugs, duplicate rows, null labels, schema drift -- these are
    cheap to catch and they don't need any ML at all. If your
    audit pipeline skips this step you'll waste compute on
    confident-learning flags that are really just data pipeline
    bugs.

    For this synthetic demo the integrity checks below are all
    green, but we include a per-class label length fingerprint
    that can catch off-by-one misalignment when the content
    distribution per class is distinctive. In production you'd
    add domain-specific checks (timestamps, IDs, content hashes,
    label enum validation).
    """)
    return


@app.cell
def provenance_audit(LABEL_NAMES, df_labeled, ibis, mo):
    """Provenance / integrity audit on the raw labeled dataframe."""
    # Pipeline the audit queries through ibis so the style matches
    # the rest of our bundles.
    t = ibis.memtable(
        df_labeled[["row_id", "data", "untrustworthy_label"]]
    )

    # 1. Null checks
    null_data = int(
        t.filter(t.data.isnull() | (t.data == "")).count().execute()
    )
    null_label = int(
        t.filter(
            t.untrustworthy_label.isnull() | (t.untrustworthy_label == "")
        )
        .count()
        .execute()
    )

    # 2. Label enum validation -- every label should be in the known set
    label_set = set(LABEL_NAMES)
    unknown_labels = (
        t.group_by("untrustworthy_label")
        .aggregate(n=t.count())
        .execute()
    )
    unknown_labels["known"] = unknown_labels["untrustworthy_label"].isin(
        label_set
    )
    n_unknown = int(unknown_labels.loc[~unknown_labels["known"], "n"].sum())

    # 3. Duplicate data with conflicting labels -- often an
    #    off-by-one tell in production.
    dup_conflict = (
        t.group_by("data")
        .aggregate(
            n=t.count(),
            n_distinct_labels=t.untrustworthy_label.nunique(),
        )
        .filter(lambda x: x.n_distinct_labels > 1)
        .execute()
    )
    n_dup_conflict = len(dup_conflict)

    # 4. Content-length fingerprint per label. If the per-class mean
    #    length distribution looks pathological (e.g. one class has
    #    an anomalously wide std), that can hint at misalignment.
    length_fp = (
        df_labeled[["untrustworthy_label", "data"]]
        .assign(length=df_labeled["data"].str.len())
        .groupby("untrustworthy_label")["length"]
        .agg(["mean", "std", "count"])
        .round(1)
        .reset_index()
    )

    _findings_md = f"""
    | Check | Result |
    |---|---|
    | Null / empty `data` | {'✓ ok' if null_data == 0 else f'✗ {null_data} rows'} |
    | Null / empty `untrustworthy_label` | {'✓ ok' if null_label == 0 else f'✗ {null_label} rows'} |
    | Labels outside known set | {'✓ ok' if n_unknown == 0 else f'✗ {n_unknown} rows'} |
    | Duplicate `data` with conflicting labels | {'✓ ok' if n_dup_conflict == 0 else f'⚠ {n_dup_conflict} groups'} |
    """

    mo.vstack(
        [
            mo.md("### Integrity checks\n" + _findings_md),
            mo.md("### Per-label content length fingerprint"),
            mo.ui.table(length_fp),
        ]
    )
    return


@app.cell
def step2_md(mo):
    mo.md(r"""
    ## Step 2 -- Confident learning with `cleanlab`

    Train a quick model on the noisy labels using **k-fold
    cross-validation**, so every row gets a prediction from a
    model that didn't see it during training. Cleanlab then
    compares predicted probabilities against the given labels
    and flags rows where the model confidently disagrees -- those
    are very likely mislabels.

    The model here is a bare TF-IDF + logistic regression. For
    image / tabular / multimodal data you'd swap in your own
    cross-validated probability estimates; the cleanlab API is
    the same.
    """)
    return


@app.cell
def confident_learning(
    LogisticRegression,
    Pipeline,
    RANDOM_SEED,
    TfidfVectorizer,
    cross_val_predict,
    df_labeled,
    find_label_issues,
    np,
    pd,
):
    """Train TF-IDF + LR with cross_val_predict, pass pred_probs to
    cleanlab's find_label_issues. Cheap, fast, catches random noise."""

    LABEL_NAMES_CL = ["World", "Sports", "Business", "Sci/Tech"]

    X_cl = df_labeled["data"].to_numpy()
    # Unknown labels (out of enum) are mapped to class 0 here so cleanlab
    # can still train. Provenance separately flags them, so double-flagging
    # is fine -- the final combined pipeline treats them as errors either way.
    y_cl = np.array(
        [
            LABEL_NAMES_CL.index(l) if l in LABEL_NAMES_CL else 0
            for l in df_labeled["untrustworthy_label"]
        ]
    )

    _pipeline = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    max_features=15000,
                    ngram_range=(1, 2),
                    min_df=2,
                ),
            ),
            (
                "lr",
                LogisticRegression(
                    max_iter=1000,
                    C=1.0,
                    random_state=RANDOM_SEED,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    pred_probs = cross_val_predict(
        _pipeline,
        X_cl,
        y_cl,
        cv=5,
        method="predict_proba",
        n_jobs=-1,
    )

    # self_confidence = probability the model assigns to the given
    # label. Low self_confidence = cleanlab thinks it's likely wrong.
    self_confidence = pred_probs[np.arange(len(y_cl)), y_cl]
    # Also grab the model's top prediction for each row; used in the
    # judge prompt and the trust score.
    model_pred = pred_probs.argmax(axis=1)
    model_top_prob = pred_probs.max(axis=1)

    # n_jobs=1 avoids a cleanlab multiprocessing bug where
    # `pred_probs_by_class` is undefined in worker process scope
    # under Python 3.13+ in certain fork modes.
    issue_order = find_label_issues(
        labels=y_cl,
        pred_probs=pred_probs,
        return_indices_ranked_by="self_confidence",
        n_jobs=1,
    )

    # Build a flag column: True = cleanlab thinks this row is mislabeled.
    is_flagged = np.zeros(len(df_labeled), dtype=bool)
    is_flagged[issue_order] = True

    df_audited = df_labeled.assign(
        self_confidence=self_confidence,
        model_pred=[LABEL_NAMES_CL[i] for i in model_pred],
        model_top_prob=model_top_prob,
        cleanlab_flagged=is_flagged,
        # Rank of this row among flagged (lower = more suspicious)
        cleanlab_rank=pd.Series(
            np.where(
                is_flagged,
                np.argsort(np.argsort(self_confidence)),
                -1,
            ),
            index=df_labeled.index,
        ),
    )
    return (df_audited,)


@app.cell
def cleanlab_results(df_audited, mo, np, pd, plt):
    """Show cleanlab's flagged set and how well it lines up with the
    hidden ground truth corruption."""
    total_flagged = int(df_audited["cleanlab_flagged"].sum())
    total_errors = int((df_audited["corruption"] != "clean").sum())

    # Recall of flagged set vs real corruption, broken down by type
    flagged = df_audited[df_audited["cleanlab_flagged"]]
    breakdown = (
        flagged.groupby("corruption").size().rename("flagged_count")
    )
    ground_truth = (
        df_audited[df_audited["corruption"] != "clean"]
        .groupby("corruption")
        .size()
        .rename("total_count")
    )
    cl_table = (
        pd.concat([ground_truth, breakdown], axis=1)
        .fillna(0)
        .astype(int)
        .assign(
            recall=lambda d: (d["flagged_count"] / d["total_count"]).round(
                3
            )
        )
        .reset_index()
    )

    # Precision / recall curve vs budget K
    sorted_by_conf = df_audited.sort_values("self_confidence")
    is_error = (sorted_by_conf["corruption"] != "clean").to_numpy()
    cum_true_positives = np.cumsum(is_error)
    ks = np.arange(1, len(sorted_by_conf) + 1)
    precision_at_k = cum_true_positives / ks
    recall_at_k = cum_true_positives / max(total_errors, 1)

    fig_pr, ax_pr = plt.subplots(1, 2, figsize=(11, 4))
    ax_pr[0].plot(ks, precision_at_k, color="#4477aa")
    ax_pr[0].axvline(
        total_flagged,
        color="red",
        linestyle="--",
        label=f"cleanlab budget ({total_flagged})",
    )
    ax_pr[0].set_xlabel("K (top-K lowest self_confidence)")
    ax_pr[0].set_ylabel("precision")
    ax_pr[0].set_title("Precision vs review budget")
    ax_pr[0].set_ylim(0, 1.05)
    ax_pr[0].grid(alpha=0.3)
    ax_pr[0].legend(fontsize=8)

    ax_pr[1].plot(ks, recall_at_k, color="#228833")
    ax_pr[1].axvline(
        total_flagged, color="red", linestyle="--"
    )
    ax_pr[1].set_xlabel("K (top-K lowest self_confidence)")
    ax_pr[1].set_ylabel("recall of real errors")
    ax_pr[1].set_title("Recall vs review budget")
    ax_pr[1].set_ylim(0, 1.05)
    ax_pr[1].grid(alpha=0.3)

    fig_pr.tight_layout()

    mo.vstack(
        [
            mo.md(
                f"**Flagged by cleanlab: `{total_flagged}` / "
                f"{len(df_audited)} rows ({total_flagged / len(df_audited):.1%}).**\n\n"
                f"Real corruption total: `{total_errors}`."
            ),
            mo.md("### Recall by corruption type"),
            mo.ui.table(cl_table),
            mo.md(
                "### Precision / recall vs review budget K\n\n"
                "The vertical red line is cleanlab's own chosen budget. "
                "Moving K right catches more errors at lower precision -- "
                "useful when feeding the review set to a cheap LLM judge."
            ),
            mo.as_html(fig_pr),
        ]
    )
    return


@app.cell
def step3_md(mo):
    mo.md(r"""
    ## Step 3 -- LLM-as-judge on the flagged subset

    Cleanlab catches *random* label noise well but struggles on
    *systematic* confusion -- if Sports and Business are
    consistently swapped, the model learns the swap and doesn't
    flag it as disagreement. That's what a semantic judge is for.

    Rather than sending every row to the judge (expensive), we
    send only the top `K_JUDGE` flagged rows from cleanlab plus a
    small random sample of unflagged rows (as a false-negative
    audit). For each row we ask the judge: "does this label look
    right, and if not, what is correct?"
    """)
    return


@app.cell
def judge_controls(K_JUDGE, LLM_MODEL_NAME, mo, os):
    """Gate the judge behind a button to avoid accidental spend on
    every notebook re-run."""
    have_key = "LLM_API_KEY" in os.environ or "OPENAI_API_KEY" in os.environ
    have_base = "LLM_BASE_URL" in os.environ or "OPENAI_BASE_URL" in os.environ

    run_judge_button = mo.ui.run_button(
        label=f"Run LLM judge on top {K_JUDGE} flagged rows",
        kind="danger",
    )

    _status_lines = [
        f"- `LLM_API_KEY`: {'✓ set' if have_key else '✗ not set (required)'}",
        f"- `LLM_BASE_URL`: {'✓ set' if have_base else '· default (OpenAI)'}",
        f"- Model: `{LLM_MODEL_NAME}`",
        f"- Budget: `{K_JUDGE}` LLM calls",
    ]

    mo.vstack(
        [
            mo.md("### Judge configuration\n\n" + "\n".join(_status_lines)),
            run_judge_button,
            mo.md(
                "_Click the button to actually spend tokens. The judge "
                "is idempotent for a given seed, so re-running the "
                "notebook without clicking won't issue new calls._"
            ),
        ]
    )
    return (run_judge_button,)


@app.cell
def judge_prompt_preview(LABEL_NAMES, df_audited, mo):
    """Show exactly what we'd send to the judge for the top flagged
    row. Makes the judge's contract obvious before any money moves."""
    _top = df_audited[df_audited["cleanlab_flagged"]].sort_values(
        "self_confidence"
    )
    if len(_top) == 0:
        _preview = mo.md("_No flagged rows -- nothing for the judge to review._")
    else:
        _row = _top.iloc[0]
        _system = (
            "You are an expert label auditor for a text classification "
            "dataset. You will be shown a short piece of text and the "
            "category a human labeler assigned to it. Your job is to "
            "verify whether that label is correct. Be strict: only "
            "approve the label if it is clearly the best fit among the "
            "valid options. Never invent new categories."
        )
        _user = (
            "Valid categories: "
            f"{', '.join(LABEL_NAMES)}\n\n"
            f"Text: {_row['data']}\n\n"
            f"Assigned label: {_row['untrustworthy_label']}\n\n"
            "Respond on exactly two lines:\n"
            "VERDICT: YES or NO\n"
            "CORRECT_LABEL: one of the valid categories, or SAME if verdict is YES"
        )
        _preview = mo.md(
            f"""
            ### Example prompt (for the most-suspicious row)

            **System:**

            ```
            {_system}
            ```

            **User:**

            ```
            {_user}
            ```
            """
        )
    _preview
    return


@app.cell
def run_judge(
    K_JUDGE,
    LABEL_NAMES,
    LLM_MODEL_NAME,
    df_audited,
    llm_pkg,
    mo,
    pd,
    run_judge_button,
):
    """Run the LLM judge on the top-K flagged rows. Gated by the
    button above so notebook re-runs don't re-spend."""
    if not run_judge_button.value:
        judge_results = pd.DataFrame(
            columns=[
                "row_id",
                "verdict",
                "corrected_label",
                "raw_response",
            ]
        )
        _status = mo.md(
            "_Judge not yet run. Click the button above to send calls._"
        )
    else:
        _top_flagged = (
            df_audited[df_audited["cleanlab_flagged"]]
            .sort_values("self_confidence")
            .head(K_JUDGE)
        )
        try:
            _model = llm_pkg.get_model(LLM_MODEL_NAME)
        except Exception as exc:
            judge_results = pd.DataFrame(
                columns=[
                    "row_id",
                    "verdict",
                    "corrected_label",
                    "raw_response",
                ]
            )
            _status = mo.md(
                f"**LLM judge failed to initialize: `{exc}`.** "
                "Check `LLM_API_KEY` / `LLM_BASE_URL` and that the "
                f"model `{LLM_MODEL_NAME}` is installed via "
                "`llm install ...` or the openai backend."
            )
            _top_flagged = _top_flagged.iloc[0:0]

        _system = (
            "You are an expert label auditor for a text classification "
            "dataset. You will be shown a short piece of text and the "
            "category a human labeler assigned to it. Your job is to "
            "verify whether that label is correct. Be strict: only "
            "approve the label if it is clearly the best fit among the "
            "valid options. Never invent new categories."
        )

        _rows_out = []
        for _, _row in _top_flagged.iterrows():
            _user = (
                f"Valid categories: {', '.join(LABEL_NAMES)}\n\n"
                f"Text: {_row['data']}\n\n"
                f"Assigned label: {_row['untrustworthy_label']}\n\n"
                "Respond on exactly two lines:\n"
                "VERDICT: YES or NO\n"
                "CORRECT_LABEL: one of the valid categories, "
                "or SAME if verdict is YES"
            )
            try:
                _resp = _model.prompt(_user, system=_system)
                _text = _resp.text()
            except Exception as exc:  # noqa: BLE001
                _text = f"__ERROR__ {exc}"

            _verdict = "UNKNOWN"
            _corrected = None
            for _line in _text.strip().splitlines():
                _line = _line.strip()
                if _line.upper().startswith("VERDICT:"):
                    _v = _line.split(":", 1)[1].strip().upper()
                    if _v in ("YES", "NO"):
                        _verdict = _v
                elif _line.upper().startswith("CORRECT_LABEL:"):
                    _c = _line.split(":", 1)[1].strip()
                    if _c.upper() == "SAME":
                        _corrected = _row["untrustworthy_label"]
                    elif _c in LABEL_NAMES:
                        _corrected = _c

            _rows_out.append(
                {
                    "row_id": int(_row["row_id"]),
                    "verdict": _verdict,
                    "corrected_label": _corrected,
                    "raw_response": _text,
                }
            )

        judge_results = pd.DataFrame(_rows_out)
        _n_yes = int((judge_results["verdict"] == "YES").sum())
        _n_no = int((judge_results["verdict"] == "NO").sum())
        _n_unk = int((judge_results["verdict"] == "UNKNOWN").sum())
        _status = mo.md(
            f"**Judge results:** `{_n_yes}` approved, `{_n_no}` rejected, "
            f"`{_n_unk}` unparsed out of {len(judge_results)} calls."
        )

    _status
    return (judge_results,)


@app.cell
def step4_md(mo):
    mo.md(r"""
    ## Step 4 -- Final trust score and review set

    Combine all four signals into a per-row `trust_score` and a
    `review_action` recommendation:

    - **cleanlab flagged** + **judge rejected** → high confidence mislabel, use judge's `corrected_label`
    - **cleanlab flagged** + **judge approved** → likely OK, keep original, note as ambiguous
    - **cleanlab flagged** + **no judge call** → needs human review
    - **not flagged** → trust as-is
    """)
    return


@app.cell
def final_review_set(df_audited, judge_results, mo, pd):
    """Join the judge verdicts back onto the audited dataframe,
    compute a simple `trust_score`, and surface the top review set."""
    df_out = df_audited.merge(judge_results, on="row_id", how="left")

    def _score_row(r):
        if not r["cleanlab_flagged"]:
            return 0.8 + 0.2 * r["self_confidence"]
        # Flagged by cleanlab
        if r["verdict"] == "NO":
            return 0.05  # judge agrees it's wrong
        if r["verdict"] == "YES":
            return 0.6  # judge overrules cleanlab
        return 0.3  # flagged but not yet judged

    df_out["trust_score"] = df_out.apply(_score_row, axis=1)

    def _action(r):
        if r["verdict"] == "NO" and pd.notna(r["corrected_label"]):
            return "relabel"
        if r["verdict"] == "YES":
            return "keep (ambiguous)"
        if r["cleanlab_flagged"]:
            return "needs_review"
        return "keep"

    df_out["review_action"] = df_out.apply(_action, axis=1)

    # Surface the top-25 most suspicious rows for human inspection
    review_display = (
        df_out.sort_values("trust_score")
        .head(25)[
            [
                "row_id",
                "data",
                "untrustworthy_label",
                "model_pred",
                "verdict",
                "corrected_label",
                "trust_score",
                "review_action",
            ]
        ]
        .assign(
            data=lambda d: d["data"].str.slice(0, 90) + "...",
            trust_score=lambda d: d["trust_score"].round(3),
        )
    )

    action_counts = df_out["review_action"].value_counts().reset_index()
    action_counts.columns = ["action", "count"]

    mo.vstack(
        [
            mo.md("### Review actions by bucket"),
            mo.ui.table(action_counts),
            mo.md("### Top-25 most suspicious rows"),
            mo.ui.table(review_display),
        ]
    )
    return (df_out,)


@app.cell
def evaluation_md(mo):
    mo.md(r"""
    ## Evaluation -- how well did the audits work?

    We know the ground truth corruption, so we can measure each
    audit's **precision** (of what we flagged, how much was actually
    wrong) and **recall** (of all real errors, how many we caught).
    These numbers are only possible because this is a synthetic
    demo; in production you'd spot-check a sample and trust the
    audits for the rest.
    """)
    return


@app.cell
def evaluation(df_out, mo, precision_score, recall_score):
    """Measure each audit's precision/recall on the injected errors."""
    is_real_error = (df_out["corruption"] != "clean").to_numpy()

    # 1. Cleanlab alone
    cl_flag = df_out["cleanlab_flagged"].to_numpy()

    # 2. Judge-confirmed (cleanlab flagged AND judge said NO)
    judge_confirmed = (
        df_out["cleanlab_flagged"].to_numpy()
        & (df_out["verdict"].fillna("").to_numpy() == "NO")
    )

    # 3. Combined (anything in review_action != keep)
    combined = (df_out["review_action"] != "keep").to_numpy()

    def _pr(pred):
        if pred.sum() == 0:
            return 0.0, 0.0
        p = precision_score(is_real_error, pred, zero_division=0)
        r = recall_score(is_real_error, pred, zero_division=0)
        return float(p), float(r)

    cl_p, cl_r = _pr(cl_flag)
    jc_p, jc_r = _pr(judge_confirmed)
    cb_p, cb_r = _pr(combined)

    # By corruption type, how many did cleanlab catch?
    by_type = (
        df_out[df_out["corruption"] != "clean"]
        .groupby("corruption")
        .agg(
            total=("cleanlab_flagged", "size"),
            caught_by_cleanlab=("cleanlab_flagged", "sum"),
            caught_by_judge=("verdict", lambda s: int((s == "NO").sum())),
        )
        .assign(
            cleanlab_recall=lambda d: (
                d["caught_by_cleanlab"] / d["total"]
            ).round(3),
            judge_recall=lambda d: (
                d["caught_by_judge"] / d["total"]
            ).round(3),
        )
        .reset_index()
    )

    mo.md(
        f"""
        ### Overall metrics

        | Audit | Precision | Recall | Flagged count |
        |---|---:|---:|---:|
        | Cleanlab alone | `{cl_p:.3f}` | `{cl_r:.3f}` | `{int(cl_flag.sum())}` |
        | Judge-confirmed (cleanlab ∩ judge NO) | `{jc_p:.3f}` | `{jc_r:.3f}` | `{int(judge_confirmed.sum())}` |
        | Combined (review_action != keep) | `{cb_p:.3f}` | `{cb_r:.3f}` | `{int(combined.sum())}` |

        ### Recall by corruption type
        """
    )
    mo.ui.table(by_type)
    return


@app.cell
def closing_md(mo):
    mo.md(r"""
    ## What to do next

    1. **Export `review_action == 'relabel'` rows.** These are the
       highest-confidence errors -- cleanlab flagged AND the judge
       confirmed. Feed the judge's `corrected_label` back into
       your labeling pipeline.
    2. **Spot-check `needs_review` by hand.** These are flagged
       but un-judged (either over budget or the judge said YES
       ambiguously). Your human reviewer time is best spent here.
    3. **Keep `keep (ambiguous)` in the training set** but log
       them -- if fine-tuning loss stays high on these at epoch
       end, they're probably genuinely hard examples, not
       mislabels.
    4. **Adjust `K_JUDGE` upwards** if the recall curve at the top
       of the notebook shows you're leaving errors on the table
       by stopping at the cleanlab default budget.

    ## LLM-as-judge vs LLM-as-labeler

    This notebook *judges* the human labels -- it keeps them where
    they're right and flags them where they're wrong. The
    alternative is to *replace* the human labels entirely with LLM
    labels. When to prefer each:

    - **Judge (this notebook)**: default choice. Preserves human
      signal on hard/ambiguous cases, focuses LLM spend on the
      2-10% of rows that are actually suspicious.
    - **Full LLM labeling**: only when you suspect the human
      labelers are essentially guessing (> 30% error rate) or
      when you have no human labels at all.

    Don't skip the provenance audit -- structural bugs
    (off-by-one, row misalignment) will survive both strategies
    and silently poison your fine-tune.
    """)
    return


if __name__ == "__main__":
    app.run()
