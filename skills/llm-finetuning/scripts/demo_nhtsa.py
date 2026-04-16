# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#     "marimo",
#     "unsloth",
#     "torch",
#     "trl>=0.8",
#     "ipython",
#     "ipywidgets",
#     "mlflow>=2.14",
#     "scikit-learn>=1.5",
#     "numpy==2.4.4",
#     "matplotlib==3.10.8",
#     "requests>=2.31",
#     "ibis-framework[duckdb]>=9.0",
#     "jupyter-scatter>=0.22",
# ]
# ///
"""NHTSA vehicle complaint classifier — multi-target fine-tuning demo.

Fine-tunes a small LLM to classify NHTSA safety complaints into three
targets simultaneously (fire, crash, component) using structured JSON
output. The ground-truth labels come from NHTSA's own structured fields
— no manual labeling required.

This is programmatic labeling: use an existing structured dataset's
metadata as free supervision to train a model that works from raw text
alone. Once trained, the model can classify new narratives that lack
structured fields.

Downloads the NHTSA complaints flat file automatically on first run
(~250 MB compressed). Requires a CUDA GPU with >= 8 GB VRAM.

    marimo edit --sandbox demo_nhtsa.py

Or install manually:

    pip install unsloth torch trl mlflow scikit-learn numpy matplotlib requests marimo
    marimo edit demo_nhtsa.py
"""

import marimo

__generated_with = "0.23.1"
app = marimo.App(width="medium", auto_download=["html"])


@app.cell
def imports():
    import json
    import re

    from unsloth import FastModel
    from unsloth.chat_templates import get_chat_template, train_on_responses_only
    import marimo as mo
    import matplotlib.pyplot as plt
    import mlflow
    import numpy as np
    import torch
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
        confusion_matrix,
        get_chat_template,
        json,
        mlflow,
        mo,
        plt,
        re,
        torch,
        train_on_responses_only,
    )


@app.cell
def title(mo):
    mo.md(r"""
    # NHTSA Complaint Classifier — Multi-Target Fine-Tuning

    Fine-tune a small LLM to classify vehicle safety complaints into
    three targets simultaneously using structured JSON output:

    - **fire** (boolean) — did the complaint involve an actual fire?
    - **crash** (boolean) — did the complaint involve a crash/collision?
    - **component** (string) — which vehicle system is affected?

    The key insight: NHTSA's own structured data provides free
    ground-truth labels. No manual labeling needed — just pair the
    narrative text with the existing FIRE, CRASH, and COMPDESC fields.

    This is **programmatic labeling**: mine labels from structured data,
    train a model that works from raw text alone, then apply it to new
    narratives that lack structured metadata.
    """)
    return


@app.cell
def taxonomy():
    """Map raw NHTSA COMPDESC strings to a clean taxonomy.

    Prefixes are matched greedily (longest prefix first), so
    "SERVICE BRAKES" matches before a hypothetical "SERVICE" entry.
    """
    COMPONENT_MAP = {
        "AIR BAGS": "airbags",
        "BRAKES": "brakes",
        "SERVICE BRAKES": "brakes",
        "PARKING BRAKE": "brakes",
        "ELECTRICAL SYSTEM": "electrical_system",
        "ENGINE AND ENGINE COOLING": "engine",
        "ENGINE": "engine",
        "EQUIPMENT": "equipment",
        "EXTERIOR LIGHTING": "lighting",
        "INTERIOR LIGHTING": "lighting",
        "FUEL/PROPULSION SYSTEM": "fuel_system",
        "FUEL SYSTEM": "fuel_system",
        "HYBRID PROPULSION SYSTEM": "fuel_system",
        "LATCHES/LOCKS/LINKAGES": "body",
        "POWER TRAIN": "powertrain",
        "SEAT BELTS": "restraints",
        "CHILD SEAT": "restraints",
        "SEATS": "body",
        "STEERING": "steering",
        "STRUCTURE": "body",
        "SUSPENSION": "suspension",
        "TIRES": "tires",
        "VEHICLE SPEED CONTROL": "powertrain",
        "VISIBILITY": "visibility",
        "WHEELS": "tires",
        "EXHAUST SYSTEM": "exhaust",
        "FORWARD COLLISION AVOIDANCE": "adas",
        "LANE DEPARTURE": "adas",
        "BACK OVER PREVENTION": "adas",
        "ELECTRONIC STABILITY CONTROL": "adas",
    }
    COMPONENT_CLASSES = sorted(set(COMPONENT_MAP.values())) + ["other"]

    def map_component(raw: str) -> str:
        raw_upper = raw.strip().upper()
        best_key, best_len = None, 0
        for key in COMPONENT_MAP:
            if raw_upper.startswith(key) and len(key) > best_len:
                best_key, best_len = key, len(key)
        return COMPONENT_MAP[best_key] if best_key else "other"

    return COMPONENT_CLASSES, map_component


