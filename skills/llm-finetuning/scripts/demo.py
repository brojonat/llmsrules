# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#     "marimo",
#     "unsloth",
#     "torch",
#     "trl>=0.8",
#     "datasets>=2.19",
#     "ipython",
#     "ipywidgets",
#     "mlflow>=2.14",
#     "scikit-learn>=1.5",
#     "numpy>=1.26",
#     "matplotlib>=3.9",
# ]
# ///
"""Worked example for the llm-finetuning bundle.

Fine-tunes a small LLM (Gemma-4 E2B by default) on AG News text
classification using Unsloth + QLoRA. Compares zero-shot vs fine-tuned
performance and logs everything to MLflow for cross-model comparison.

Requires a CUDA GPU with >= 8 GB VRAM. If unsloth fails to install
via --sandbox, install manually in a venv:

    pip install unsloth torch trl datasets mlflow scikit-learn numpy matplotlib marimo
    marimo edit demo.py

Otherwise:

    marimo edit --sandbox demo.py
"""

import marimo

__generated_with = "0.23.1"
app = marimo.App(width="medium")


@app.cell
def imports():
    import re
    # unsloth must be imported before trl/transformers/peft
    from unsloth import FastModel
    from unsloth.chat_templates import get_chat_template, train_on_responses_only
    import marimo as mo
    import matplotlib.pyplot as plt
    import mlflow
    import numpy as np
    import torch
    from datasets import load_dataset
    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        f1_score,
        precision_recall_fscore_support,
    )
    from trl import SFTConfig, SFTTrainer

    return (
        FastModel,
        SFTConfig,
        SFTTrainer,
        accuracy_score,
        confusion_matrix,
        f1_score,
        get_chat_template,
        load_dataset,
        mlflow,
        mo,
        np,
        plt,
        precision_recall_fscore_support,
        re,
        torch,
        train_on_responses_only,
    )


@app.cell
def title(mo):
    mo.md(r"""
    # LLM Fine-Tuning with Unsloth (Done Right)

    Fine-tune small open-weight LLMs locally for text classification.
    This notebook demonstrates:

    1. **Model selection** -- swap models via dropdown, compare in MLflow
    2. **QLoRA fine-tuning** -- 4-bit quantization via Unsloth for 8 GB GPUs
    3. **Zero-shot vs fine-tuned** -- quantify what fine-tuning buys you
    4. **MLflow experiment tracking** -- log every run for comparison
    5. **GGUF export** -- deploy with llama.cpp, no Python runtime needed

    The demo task is AG News classification (4 classes: World, Sports,
    Business, Sci/Tech). The same pipeline works for any text
    classification, extraction, or instruction-following task.
    """)
    return


@app.cell
def config(mo):
    """Model and training configuration.

    MODELS maps HuggingFace model IDs to their chat template settings.
    To add a model: add an entry with its unsloth chat_template name
    and the instruction/response delimiter tokens used by
    train_on_responses_only.
    """

    MODELS = {
        "unsloth/SmolLM2-135M-Instruct": {
            "template": "chatml",
            "mask_user": "<|im_start|>user\n",
            "mask_model": "<|im_start|>assistant\n",
            "load_in_4bit": False,
        },
        "unsloth/gemma-4-E2B-it": {
            "template": "gemma-4-thinking",
            "mask_user": "<|turn>user\n",
            "mask_model": "<|turn>model\n",
            "load_in_4bit": True,
        },
        "unsloth/Llama-3.2-1B-Instruct": {
            "template": "llama-3.1",
            "mask_user": "<|start_header_id|>user<|end_header_id|>\n\n",
            "mask_model": "<|start_header_id|>assistant<|end_header_id|>\n\n",
            "load_in_4bit": True,
        },
        "unsloth/Llama-3.2-3B-Instruct": {
            "template": "llama-3.1",
            "mask_user": "<|start_header_id|>user<|end_header_id|>\n\n",
            "mask_model": "<|start_header_id|>assistant<|end_header_id|>\n\n",
            "load_in_4bit": True,
        },
        "unsloth/Qwen3-0.6B": {
            "template": "qwen-2.5",
            "mask_user": "<|im_start|>user\n",
            "mask_model": "<|im_start|>assistant\n",
            "load_in_4bit": True,
        },
    }
    model_dropdown = mo.ui.dropdown(
        options=list(MODELS.keys()),
        value="unsloth/SmolLM2-135M-Instruct",
        label="Model",
    )
    max_steps_input = mo.ui.number(
        value=150,
        start=10,
        stop=2000,
        step=10,
        label="Max training steps",
    )
    N_TRAIN = 1000
    N_EVAL = 200
    mo.md(f"""
    ## Configuration

    {model_dropdown}

    {max_steps_input}

    Training examples: **{N_TRAIN}** | Eval examples: **{N_EVAL}**
    """)
    return MODELS, N_EVAL, N_TRAIN, max_steps_input, model_dropdown


