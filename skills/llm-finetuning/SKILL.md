---
name: llm-finetuning
description: Fine-tune small open-weight LLMs locally with Unsloth + QLoRA for text tasks (classification, extraction, translation). Use when input is raw text (not tabular features), user has labeled examples, and wants model ownership without API costs. Default to Gemma-4 E2B; scale up based on VRAM. Always compare zero-shot vs fine-tuned, log every run to MLflow, export to GGUF for llama.cpp.
---

<!-- Bundled files (accessible via ${CLAUDE_SKILL_DIR}):
  - SKILL.md — this file
  - scripts/demo.py — runnable marimo notebook with worked example
  - scripts/demo_nhtsa.py — NHTSA complaints fine-tuning notebook
  - assets/demo.html — pre-rendered HTML preview (open in any browser)
  - assets/demo_nhtsa.html — pre-rendered NHTSA notebook preview
  - references/MODEL_NAMING.md — model naming conventions
  - references/MODEL_ARCHITECTURES.md — model architecture reference
  - nhtsa_cache/CMPL_SCHEMA.txt — NHTSA complaints schema reference
-->

# LLM Fine-Tuning with Unsloth (Done Right)

Fine-tune small open-weight LLMs **locally** for text tasks. Unsloth +
QLoRA makes this practical on consumer GPUs (8 GB VRAM). The workflow:
pick a model, format data as instruction-tuning pairs, fine-tune with
TRL's `SFTTrainer`, evaluate against zero-shot baseline, log to MLflow,
export to GGUF for llama.cpp deployment.

## When to use this skill

- Input is **text** (articles, tickets, emails, reviews) — not tabular
  features
- You have at least a few hundred labeled examples
- You want **model ownership** — no API dependency, no per-token cost,
  data stays on-device
- You want a single model that can handle related text tasks later
  (classification today, extraction tomorrow)

## When NOT to use this skill

- Input is **tabular** (numbers, categories) → use XGBoost (see
  binary/multiclass/multilabel classification skills)
- You have < 50 labeled examples → use zero-shot or few-shot prompting
  with a larger model via API
- You need state-of-the-art quality and cost doesn't matter → use
  Claude/GPT API with prompt engineering
- You're doing unsupervised text analysis → use embeddings + clustering,
  not fine-tuning

## Model selection

Pick the largest model that fits in your VRAM with QLoRA (4-bit).
Bigger models learn faster and generalize better, but the returns
diminish. For most text classification tasks, 1-4B is plenty.

| Model | Params | VRAM (QLoRA) | Unsloth ID | Notes |
|---|---|---|---|---|
| Qwen3-0.6B | 0.6B | ~4 GB | `unsloth/Qwen3-0.6B` | Smallest, fastest iteration |
| Llama-3.2 1B | 1B | ~6 GB | `unsloth/Llama-3.2-1B-Instruct` | Good quality/size ratio |
| **Gemma-4 E2B** | 2B | 8-10 GB | `unsloth/gemma-4-E2B-it` | **Default.** Strong for its size |
| Llama-3.2 3B | 3B | ~10 GB | `unsloth/Llama-3.2-3B-Instruct` | Benchmark vs Gemma-4 E2B |
| Phi-4 mini | 3.8B | ~12 GB | `unsloth/Phi-4-mini-instruct` | Needs 16+ GB VRAM |
| Gemma-4 E4B | 4B | ~17 GB | `unsloth/gemma-4-E4B-it` | Needs 24+ GB VRAM |

### Chat templates and mask tokens

Each model family has its own chat format. When adding a new model,
you need three things:

1. **Unsloth chat template name** — passed to `get_chat_template()`
2. **Instruction mask** — the token sequence that starts a user turn
3. **Response mask** — the token sequence that starts a model turn

These are used by `train_on_responses_only()` to ensure the model only
learns to predict responses, not to parrot the prompt.

| Model family | Template | Instruction part | Response part |
|---|---|---|---|
| Gemma 4 | `gemma-4-thinking` | `<\|turn>user\n` | `<\|turn>model\n` |
| Llama 3.x | `llama-3.1` | `<\|start_header_id\|>user<\|end_header_id\|>\n\n` | `<\|start_header_id\|>assistant<\|end_header_id\|>\n\n` |
| Qwen 2.5/3 | `qwen-2.5` | `<\|im_start\|>user\n` | `<\|im_start\|>assistant\n` |