@app.cell
def config(COMPONENT_CLASSES, mo):
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

    SYSTEM_PROMPT = (
        "You are a vehicle safety analyst. Read the complaint narrative and "
        "emit a JSON object with these fields: "
        "fire (boolean — was there an actual fire?), "
        "crash (boolean — was there an actual crash/collision?), "
        "component (string — the primary vehicle system affected, one of: "
        f"{', '.join(COMPONENT_CLASSES)}), "
        "make (string — the vehicle manufacturer, e.g. FORD, TOYOTA, HONDA), "
        "year (string — the model year, e.g. 2019). "
        "Respond with JSON only, no prose."
    )

    model_dropdown = mo.ui.dropdown(
        options=list(MODELS.keys()),
        value="unsloth/SmolLM2-135M-Instruct",
        label="Model",
    )
    max_steps_input = mo.ui.number(
        value=200,
        start=10,
        stop=3000,
        step=10,
        label="Max training steps",
    )
    N_TRAIN = 2000
    N_EVAL = 400
    mo.md(f"""
    ## Configuration

    {model_dropdown}

    {max_steps_input}

    Training examples: **{N_TRAIN}** | Eval examples: **{N_EVAL}**

    Multi-target output format:
    ```json
    {{"fire": false, "crash": true, "component": "brakes"}}
    ```
    """)
    return (
        MODELS,
        N_EVAL,
        N_TRAIN,
        SYSTEM_PROMPT,
        max_steps_input,
        model_dropdown,
    )


@app.cell
def load_data(N_EVAL, N_TRAIN, map_component, mo):
    import io
    import zipfile
    from pathlib import Path

    import ibis
    import requests

    NHTSA_URL = "https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip"
    CACHE_DIR = Path("nhtsa_cache")
    FLAT_FILE = CACHE_DIR / "FLAT_CMPL.txt"

    if not FLAT_FILE.exists():
        mo.status.spinner(
            title="Downloading NHTSA complaints flat file (~250 MB)...",
        )
        CACHE_DIR.mkdir(exist_ok=True)
        resp = requests.get(NHTSA_URL, stream=True, timeout=120)
        resp.raise_for_status()
        content = io.BytesIO(resp.content)
        with zipfile.ZipFile(content) as zf:
            for name in zf.namelist():
                if name.upper().endswith(".TXT"):
                    with zf.open(name) as src, open(FLAT_FILE, "wb") as dst:
                        dst.write(src.read())
                    break

    # Read with duckdb via ibis — columnar scan, no full-file slurp.
    # Column names from CMPL_SCHEMA.txt (see nhtsa_cache/CMPL_SCHEMA.txt).
    # DuckDB zero-pads auto-generated names: column00, column01, ...
    con = ibis.duckdb.connect()
    t = con.sql(f"""
        SELECT
            column00 AS cmplid,
            column03 AS make,
            column04 AS model_name,
            column05 AS year,
            column06 AS crash,
            column08 AS fire,
            column09 AS injured,
            column11 AS compdesc,
            column19 AS narrative
        FROM read_csv(
            '{FLAT_FILE}',
            delim = '\t',
            header = false,
            auto_detect = true,
            ignore_errors = true
        )
        WHERE length(column19) >= 50
          AND length(column11) > 0
    """)

    # Deterministic sample: order by complaint ID, pull only the rows
    # we need into pandas (~0.5 MB for 2400 rows vs 1.5 GB full file)
    n_total = N_TRAIN + N_EVAL
    df = (
        t.mutate(row_hash=ibis._.cmplid.cast("int64").abs() % 2_147_483_647)
        .order_by("row_hash")
        .limit(n_total)
        .drop("row_hash")
        .execute()
    )

    # Component mapping + bool coercion at the pandas boundary
    records = [
        {
            "id": row.cmplid,
            "narrative": row.narrative.strip(),
            "make": str(row.make).strip(),
            "year": str(row.year).strip(),
            "vehicle": f"{row.year} {row.make} {row.model_name}".strip(),
            "fire": str(row.fire).strip().upper() == "Y",
            "crash": str(row.crash).strip().upper() == "Y",
            "injured": int(row.injured or 0) > 0,
            "component": map_component(row.compdesc),
        }
        for row in df.itertuples()
    ]

    train_records = records[:N_TRAIN]
    eval_records = records[N_TRAIN:]
    return eval_records, train_records