@app.cell
def load_data(N_EVAL, N_TRAIN, load_dataset, np):
    """Load AG News and split into train/eval subsets."""
    ag = load_dataset("ag_news", split="train")
    LABEL_NAMES = ["World", "Sports", "Business", "Sci/Tech"]
    ag_shuffled = ag.shuffle(seed=42)
    train_subset = ag_shuffled.select(range(N_TRAIN))
    eval_subset = ag_shuffled.select(range(N_TRAIN, N_TRAIN + N_EVAL))
    eval_texts = [row["text"] for row in eval_subset]
    eval_labels = np.array([row["label"] for row in eval_subset])
    return LABEL_NAMES, eval_labels, eval_texts, train_subset


@app.cell
def show_data(LABEL_NAMES, eval_labels, mo, train_subset):
    train_counts = {}
    for row in train_subset:
        lbl = LABEL_NAMES[row["label"]]
        train_counts[lbl] = train_counts.get(lbl, 0) + 1
    table_md = "\n".join(
        f"| {name} | {train_counts.get(name, 0)} |"
        for name in LABEL_NAMES
    )
    mo.md(f"""
    ## Dataset: AG News (text classification)

    4-class news article classification. Each article maps to one of:
    World, Sports, Business, Sci/Tech.

    | Category | Train count |
    |---|---|
    {table_md}

    | Split | Count |
    |---|---|
    | Train | {len(train_subset)} |
    | Eval | {len(eval_labels)} |

    **In production**, replace AG News with your own labeled data.
    Format each example as an instruction-tuning pair: the user message
    is the text with a task prompt, the assistant message is the label.
    """)
    return


@app.cell
def make_classifier(re, torch):
    """Shared inference helper for zero-shot and fine-tuned evaluation."""


    def _strip_thinking(text):
        """Remove <think>...</think> blocks from model output."""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if not cleaned and "</think>" in text:
            cleaned = text.split("</think>")[-1].strip()
        return cleaned if cleaned else text


    def classify_batch(model, tokenizer, texts, label_names):
        """Inference helper. Works with text-only tokenizers and multimodal
        processors. Suppresses Qwen3 thinking via /no_think instruction."""
        model.eval()
        preds = []
        raw_responses = []
        for text in texts:
            messages = [
                {
                    "role": "user",
                    "content": (
                        "Classify this news article into exactly one "
                        f"category: {', '.join(label_names)}. "
                        "Reply with just the category name. /no_think\n\n"
                        f"{text}"
                    ),
                },
            ]
            try:
                prompt_text = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                    enable_thinking=False,
                )
            except (TypeError, ValueError):
                prompt_text = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            inputs = tokenizer(text=prompt_text, return_tensors="pt").to(
                model.device
            )
            input_len = inputs["input_ids"].shape[1]
            with torch.no_grad():
                output = model.generate(
                    **inputs,
                    max_new_tokens=16,
                    do_sample=False,
                )
            response = tokenizer.decode(
                output[0][input_len:],
                skip_special_tokens=True,
            ).strip()
            raw_responses.append(response)
            cleaned = _strip_thinking(response)
            pred = -1
            cleaned_lower = cleaned.lower()
            for idx, name in enumerate(label_names):
                if name.lower() in cleaned_lower:
                    pred = idx
                    break
            preds.append(pred)
        return preds, raw_responses

    return (classify_batch,)