## Data formatting

Frame every text task as **instruction-tuning**: the user message is the
input text with a task prompt, the assistant message is the label or
output.

### Text classification example

```python
messages = [
    {"role": "user", "content": (
        "Classify this news article into exactly one category: "
        "World, Sports, Business, Sci/Tech.\n\n"
        f"{article_text}"
    )},
    {"role": "assistant", "content": "Sports"},
]
```

### Formatting for SFTTrainer

```python
from unsloth.chat_templates import get_chat_template

tokenizer = get_chat_template(tokenizer, chat_template="gemma-4-thinking")

def format_example(row):
    messages = [
        {"role": "user", "content": f"<your prompt>\n\n{row['text']}"},
        {"role": "assistant", "content": row["label_name"]},
    ]
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False,
    )
    # Remove BOS — SFTTrainer adds its own
    bos = tokenizer.bos_token or ""
    if bos and text.startswith(bos):
        text = text[len(bos):]
    return {"formatted_text": text}

formatted = dataset.map(format_example)
```

## Training pipeline

### 1. Load model with QLoRA

```python
from unsloth import FastModel

model, tokenizer = FastModel.from_pretrained(
    model_name="unsloth/gemma-4-E2B-it",
    dtype=None,              # auto-detect
    max_seq_length=2048,     # keep short for classification
    load_in_4bit=True,       # QLoRA
    full_finetuning=False,
)
```

### 2. Add LoRA adapters

```python
model = FastModel.get_peft_model(
    model,
    finetune_vision_layers=False,
    finetune_language_layers=True,
    finetune_attention_modules=True,
    finetune_mlp_modules=True,
    r=8,                    # LoRA rank — 8 is a good default
    lora_alpha=8,           # usually equal to r
    lora_dropout=0,
    bias="none",
    random_state=3407,
)
```

### 3. Train with SFTTrainer

```python
from trl import SFTTrainer, SFTConfig
from unsloth.chat_templates import train_on_responses_only

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=formatted,
    args=SFTConfig(
        output_dir="/tmp/llm-ft",
        dataset_text_field="formatted_text",
        per_device_train_batch_size=1,     # 1 for 8 GB VRAM
        gradient_accumulation_steps=4,      # effective batch = 4
        warmup_steps=5,
        max_steps=60,                       # tune based on dataset size
        learning_rate=2e-4,
        optim="adamw_8bit",
        weight_decay=0.001,
        lr_scheduler_type="linear",
        seed=3407,
        save_strategy="no",
        report_to="none",                   # we log to MLflow manually
    ),
)

# Only compute loss on assistant responses
trainer = train_on_responses_only(
    trainer,
    instruction_part="<|turn>user\n",      # model-specific
    response_part="<|turn>model\n",         # model-specific
)

stats = trainer.train()
```

### Key training params to tune

| Param | Default | When to change |
|---|---|---|
| `max_steps` | 60 | More data → more steps. 1-3 epochs over the dataset. |
| `learning_rate` | 2e-4 | Lower (1e-4) if loss is unstable. |
| `r` (LoRA rank) | 8 | Increase to 16-32 for harder tasks. More capacity but slower. |
| `max_seq_length` | 2048 | Increase for long documents. Costs more VRAM. |
| `gradient_accumulation_steps` | 4 | Increase for more stable gradients at the cost of speed. |

## Evaluation

### Always compare zero-shot vs fine-tuned

The most important evaluation is: did fine-tuning actually help? Run the
base model (before training) on the eval set, then run the fine-tuned
model. Compare accuracy and F1 macro.

```python
def classify(model, tokenizer, text, label_names):
    messages = [{"role": "user", "content": f"Classify: {', '.join(label_names)}.\n\n{text}"}]
    inputs = tokenizer.apply_chat_template(
        messages, return_tensors="pt", add_generation_prompt=True,
    ).to(model.device)
    with torch.no_grad():
        output = model.generate(input_ids=inputs, max_new_tokens=20, do_sample=False)
    response = tokenizer.decode(output[0][inputs.shape[1]:], skip_special_tokens=True).strip()
    for idx, name in enumerate(label_names):
        if name.lower() in response.lower():
            return idx
    return -1  # parse failure
```

### Metrics

Same metrics as multiclass classification:

- **F1 macro** — primary metric, surfaces rare-class failures
- **Per-class F1** — each class has its own difficulty
- **Confusion matrix** — which classes get confused
- **Parse rate** — fraction of responses that contain a valid label.
  Low parse rate means the model isn't following the format.