@app.cell
def show_data(COMPONENT_CLASSES, eval_records, mo, train_records):
    import collections

    fire_dist = collections.Counter(r["fire"] for r in train_records)
    crash_dist = collections.Counter(r["crash"] for r in train_records)
    comp_dist = collections.Counter(r["component"] for r in train_records)

    comp_rows = "\n".join(
        f"| {cls} | {comp_dist.get(cls, 0)} |"
        for cls in COMPONENT_CLASSES
        if comp_dist.get(cls, 0) > 0
    )

    mo.md(f"""
    ## Dataset: NHTSA Vehicle Safety Complaints

    Three prediction targets mined from NHTSA's structured fields:

    | Target | True | False |
    |---|---|---|
    | fire | {fire_dist[True]} | {fire_dist[False]} |
    | crash | {crash_dist[True]} | {crash_dist[False]} |

    **Component taxonomy** ({len(COMPONENT_CLASSES)} classes):

    | Component | Train count |
    |---|---|
    {comp_rows}

    | Split | Count |
    |---|---|
    | Train | {len(train_records)} |
    | Eval | {len(eval_records)} |

    **Labels are free** — derived from NHTSA's own FIRE, CRASH, and
    COMPDESC columns. No manual annotation needed.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Exploratory Data Analysis: t-SNE projection

    TF-IDF vectorization of complaint narratives projected to 2D with t-SNE.
    Points colored by component class — clusters indicate the model has
    learnable signal in the raw text. This is a quick sanity check, not a
    rigorous embedding analysis.
    """)
    return


@app.cell(hide_code=True)
def _(train_records):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.manifold import TSNE
    import pandas as pd

    # TF-IDF: narratives -> sparse term vectors (capped at 3000 features)
    _tfidf = TfidfVectorizer(max_features=3000, stop_words="english")
    _X = _tfidf.fit_transform([r["narrative"] for r in train_records])

    # t-SNE: high-dim sparse vectors -> 2D coordinates
    _tsne = TSNE(n_components=2, random_state=42, perplexity=30, max_iter=500)
    _coords = _tsne.fit_transform(_X.toarray())

    # Assemble a pandas DataFrame for jscatter
    eda_df = pd.DataFrame(
        {
            "x": _coords[:, 0],
            "y": _coords[:, 1],
            "component": [r["component"] for r in train_records],
            "fire": [str(r["fire"]) for r in train_records],
            "crash": [str(r["crash"]) for r in train_records],
            "injured": [str(r["injured"]) for r in train_records],
            "make": [
                r["vehicle"].split()[1]
                if len(r["vehicle"].split()) > 1
                else r["vehicle"]
                for r in train_records
            ],
            "year": [r["vehicle"].split()[0] for r in train_records],
            "vehicle": [r["vehicle"] for r in train_records],
            "narrative": [r["narrative"][:120] for r in train_records],
        }
    )
    return (eda_df,)


@app.cell(hide_code=True)
def _(mo):
    color_by = mo.ui.dropdown(
        options=["component", "fire", "crash", "injured", "make", "year"],
        value="component",
        label="Color by",
    )
    color_by
    return (color_by,)


@app.cell(hide_code=True)
def _(color_by, eda_df, mo):
    import jscatter

    _scatter = jscatter.Scatter(x="x", y="y", data=eda_df)
    _scatter.height(500)
    _scatter.color(by=color_by.value)
    _scatter.legend(True)
    _scatter.tooltip(True)
    _scatter.size(3)
    _scatter.lasso(initiator=True, on_long_press=True)

    scatter_widget = mo.ui.anywidget(_scatter.widget)
    scatter_widget
    return (scatter_widget,)