@app.cell
def load_model_cell(
    FastModel,
    MODELS,
    get_chat_template,
    model_dropdown,
    torch,
):
    """Load model with QLoRA + LoRA adapters + chat template."""
    _model_name = model_dropdown.value
    _cfg = MODELS[_model_name]
    _use_4bit = _cfg.get("load_in_4bit", True)
    model, tokenizer = FastModel.from_pretrained(
        model_name=_model_name,
        dtype=None,
        max_seq_length=2048,
        load_in_4bit=_use_4bit,
        full_finetuning=False,
    )
    model = FastModel.get_peft_model(
        model,
        finetune_vision_layers=False,
        finetune_language_layers=True,
        finetune_attention_modules=True,
        finetune_mlp_modules=True,
        r=8,
        lora_alpha=8,
        lora_dropout=0,
        bias="none",
        random_state=3407,
    )
    tokenizer = get_chat_template(tokenizer, chat_template=_cfg["template"])
    # Turing GPUs (compute < 8.0): disable flex_attention and torch.compile
    # (flex_attention and FX tracing fail on these architectures)
    if torch.cuda.is_available() and torch.cuda.get_device_capability()[0] < 8:
        model.config._attn_implementation = "eager"
        torch._dynamo.config.suppress_errors = True
        torch._dynamo.config.disable = True
    return model, tokenizer


@app.cell
def format_train_data(LABEL_NAMES, tokenizer, train_subset):
    """Format training data as chat conversations for SFTTrainer."""
    bos = tokenizer.bos_token or ""

    def _format(row):
        messages = [
            {
                "role": "user",
                "content": (
                    "Classify this news article into exactly one "
                    "category: "
                    f"{', '.join(LABEL_NAMES)}.\n\n{row['text']}"
                ),
            },
            {"role": "assistant", "content": LABEL_NAMES[row["label"]]},
        ]
        text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False,
        )
        # SFTTrainer adds BOS — strip it from formatted text to avoid duplication
        if bos and text.startswith(bos):
            text = text[len(bos):]
        return {"formatted_text": text}

    formatted_dataset = train_subset.map(_format)
    return (formatted_dataset,)


@app.cell
def zs_section(mo):
    mo.md(r"""
    ## Zero-shot evaluation (before training)

    The base model with freshly-initialized LoRA adapters (which output
    zero at init, so this IS the base model). How well does the
    pre-trained model classify news without any fine-tuning?
    """)
    return


@app.cell
def zero_shot_eval(
    LABEL_NAMES,
    classify_batch,
    eval_texts,
    model,
    np,
    tokenizer,
):
    zs_preds_raw, zs_responses = classify_batch(
        model, tokenizer, eval_texts, LABEL_NAMES,
    )
    zs_preds = np.array(zs_preds_raw)
    return zs_preds, zs_responses


@app.cell
def train_section_md(mo):
    mo.md(r"""
    ## Fine-tune with QLoRA

    `SFTTrainer` from TRL handles the training loop.
    `train_on_responses_only` masks instruction tokens so the model
    only learns to predict the label, not the prompt. All params and
    metrics are logged to MLflow.
    """)
    return