### Parse failures

If the model outputs `"This article is about sports and entertainment"`
instead of just `"Sports"`, parsing fails. Fine-tuning should fix this —
the model learns the exact output format from training data. If parse
rate stays low after fine-tuning, increase `max_steps` or check the
training data format.

## MLflow conventions

Log every training run to MLflow for comparison across models and
hyperparameters.

```python
import mlflow

mlflow.set_experiment("llm-finetuning")
with mlflow.start_run(run_name="gemma-4-E2B-it"):
    mlflow.log_params({
        "model_name": "unsloth/gemma-4-E2B-it",
        "lora_r": 8,
        "max_steps": 60,
        "learning_rate": 2e-4,
        "max_seq_length": 2048,
    })
    # ... train ...
    mlflow.log_metric("train_loss", stats.training_loss)
    mlflow.log_metrics({
        "zs_accuracy": zs_acc,
        "zs_f1_macro": zs_f1,
        "ft_accuracy": ft_acc,
        "ft_f1_macro": ft_f1,
    })
```

Compare runs: `mlflow ui --port 5000`

### What to compare across runs

- **Model size vs F1**: does the 2B model beat the 0.6B?
- **Steps vs F1**: diminishing returns? overfitting?
- **LoRA rank vs F1**: does r=16 beat r=8?
- **Zero-shot delta**: how much did fine-tuning actually buy?

## GGUF export

After fine-tuning, merge LoRA adapters and quantize to GGUF:

```python
model.save_pretrained_gguf(
    "finetuned-model",
    tokenizer,
    quantization_method="q4_k_m",
)
```

Quantization options:
- `q4_k_m` — 4-bit, recommended default (~3 GB for E2B)
- `q8_0` — 8-bit, higher quality (~5 GB for E2B)
- `f16` — full precision, no loss (~9 GB for E2B)

## Inference with llama.cpp

```bash
llama-server -m finetuned-model/unsloth.Q4_K_M.gguf \
    --port 8080 --ctx-size 2048
```

Then query via the OpenAI-compatible API:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role":"user","content":"Classify: World, Sports, Business, Sci/Tech.\n\nNASA launches new Mars rover..."}],
    "max_tokens": 20,
    "temperature": 0
  }'
```

## Pitfalls

1. **Wrong chat template** — if you use template X for training and
   template Y for inference, the model will produce garbage. Always
   use the same template for both.
2. **Forgetting `train_on_responses_only`** — without it, the model
   also learns to generate the user prompt, wasting capacity and
   often degrading classification quality.
3. **Too many steps → overfitting** — with small datasets (< 1000
   examples), 1-2 epochs is enough. Watch training loss: if it
   flatlines near zero, you're overfitting.
4. **BOS token duplication** — `SFTTrainer` adds BOS automatically.
   If your formatted text already starts with BOS, strip it.
5. **Ignoring parse failures** — if 30% of responses don't parse,
   your accuracy numbers are misleading (computed only on the 70%
   that parsed). Report parse rate alongside accuracy.
6. **Not comparing zero-shot** — if zero-shot gets 85% accuracy,
   fine-tuning to 87% may not be worth the effort. Always measure
   the baseline.
7. **VRAM OOM** — reduce `max_seq_length`, use `load_in_4bit=True`,
   set `per_device_train_batch_size=1`. If still OOM, use a smaller
   model.

## Demos

This bundle includes two runnable marimo notebooks:

- **`demo.py`** — AG News text classification (4 classes, single label).
  Quick to run, good for validating the pipeline.
- **`demo_nhtsa.py`** — NHTSA vehicle safety complaints (multi-target:
  fire, crash, component via structured JSON output). Downloads NHTSA's
  2.2M-record complaint database automatically. Demonstrates
  **programmatic labeling**: using structured fields from an existing
  database as free supervision to train a model that works from raw
  text alone.

## Dependencies

This bundle uses PEP 723 inline script metadata. Run with:

```bash
marimo edit --sandbox demo.py
marimo edit --sandbox demo_nhtsa.py
```

If unsloth fails to install via sandbox (CUDA compatibility), install
manually in a venv:

```bash
python -m venv .venv && source .venv/bin/activate
pip install unsloth torch trl datasets mlflow scikit-learn numpy matplotlib requests marimo
marimo edit demo.py
```