@app.cell(hide_code=True)
def _(eda_df, mo, scatter_widget):
    _sel = scatter_widget.selection
    if _sel is not None and len(_sel) > 0:
        _selected_df = eda_df.iloc[_sel][
            [
                "component",
                "fire",
                "crash",
                "injured",
                "make",
                "year",
                "vehicle",
                "narrative",
            ]
        ]
        _out = mo.vstack(
            [
                mo.md(f"**{len(_selected_df)} points selected**"),
                mo.ui.table(_selected_df, page_size=10),
            ]
        )
    else:
        _out = mo.md(
            "*Lasso or box-select points on the scatter plot above to inspect records.*"
        )
    _out
    return


@app.cell
def make_classifier(json, re, torch):
    """Shared inference helper for zero-shot and fine-tuned evaluation."""

    def _strip_thinking(text):
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if not cleaned and "</think>" in text:
            cleaned = text.split("</think>")[-1].strip()
        return cleaned if cleaned else text

    def _parse_prediction(response, component_classes):
        """Parse a JSON prediction from the model response."""
        cleaned = _strip_thinking(response)
        json_match = re.search(r"\{[^}]+\}", cleaned)
        if not json_match:
            return {"fire": None, "crash": None, "component": None,
                    "make": None, "year": None}
        try:
            obj = json.loads(json_match.group())
        except json.JSONDecodeError:
            return {"fire": None, "crash": None, "component": None,
                    "make": None, "year": None}

        fire = obj.get("fire")
        crash = obj.get("crash")
        component = obj.get("component", "").lower().strip()
        make = obj.get("make", "").upper().strip() or None
        year = obj.get("year", "").strip() or None

        if isinstance(fire, str):
            fire = fire.lower() in ("true", "yes", "y", "1")
        if isinstance(crash, str):
            crash = crash.lower() in ("true", "yes", "y", "1")

        fire = bool(fire) if fire is not None else None
        crash = bool(crash) if crash is not None else None

        if component not in component_classes:
            component = None

        return {"fire": fire, "crash": crash, "component": component,
                "make": make, "year": year}

    def classify_batch(model, tokenizer, records, system_prompt, component_classes):
        """Run inference on a batch of records, returning parsed predictions."""
        model.eval()
        results = []
        for rec in records:
            messages = [
                {"role": "user", "content": (
                    f"{system_prompt}\n\n"
                    f"Vehicle: {rec['vehicle']}\n"
                    f"Complaint: {rec['narrative']}"
                )},
            ]
            try:
                prompt_text = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True,
                    enable_thinking=False,
                )
            except (TypeError, ValueError):
                prompt_text = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True,
                )
            inputs = tokenizer(text=prompt_text, return_tensors="pt").to(
                model.device
            )
            input_len = inputs["input_ids"].shape[1]
            with torch.no_grad():
                output = model.generate(
                    **inputs, max_new_tokens=96, do_sample=False,
                )
            response = tokenizer.decode(
                output[0][input_len:], skip_special_tokens=True,
            ).strip()
            parsed = _parse_prediction(response, component_classes)
            parsed["raw_response"] = response
            results.append(parsed)
        return results

    return (classify_batch,)


@app.cell
def load_model_cell(
    FastModel,
    MODELS,
    get_chat_template,
    model_dropdown,
    torch,
):
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
    if torch.cuda.is_available() and torch.cuda.get_device_capability()[0] < 8:
        model.config._attn_implementation = "eager"
        torch._dynamo.config.suppress_errors = True
        torch._dynamo.config.disable = True
    return model, tokenizer


@app.cell
def format_train_data(SYSTEM_PROMPT, json, tokenizer, train_records):
    """Format training data as chat conversations for SFTTrainer.

    Each example has the system prompt + narrative as input, and a JSON
    object with fire/crash/component as the target output.
    """
    bos = tokenizer.bos_token or ""

    def _format(rec):
        labels = {
            "fire": rec["fire"],
            "crash": rec["crash"],
            "component": rec["component"],
            "make": rec["make"],
            "year": rec["year"],
        }
        messages = [
            {"role": "user", "content": (
                f"{SYSTEM_PROMPT}\n\n"
                f"Vehicle: {rec['vehicle']}\n"
                f"Complaint: {rec['narrative']}"
            )},
            {"role": "assistant", "content": json.dumps(
                labels, separators=(",", ":"),
            )},
        ]
        text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False,
        )
        if bos and text.startswith(bos):
            text = text[len(bos):]
        return {"formatted_text": text}

    # Convert to HuggingFace Dataset for SFTTrainer
    from datasets import Dataset
    formatted_dataset = Dataset.from_list(
        [_format(r) for r in train_records]
    )
    return (formatted_dataset,)