@app.cell
def train_model(
    MODELS,
    SFTConfig,
    SFTTrainer,
    formatted_dataset,
    max_steps_input,
    mlflow,
    model,
    model_dropdown,
    tokenizer,
    torch,
    train_on_responses_only,
):
    _model_name = model_dropdown.value
    _cfg = MODELS[_model_name]
    _max_steps = max_steps_input.value

    mlflow.set_experiment("llm-finetuning")
    with mlflow.start_run(run_name=_model_name.split("/")[-1]) as active_run:
        mlflow.log_params(
            {
                "model_name": _model_name,
                "lora_r": 8,
                "lora_alpha": 8,
                "max_seq_length": 2048,
                "load_in_4bit": _cfg.get("load_in_4bit", True),
                "max_steps": _max_steps,
                "learning_rate": 2e-4,
                "per_device_train_batch_size": 1,
                "gradient_accumulation_steps": 4,
            }
        )

        # Use fp16 on Turing GPUs (no bf16 support), bf16 on Ampere+
        _use_bf16 = (
            torch.cuda.is_available()
            and torch.cuda.get_device_capability()[0] >= 8
        )
        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            train_dataset=formatted_dataset,
            dataset_num_proc=1,
            args=SFTConfig(
                output_dir="/tmp/llm-ft-demo",
                dataset_text_field="formatted_text",
                per_device_train_batch_size=1,
                gradient_accumulation_steps=4,
                warmup_steps=5,
                max_steps=_max_steps,
                learning_rate=2e-4,
                logging_steps=1,
                optim="adamw_8bit",
                weight_decay=0.001,
                lr_scheduler_type="linear",
                seed=3407,
                save_strategy="no",
                report_to="none",
                fp16=not _use_bf16,
                bf16=_use_bf16,
            ),
        )
        trainer = train_on_responses_only(
            trainer,
            instruction_part=_cfg["mask_user"],
            response_part=_cfg["mask_model"],
        )
        trainer_stats = trainer.train()
        mlflow.log_metric("train_loss", trainer_stats.training_loss)
        run_id = active_run.info.run_id
    return (run_id,)


@app.cell
def ft_section(mo):
    mo.md(r"""
    ## Fine-tuned evaluation

    Same eval set, same prompt format. The LoRA weights have now been
    updated by training. Compare against the zero-shot predictions
    captured before training.
    """)
    return


@app.cell
def finetuned_eval(
    LABEL_NAMES,
    classify_batch,
    eval_texts,
    model,
    np,
    tokenizer,
):
    ft_preds_raw, ft_responses = classify_batch(
        model, tokenizer, eval_texts, LABEL_NAMES,
    )
    ft_preds = np.array(ft_preds_raw)
    return ft_preds, ft_responses


@app.cell
def comparison(
    accuracy_score,
    eval_labels,
    f1_score,
    ft_preds,
    mlflow,
    mo,
    run_id,
    zs_preds,
):
    """Compute metrics, log to MLflow, display comparison table."""

    def _metrics(preds, labels):
        valid = preds >= 0
        if valid.sum() == 0:
            return 0.0, 0.0, 0.0
        acc = float(accuracy_score(labels[valid], preds[valid]))
        f1 = float(
            f1_score(labels[valid], preds[valid], average="macro", zero_division=0)
        )
        parse_rate = float(valid.mean())
        return acc, f1, parse_rate

    zs_acc, zs_f1, zs_parse = _metrics(zs_preds, eval_labels)
    ft_acc, ft_f1, ft_parse = _metrics(ft_preds, eval_labels)

    with mlflow.start_run(run_id=run_id):
        mlflow.log_metrics({
            "zs_accuracy": zs_acc,
            "zs_f1_macro": zs_f1,
            "zs_parse_rate": zs_parse,
            "ft_accuracy": ft_acc,
            "ft_f1_macro": ft_f1,
            "ft_parse_rate": ft_parse,
        })

    def _fmt(zs_val, ft_val):
        delta = ft_val - zs_val
        return f"`{zs_val:.4f}` -> `{ft_val:.4f}` ({delta:+.4f})"

    mo.md(f"""
    ## Zero-shot vs Fine-tuned

    | Metric | Zero-shot -> Fine-tuned |
    |---|---|
    | Accuracy | {_fmt(zs_acc, ft_acc)} |
    | F1 macro | {_fmt(zs_f1, ft_f1)} |
    | Parse rate | {_fmt(zs_parse, ft_parse)} |

    **Parse rate** = fraction of responses that contained a valid label
    name. Low zero-shot parse rate means the base model doesn't follow
    the classification format -- fine-tuning teaches it.
    """)
    return


@app.cell
def confusion_section(mo):
    mo.md(r"""
    ## Confusion matrix (fine-tuned model)

    Which classes get confused for which? Two views: raw counts and
    row-normalized (per-class recall on the diagonal).
    """)
    return


@app.cell
def confusion_plot(
    LABEL_NAMES,
    confusion_matrix,
    eval_labels,
    ft_preds,
    mo,
    plt,
    zs_preds,
):
    """Side-by-side confusion matrices: zero-shot vs fine-tuned."""
    _n_cls_cm = len(LABEL_NAMES)

    def _cm_pair(preds):
        valid = preds >= 0
        if valid.sum() == 0:
            return None, None
        raw = confusion_matrix(
            eval_labels[valid], preds[valid],
            labels=list(range(_n_cls_cm)),
        )
        norm = raw.astype(float) / raw.sum(axis=1, keepdims=True).clip(min=1)
        return raw, norm

    zs_raw, zs_norm = _cm_pair(zs_preds)
    ft_raw, ft_norm = _cm_pair(ft_preds)

    if zs_raw is None or ft_raw is None:
        _cm_out = mo.md("_Not enough valid predictions for confusion matrices._")
    else:
        # Shared color scale across models for the counts column
        vmax_raw = int(max(zs_raw.max(), ft_raw.max()))
        fig_cm, axes_cm = plt.subplots(2, 2, figsize=(11, 9))
        _rows_cm = [
            ("zero-shot", zs_raw, zs_norm),
            ("fine-tuned", ft_raw, ft_norm),
        ]
        for ri, (label, raw_mat, norm_mat) in enumerate(_rows_cm):
            for ci_cm, (mat, fmt_str, title_suffix, vmax) in enumerate([
                (raw_mat, "d", "counts", vmax_raw),
                (norm_mat, ".2f", "recall (row-normalized)", 1.0),
            ]):
                ax = axes_cm[ri, ci_cm]
                im = ax.imshow(mat, cmap="Blues", vmin=0, vmax=vmax)
                ax.set_xticks(range(_n_cls_cm))
                ax.set_yticks(range(_n_cls_cm))
                ax.set_xticklabels(
                    LABEL_NAMES, rotation=45, ha="right", fontsize=8,
                )
                ax.set_yticklabels(LABEL_NAMES, fontsize=8)
                ax.set_xlabel("predicted")
                ax.set_ylabel("true")
                ax.set_title(f"{label} -- {title_suffix}")
                thresh_cm = vmax / 2 if vmax > 0 else 0.5
                for ii in range(_n_cls_cm):
                    for jj in range(_n_cls_cm):
                        ax.text(
                            jj, ii, format(mat[ii, jj], fmt_str),
                            ha="center", va="center", fontsize=8,
                            color="white" if mat[ii, jj] > thresh_cm else "black",
                        )
                fig_cm.colorbar(im, ax=ax, fraction=0.046)
        fig_cm.suptitle(
            "Confusion matrices: zero-shot (top) vs fine-tuned (bottom)",
            fontsize=12,
        )
        fig_cm.tight_layout()
        _cm_out = mo.as_html(fig_cm)
    _cm_out
    return