@app.cell
def zs_section(mo):
    mo.md(r"""
    ## Zero-shot evaluation (before training)

    The base model with freshly-initialized LoRA adapters. Can the
    pre-trained model extract fire/crash/component from complaint
    narratives without any fine-tuning?
    """)
    return


@app.cell
def zero_shot_eval(
    COMPONENT_CLASSES,
    SYSTEM_PROMPT,
    classify_batch,
    eval_records,
    model,
    tokenizer,
):
    zs_results = classify_batch(
        model, tokenizer, eval_records, SYSTEM_PROMPT, COMPONENT_CLASSES,
    )
    return (zs_results,)


@app.cell
def train_section_md(mo):
    mo.md(r"""
    ## Fine-tune with QLoRA

    Training the model to emit structured JSON with fire/crash/component
    predictions. `train_on_responses_only` ensures the model only learns
    to predict the JSON output, not to parrot the prompt.
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

    mlflow.set_experiment("nhtsa-finetuning")
    with mlflow.start_run(run_name=_model_name.split("/")[-1]) as active_run:
        mlflow.log_params({
            "model_name": _model_name,
            "lora_r": 8,
            "lora_alpha": 8,
            "max_seq_length": 2048,
            "load_in_4bit": _cfg.get("load_in_4bit", True),
            "max_steps": _max_steps,
            "learning_rate": 2e-4,
            "task": "multi-target (fire, crash, component)",
        })

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
                output_dir="/tmp/nhtsa-ft",
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

    Same eval set, same prompt format. Compare against the zero-shot
    predictions captured before training.
    """)
    return


@app.cell
def finetuned_eval(
    COMPONENT_CLASSES,
    SYSTEM_PROMPT,
    classify_batch,
    eval_records,
    model,
    tokenizer,
):
    ft_results = classify_batch(
        model, tokenizer, eval_records, SYSTEM_PROMPT, COMPONENT_CLASSES,
    )
    return (ft_results,)