@app.cell
def per_class_plot(
    LABEL_NAMES,
    eval_labels,
    ft_preds,
    mo,
    np,
    plt,
    precision_recall_fscore_support,
    zs_preds,
):
    """Grouped per-class precision/recall/F1: zero-shot (faded) vs fine-tuned (solid)."""
    _n_cls_pc = len(LABEL_NAMES)

    def _pr_f1(preds):
        valid = preds >= 0
        if valid.sum() == 0:
            z = np.zeros(_n_cls_pc)
            return z, z, z, z.astype(int)
        return precision_recall_fscore_support(
            eval_labels[valid], preds[valid],
            labels=list(range(_n_cls_pc)), zero_division=0,
        )

    zs_p, zs_r, zs_f1, _ = _pr_f1(zs_preds)
    ft_p, ft_r, ft_f1, ft_sup = _pr_f1(ft_preds)

    if int((ft_preds >= 0).sum()) + int((zs_preds >= 0).sum()) < 10:
        _pc_out = mo.md("_Not enough valid predictions for per-class metrics._")
    else:
        x_pc = np.arange(_n_cls_pc)
        bar_w = 0.13
        fig_pc, ax_pc = plt.subplots(figsize=(11, 5))
        # zero-shot (faded)
        ax_pc.bar(x_pc - 2.5 * bar_w, zs_p, bar_w,
                  color="#4477aa", alpha=0.4, label="precision (zs)")
        ax_pc.bar(x_pc - 1.5 * bar_w, zs_r, bar_w,
                  color="#ee8866", alpha=0.4, label="recall (zs)")
        ax_pc.bar(x_pc - 0.5 * bar_w, zs_f1, bar_w,
                  color="#228833", alpha=0.4, label="F1 (zs)")
        # fine-tuned (solid)
        ax_pc.bar(x_pc + 0.5 * bar_w, ft_p, bar_w,
                  color="#4477aa", label="precision (ft)")
        ax_pc.bar(x_pc + 1.5 * bar_w, ft_r, bar_w,
                  color="#ee8866", label="recall (ft)")
        ax_pc.bar(x_pc + 2.5 * bar_w, ft_f1, bar_w,
                  color="#228833", label="F1 (ft)")
        ax_pc.set_xticks(x_pc)
        ax_pc.set_xticklabels(
            [f"{name}\n(n={int(ft_sup[ki])})" for ki, name in enumerate(LABEL_NAMES)],
            fontsize=9,
        )
        ax_pc.set_ylim(0, 1.05)
        ax_pc.set_ylabel("score")
        ax_pc.set_title(
            "Per-class precision / recall / F1 -- zero-shot (faded) vs fine-tuned (solid)"
        )
        ax_pc.legend(loc="lower right", fontsize=8, ncol=2)
        ax_pc.grid(axis="y", alpha=0.3)
        fig_pc.tight_layout()
        _pc_out = mo.as_html(fig_pc)
    _pc_out
    return


@app.cell
def transition_analysis(
    LABEL_NAMES,
    eval_labels,
    eval_texts,
    ft_preds,
    ft_responses,
    mo,
    np,
    zs_preds,
    zs_responses,
):
    """Where did fine-tuning help, hurt, or leave things unchanged?"""
    _zs_ok = (zs_preds == eval_labels)
    _ft_ok = (ft_preds == eval_labels)
    _n_tx = len(eval_labels)

    _masks = {
        "kept_correct":  _zs_ok & _ft_ok,
        "regressed":     _zs_ok & ~_ft_ok,
        "fixed":         ~_zs_ok & _ft_ok,
        "still_wrong":   ~_zs_ok & ~_ft_ok,
    }
    _counts = {k: int(m.sum()) for k, m in _masks.items()}
    _net = _counts["fixed"] - _counts["regressed"]

    def _label_or_raw(pred, raw_response):
        if pred >= 0:
            return LABEL_NAMES[pred]
        return f"parse fail: `{raw_response[:40]}`"

    def _examples_md(mask_key, limit=8):
        idx = np.where(_masks[mask_key])[0]
        if len(idx) == 0:
            return "_(none)_"
        rows_md = []
        for i in idx[:limit]:
            snippet = eval_texts[i][:110].replace("\n", " ")
            true_name = LABEL_NAMES[eval_labels[i]]
            zs_str = _label_or_raw(zs_preds[i], zs_responses[i])
            ft_str = _label_or_raw(ft_preds[i], ft_responses[i])
            rows_md.append(
                f"- **{true_name}** / zs: _{zs_str}_ / ft: _{ft_str}_<br>"
                f"  <small>{snippet}...</small>"
            )
        suffix = (
            f"\n\n_... and {len(idx) - limit} more_"
            if len(idx) > limit else ""
        )
        return "\n".join(rows_md) + suffix

    _accordion = mo.accordion(
        {
            f"**Fixed** ({_counts['fixed']}) — zs wrong → ft correct":
                mo.md(_examples_md("fixed")),
            f"**Regressed** ({_counts['regressed']}) — zs correct → ft wrong":
                mo.md(_examples_md("regressed")),
            f"**Still wrong** ({_counts['still_wrong']}) — both models missed":
                mo.md(_examples_md("still_wrong")),
            f"**Kept correct** ({_counts['kept_correct']}) — both right":
                mo.md(_examples_md("kept_correct")),
        }
    )

    _summary = mo.md(f"""
    ## What did fine-tuning change?

    |                 | **ft correct** | **ft wrong** |
    |---|---:|---:|
    | **zs correct**  | {_counts['kept_correct']} _(kept)_ | {_counts['regressed']} _(**regressed**)_ |
    | **zs wrong**    | {_counts['fixed']} _(**fixed**)_ | {_counts['still_wrong']} _(still wrong)_ |

    **Net change:** `{_net:+d}` examples correct ( = {_counts['fixed']} fixed − {_counts['regressed']} regressed ) out of {_n_tx}.

    Expand each bucket below to inspect actual examples.
    """)

    mo.vstack([_summary, _accordion])
    return


@app.cell
def mlflow_runs(mo):
    mo.md(r"""
    ## Compare runs in MLflow

    Every training run is logged to the `llm-finetuning` experiment.
    To compare models: change the dropdown above, re-run the notebook,
    and each run is captured. Then launch the MLflow UI:

    ```bash
    mlflow ui --port 5000
    ```

    Open `http://localhost:5000` to see all runs side by side --
    params, metrics, and training loss curves. Filter by
    `params.model_name` to compare across model families.
    """)
    return


@app.cell
def export_section(mo):
    mo.md(r"""
    ## Export to GGUF for llama.cpp

    After fine-tuning, merge LoRA adapters and quantize to GGUF for
    deployment with llama.cpp (no Python runtime needed):

    ```python
    # Merge LoRA + quantize to GGUF
    model.save_pretrained_gguf(
        "finetuned-model",
        tokenizer,
        quantization_method="q4_k_m",  # good balance of size vs quality
    )
    ```

    Quantization options (smaller to larger):
    - `q4_k_m` -- 4-bit, recommended default (~3 GB for E2B)
    - `q8_0` -- 8-bit, higher quality (~5 GB for E2B)
    - `f16` -- 16-bit, no quantization loss (~9 GB for E2B)

    Then serve with llama.cpp:

    ```bash
    llama-server -m finetuned-model/unsloth.Q4_K_M.gguf \
        --port 8080 --ctx-size 2048
    ```
    """)
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    Six things to always do for LLM fine-tuning on text tasks:

    1. **Unsloth + QLoRA** (`load_in_4bit=True`) -- fits on consumer
       GPUs, 2x faster than vanilla HuggingFace
    2. **`train_on_responses_only`** -- mask instruction tokens so the
       model learns to predict labels, not to parrot the prompt
    3. **Always compare zero-shot vs fine-tuned** -- if zero-shot is
       good enough, you don't need to fine-tune
    4. **Log every run to MLflow** -- model name, training params,
       zero-shot metrics, fine-tuned metrics. Compare across models.
    5. **Per-class F1 + confusion matrix** -- same diagnostics as
       traditional classification. Rare classes will lag.
    6. **Export to GGUF + serve with llama.cpp** -- no Python runtime
       for inference, fast, deployable anywhere

    Drop the `SKILL.md` from this bundle into your project's
    `.claude/skills/llm-finetuning/` directory and your AI agent
    will follow the same workflow on your real data.
    """)
    return


if __name__ == "__main__":
    app.run()