@app.cell
def comparison(eval_records, ft_results, mlflow, mo, run_id, zs_results):
    """Compute per-target _metrics, log to MLflow, display comparison."""


    def _binary_metrics(gt_vals, pred_vals):
        valid = [(g, p) for g, p in zip(gt_vals, pred_vals) if p is not None]
        if not valid:
            return 0.0, 0.0, 0.0, 0.0
        gt_v, pr_v = zip(*valid)
        from sklearn.metrics import (
            accuracy_score,
            f1_score,
            precision_score,
            recall_score,
        )

        return (
            accuracy_score(gt_v, pr_v),
            precision_score(gt_v, pr_v, zero_division=0),
            recall_score(gt_v, pr_v, zero_division=0),
            f1_score(gt_v, pr_v, zero_division=0),
        )


    def _component_metrics(gt_vals, pred_vals):
        valid = [(g, p) for g, p in zip(gt_vals, pred_vals) if p is not None]
        if not valid:
            return 0.0, 0.0
        gt_v, pr_v = zip(*valid)
        from sklearn.metrics import accuracy_score, f1_score

        return (
            accuracy_score(gt_v, pr_v),
            f1_score(gt_v, pr_v, average="macro", zero_division=0),
        )


    def _parse_rate(pred_vals):
        return sum(1 for p in pred_vals if p is not None) / len(pred_vals)


    _gt_fire = [r["fire"] for r in eval_records]
    _gt_crash = [r["crash"] for r in eval_records]
    _gt_comp = [r["component"] for r in eval_records]
    _gt_make = [r["make"] for r in eval_records]
    _gt_year = [r["year"] for r in eval_records]

    _metrics = {}
    for label, results in [("zs", zs_results), ("ft", ft_results)]:
        pr_fire = [r["fire"] for r in results]
        pr_crash = [r["crash"] for r in results]
        pr_comp = [r["component"] for r in results]
        pr_make = [r["make"] for r in results]
        pr_year = [r["year"] for r in results]

        fire_acc, fire_prec, fire_rec, fire_f1 = _binary_metrics(_gt_fire, pr_fire)
        crash_acc, crash_prec, crash_rec, crash_f1 = _binary_metrics(
            _gt_crash, pr_crash
        )
        comp_acc, comp_f1 = _component_metrics(_gt_comp, pr_comp)
        make_acc, _ = _component_metrics(_gt_make, pr_make)
        year_acc, _ = _component_metrics(_gt_year, pr_year)
        parse_rate = _parse_rate(pr_fire)

        _metrics[label] = {
            "fire_f1": fire_f1,
            "fire_acc": fire_acc,
            "crash_f1": crash_f1,
            "crash_acc": crash_acc,
            "component_acc": comp_acc,
            "component_f1_macro": comp_f1,
            "make_acc": make_acc,
            "year_acc": year_acc,
            "parse_rate": parse_rate,
        }

    with mlflow.start_run(run_id=run_id):
        for prefix, m in _metrics.items():
            mlflow.log_metrics({f"{prefix}_{k}": v for k, v in m.items()})


    def _fmt(zs_val, ft_val):
        delta = ft_val - zs_val
        return f"`{zs_val:.4f}` -> `{ft_val:.4f}` ({delta:+.4f})"


    zs, ft = _metrics["zs"], _metrics["ft"]
    mo.md(f"""
    ## Zero-shot vs Fine-tuned

    | Target | Metric | Zero-shot -> Fine-tuned |
    |---|---|---|
    | fire | F1 | {_fmt(zs["fire_f1"], ft["fire_f1"])} |
    | fire | accuracy | {_fmt(zs["fire_acc"], ft["fire_acc"])} |
    | crash | F1 | {_fmt(zs["crash_f1"], ft["crash_f1"])} |
    | crash | accuracy | {_fmt(zs["crash_acc"], ft["crash_acc"])} |
    | component | accuracy | {_fmt(zs["component_acc"], ft["component_acc"])} |
    | component | F1 macro | {_fmt(zs["component_f1_macro"], ft["component_f1_macro"])} |
    | make | accuracy | {_fmt(zs["make_acc"], ft["make_acc"])} |
    | year | accuracy | {_fmt(zs["year_acc"], ft["year_acc"])} |
    | parse | rate | {_fmt(zs["parse_rate"], ft["parse_rate"])} |

    **Parse rate** = fraction of responses that produced valid JSON.
    **make/year** = can the model infer the vehicle from the narrative
    text alone? TF-IDF can't do this; attention-based models can.
    """)
    return


@app.cell
def confusion_section(mo):
    mo.md(r"""
    ## Component confusion matrix (fine-tuned)

    Which vehicle systems get confused for which? Rows = true component,
    columns = predicted. Row-normalized to show per-class recall.
    """)
    return


@app.cell
def confusion_plot(
    confusion_matrix,
    eval_records,
    ft_results,
    mo,
    plt,
    zs_results,
):
    # Filter to classes that appear in the eval set
    _gt_comp = [r["component"] for r in eval_records]
    _active_classes = sorted(set(_gt_comp))
    _class_to_idx = {c: i for i, c in enumerate(_active_classes)}
    _n_cls = len(_active_classes)


    def _cm(results):
        gt_idx, pr_idx = [], []
        for rec, res in zip(eval_records, results):
            if res["component"] is None:
                continue
            if (
                rec["component"] in _class_to_idx
                and res["component"] in _class_to_idx
            ):
                gt_idx.append(_class_to_idx[rec["component"]])
                pr_idx.append(_class_to_idx[res["component"]])
        if not gt_idx:
            return None
        return confusion_matrix(gt_idx, pr_idx, labels=list(range(_n_cls)))


    _ft_cm = _cm(ft_results)
    _zs_cm = _cm(zs_results)

    if _ft_cm is None:
        _cm_out = mo.md("_Not enough valid component predictions._")
    else:
        fig_cm, axes = plt.subplots(1, 2, figsize=(14, 6))
        for ax, cm_mat, title in [
            (axes[0], _zs_cm, "zero-shot"),
            (axes[1], _ft_cm, "fine-tuned"),
        ]:
            if cm_mat is None:
                ax.set_visible(False)
                continue
            _norm = cm_mat.astype(float) / cm_mat.sum(axis=1, keepdims=True).clip(
                min=1
            )
            im = ax.imshow(_norm, cmap="Blues", vmin=0, vmax=1)
            ax.set_xticks(range(_n_cls))
            ax.set_yticks(range(_n_cls))
            ax.set_xticklabels(
                _active_classes, rotation=60, ha="right", fontsize=7
            )
            ax.set_yticklabels(_active_classes, fontsize=7)
            ax.set_xlabel("predicted")
            ax.set_ylabel("true")
            ax.set_title(f"{title} -- recall (row-normalized)")
            for ii in range(_n_cls):
                for jj in range(_n_cls):
                    ax.text(
                        jj,
                        ii,
                        f"{_norm[ii, jj]:.2f}",
                        ha="center",
                        va="center",
                        fontsize=6,
                        color="white" if _norm[ii, jj] > 0.5 else "black",
                    )
            fig_cm.colorbar(im, ax=ax, fraction=0.046)
        fig_cm.suptitle(
            "Component confusion: zero-shot vs fine-tuned", fontsize=12
        )
        fig_cm.tight_layout()
        _cm_out = mo.as_html(fig_cm)
    _cm_out
    return


@app.cell
def sample_predictions(eval_records, ft_results, json, mo, zs_results):
    def _():
        """Show a handful of predictions to inspect model behavior."""
        examples = []
        for i in range(min(10, len(eval_records))):
            rec = eval_records[i]
            zs = zs_results[i]
            ft = ft_results[i]
            gt = {"fire": rec["fire"], "crash": rec["crash"], "component": rec["component"]}
            snippet = rec["narrative"][:120].replace("\n", " ")
            examples.append(
                f"**[{rec['vehicle']}]** {snippet}...\n\n"
                f"- Ground truth: `{json.dumps(gt)}`\n"
                f"- Zero-shot: `{zs['raw_response'][:100]}`\n"
                f"- Fine-tuned: `{ft['raw_response'][:100]}`\n"
            )

        _accordion = mo.accordion({
            f"Example {i+1}": mo.md(ex) for i, ex in enumerate(examples)
        })
        return mo.vstack([
            mo.md("## Sample predictions"),
            _accordion,
        ])


    _()
    return


@app.cell
def mlflow_section(mo):
    mo.md(r"""
    ## Compare runs in MLflow

    Every training run is logged to the `nhtsa-finetuning` experiment.
    Compare models and hyperparameters:

    ```bash
    mlflow ui --port 5000
    ```

    Key metrics to compare:
    - **fire/crash F1** — binary detection of safety-critical events
    - **component accuracy** — multi-class system identification
    - **parse rate** — does the model emit valid JSON?
    """)
    return


@app.cell
def export_section(mo):
    mo.md(r"""
    ## Export to GGUF for llama.cpp

    ```python
    model.save_pretrained_gguf(
        "nhtsa-classifier",
        tokenizer,
        quantization_method="q4_k_m",
    )
    ```

    Then serve:

    ```bash
    llama-server -m nhtsa-classifier/unsloth.Q4_K_M.gguf \
        --port 8080 --ctx-size 2048
    ```

    The model accepts complaint narratives and returns structured JSON
    with fire/crash/component predictions — ready for integration into
    a safety monitoring pipeline.
    """)
    return


@app.cell
def takeaway(mo):
    mo.md(r"""
    ## Takeaway

    **Programmatic labeling** for LLM fine-tuning:

    1. **Find structured data** — NHTSA's FIRE, CRASH, COMPDESC fields
       provide free ground-truth labels for 2.2M complaint narratives
    2. **Train on text -> structured output** — the model learns to
       extract what the database already knows, but from raw text alone
    3. **Deploy on new narratives** — incoming complaints get instant
       fire/crash/component classification without manual review
    4. **Multi-target JSON** — one inference call, three predictions,
       structured output that's easy to parse downstream

    This same pattern works anywhere you have a database with structured
    fields alongside unstructured text: medical records, support tickets,
    insurance claims, regulatory filings.
    """)
    return


if __name__ == "__main__":
    app.run()
