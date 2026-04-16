# Model Naming and Quantization Reference

A field guide to the cryptic suffixes you'll see when browsing HuggingFace or
Unsloth for open-weight LLMs. If you've ever wondered what `gemma-4-E2B-it` or
`Qwen3-0.6B-unsloth-bnb-4bit-Q4_K_M.gguf` actually means, read this.

## The anatomy of a model ID

A model ID is a path: `{org}/{family}-{version}-{size}-{variant}-{quant}`. Each
segment is optional and ordering isn't strict, but this is roughly how the
HuggingFace ecosystem names things.

Example: `unsloth/gemma-4-E2B-it-unsloth-bnb-4bit`

- `unsloth` — org hosting the weights (Google, Meta, Alibaba repackage under
  `unsloth/...` with Unsloth's pre-quantized variants)
- `gemma-4` — family + version
- `E2B` — size (see below)
- `it` — variant (instruction-tuned)
- `unsloth-bnb-4bit` — quantization

## Size suffixes

### Plain parameter counts

Most models advertise their parameter count directly:

| Suffix                            | Meaning                          |
| --------------------------------- | -------------------------------- |
| `135M`, `360M`                    | millions of parameters (SmolLM2) |
| `0.5B`, `0.6B`, `1B`, `7B`, `70B` | billions of parameters           |
| `1.5B`, `3B`, `8B`, `13B`         | same, fractional                 |

Rule of thumb: **total VRAM ≈ params × bytes-per-param × 1.2 (overhead)**. For
fp16 that's 2 bytes/param; for 4-bit it's 0.5 bytes/param. A 7B model needs
roughly 17 GB in fp16 or roughly 5 GB in 4-bit for inference. Training adds
gradient and optimizer memory — roughly 4–6× the inference footprint for full
fine-tuning, or roughly 1.5× for LoRA/QLoRA.

### Gemma's "effective" notation (`E2B`, `E4B`)

Gemma 3n introduced **Matformer** — a nested transformer architecture where a
single weight file contains multiple sub-models at different scales. The `E`
prefix stands for **Effective**.

- `E2B` = behaves like a 2B parameter model for compute/latency, but the
  checkpoint contains more raw parameters (often 4-5B total). At inference, only
  the 2B "active" sub-network runs.
- `E4B` = 4B-equivalent compute from a larger checkpoint.

Why? You get the quality of a larger model's pre-training corpus and depth, but
pay only for the activated slice. Trade-off: the weight file on disk is bigger
than a plain 2B model, but runtime memory and latency match.

**Implication**: an `E2B` model fits the VRAM budget of a 2B model but often
outperforms it on quality benchmarks. Gemma 4 inherits this naming.

### "Mini", "Nano", "Small", "Medium", "Large"

Marketing suffixes for relative size within a family. No standard mapping —
check the model card. Phi-4-mini is ~3.8B; Qwen3-1.7B is sometimes called
"small"; Gemma-3n-E2B is "nano".

## Variant suffixes

These describe what kind of post-training the model has received on top of the
base pre-trained weights.

| Suffix      | Meaning                                              | Use case                                     |
| ----------- | ---------------------------------------------------- | -------------------------------------------- |
| (none)      | Base model — raw next-token predictor                | Pre-training continuation, research          |
| `-it`       | **I**nstruction-**t**uned (Google/Gemma convention)  | Chat, task-following, fine-tuning target     |
| `-Instruct` | Same as `-it`, different casing (Meta/Mistral/Qwen)  | Same                                         |
| `-Chat`     | Chat-tuned with multi-turn format (older convention) | Conversational agents                        |
| `-DPO`      | Direct Preference Optimization applied               | Follows preferences, refuses harmful prompts |
| `-RLHF`     | Reinforcement Learning from Human Feedback           | Same, older pipeline                         |
| `-Thinking` | Trained to emit `<think>...</think>` before answers  | Reasoning, math, complex tasks               |

**For fine-tuning, always start from an instruction-tuned variant**
(`-it`/`-Instruct`). Base models require much more data and steps to learn to
follow prompts. The exception: if you want a model that only outputs a specific
format (e.g., JSON extractor), starting from a base model avoids fighting the
existing instruction-following behavior.

**"Thinking" models** deserve special attention. They're trained to output a
`<think>` block before their actual answer. At inference, you must either:

1. Give them enough `max_new_tokens` to finish thinking AND produce the answer
   (typical thinking blocks are 100-500 tokens), then strip the
   `<think>...</think>` block
2. Disable thinking mode via the tokenizer:
   `tokenizer.apply_chat_template( messages, enable_thinking=False)` — Qwen3 and
   similar models support this

Fine-tuning a thinking model on short-answer examples (like classification
labels) teaches it to **skip thinking** entirely, which is usually what you want
for production.

## Tokenizer families and chat templates

Every model family has its own convention for formatting a multi-turn
conversation into a single token stream. You rarely write these tokens yourself
— `tokenizer.apply_chat_template(messages)` handles the formatting — but you
need to know which family your model belongs to because:

1. `get_chat_template()` in Unsloth takes a template **name** that must match
   the model
2. `train_on_responses_only()` needs the exact **instruction** and **response**
   delimiter tokens to mask correctly
3. Multimodal models use a **Processor** class with a different API than plain
   tokenizers

### Common chat template families

| Family               | Models using it                      | Turn delimiters                                                     | EOS token       |
| -------------------- | ------------------------------------ | ------------------------------------------------------------------- | --------------- |
| **ChatML**           | Qwen2/3, SmolLM2, some Mistral, Nous | `<\|im_start\|>role\n ... <\|im_end\|>`                             | `<\|im_end\|>`  |
| **Llama-3**          | Llama-3.x                            | `<\|start_header_id\|>role<\|end_header_id\|>\n\n ... <\|eot_id\|>` | `<\|eot_id\|>`  |
| **Gemma**            | Gemma 1-4                            | `<start_of_turn>role\n ... <end_of_turn>`                           | `<end_of_turn>` |
| **Gemma-4 internal** | Gemma 4 (Unsloth variant)            | `<\|turn>role\n ... <turn\|>`                                       | varies          |
| **Llama-2 / Alpaca** | Llama-2, some older Mistrals         | `[INST] ... [/INST]`                                                | `</s>`          |
| **Phi**              | Phi-3, Phi-4                         | `<\|user\|>\n ... <\|end\|>`                                        | `<\|end\|>`     |

ChatML is becoming the de facto standard for new open models because it's
simple, composable with system prompts, and maps cleanly to the OpenAI message
format. Llama and Gemma stuck with their own formats for historical reasons.

### Masking for `train_on_responses_only`

**TRL** (Transformer Reinforcement Learning) is HuggingFace's library for
post-training LLMs — it provides trainers for supervised fine-tuning, RLHF, DPO,
and other alignment techniques. **SFT** (Supervised Fine-Tuning) is the simplest
post-training method: you show the model input/output pairs and train it to
reproduce the outputs. TRL's `SFTTrainer` wraps HuggingFace's `Trainer` with
conveniences for chat-formatted data, LoRA, and response masking.

When fine-tuning with TRL's SFTTrainer, `train_on_responses_only()` masks
instruction tokens so the loss is computed **only on the model's output**, not
on the prompt. To do that, it needs two strings:

```python
trainer = train_on_responses_only(
    trainer,
    instruction_part="<|im_start|>user\n",   # where a user turn starts
    response_part="<|im_start|>assistant\n", # where the assistant turn starts
)
```

These must **exactly match** the tokens your tokenizer emits. A single wrong
character (e.g., missing `\n`, extra space) and masking silently fails — loss is
computed over the whole sequence and training still runs but produces a worse
model. Always verify by tokenizing a formatted example and checking which tokens
end up with a real label vs. -100.

The value **-100** is PyTorch's default `ignore_index` for `CrossEntropyLoss`.
Any token position with a label of -100 is excluded from the loss calculation
entirely — the model receives no gradient signal for predicting those tokens.
`train_on_responses_only` sets all instruction/prompt token labels to -100 so
that only the assistant's response tokens contribute to training loss.

Common mask tokens by family:

| Family                 | `instruction_part`                                 | `response_part`                                         |
| ---------------------- | -------------------------------------------------- | ------------------------------------------------------- |
| ChatML (Qwen, SmolLM2) | `<\|im_start\|>user\n`                             | `<\|im_start\|>assistant\n`                             |
| Llama-3                | `<\|start_header_id\|>user<\|end_header_id\|>\n\n` | `<\|start_header_id\|>assistant<\|end_header_id\|>\n\n` |
| Gemma                  | `<start_of_turn>user\n`                            | `<start_of_turn>model\n`                                |

### Tokenizer vs. Processor

Most text-only models expose a `PreTrainedTokenizerFast`. Multimodal models
(Gemma 3n/4, Llava, Idefics, Qwen-VL) expose a **`Processor`** — a wrapper that
combines a tokenizer, an image processor, and sometimes an audio processor. The
two have **different APIs**, and code written for one will silently break on the
other.

**Differences that matter for text-only usage:**

```python
# Plain tokenizer (Qwen3, SmolLM2, Llama-3):
inputs = tokenizer.apply_chat_template(
    messages, return_tensors="pt", add_generation_prompt=True,
)  # returns a torch.Tensor
inputs.to(model.device)
model.generate(input_ids=inputs, ...)

# Multimodal processor (Gemma-4):
prompt_text = processor.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True,
)  # returns a str, regardless of return_tensors!
inputs = processor(text=prompt_text, return_tensors="pt")  # must use text= kwarg
inputs = inputs.to(model.device)  # BatchFeature, has .to() method
model.generate(**inputs, ...)  # unpack because it has mm_token_type_ids etc.
```

Key gotchas:

1. **`apply_chat_template(..., return_tensors="pt")` returns `str`** on a
   processor, ignoring the `return_tensors` argument. You need a separate
   tokenization step.
2. **Processors require keyword arguments** — `processor(text=prompt)` works;
   `processor(prompt)` treats the first positional argument as `images` and
   fails with confusing errors like `'str' object has no attribute 'to'` or
   `'NoneType' object is not subscriptable`.
3. **`BatchFeature` (processor output) has extra keys** like
   `mm_token_type_ids`, `pixel_values`, `attention_mask`. Use
   `model.generate(**inputs, ...)` to forward them all, instead of pulling out
   `input_ids` individually.

If your `classify_batch`-style inference helper needs to support both, the
safest pattern is:

```python
prompt_text = tokenizer.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True,
)
inputs = tokenizer(text=prompt_text, return_tensors="pt").to(model.device)
output = model.generate(**inputs, max_new_tokens=256, do_sample=False)
response = tokenizer.decode(
    output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True,
)
```

This works for both plain tokenizers (which accept `text` as the first kwarg)
and multimodal processors.

### Verifying the template before training

When experimenting with a new model, **always print one formatted example before
training**. Catch template and mask mismatches immediately:

```python
sample = formatted_dataset[0]["formatted_text"]
print(repr(sample))

# Check that the mask tokens actually appear in the formatted text
assert cfg["mask_user"] in sample
assert cfg["mask_model"] in sample
```

Five minutes of verification saves hours of debugging why loss doesn't converge.

## Quantization suffixes

Quantization reduces weight precision to save VRAM and speed up inference. Two
ecosystems matter: **bitsandbytes (bnb)** for training, and **GGUF** for
llama.cpp inference.

### Training-time: bitsandbytes (bnb)

Unsloth pre-quantizes models for QLoRA training. These suffixes show up in the
HuggingFace repo name:

| Suffix             | Meaning                                                | VRAM savings     | Quality impact                         |
| ------------------ | ------------------------------------------------------ | ---------------- | -------------------------------------- |
| (none)             | Full precision (bf16/fp16)                             | baseline         | perfect                                |
| `bnb-4bit`         | Standard bitsandbytes NF4 quantization                 | ~4x reduction    | ~0.5% accuracy loss                    |
| `unsloth-bnb-4bit` | Unsloth's optimized 4-bit (dynamic quant of attention) | same as bnb-4bit | slightly better than standard bnb-4bit |

**Use Unsloth's variant when available** — it's strictly better than standard
`bnb-4bit` for the same memory cost. The `load_in_4bit=True` flag in
`FastModel.from_pretrained` selects these automatically if the variant exists on
HuggingFace.

**Caveat for tiny models (<300M params)**: 4-bit quantization can leave tensors
on the PyTorch `meta` device (uninitialized), causing
`NotImplementedError: Cannot copy out of meta tensor`. For models this small,
set `load_in_4bit=False` — they fit in fp16 anyway.

### Inference-time: GGUF (llama.cpp)

GGUF is the file format llama.cpp uses. A single `.gguf` file contains weights,
tokenizer, and metadata. Quantization is baked in at export time.

Naming: `unsloth.Q4_K_M.gguf` — the `Q4_K_M` is the quantization recipe.

| Name         | Bits | Size (7B model) | Use case                                         |
| ------------ | ---- | --------------- | ------------------------------------------------ |
| `F16`        | 16   | ~13 GB          | Max quality, "fp16" equivalent                   |
| `BF16`       | 16   | ~13 GB          | Same size, different float format                |
| `Q8_0`       | ~8   | ~7 GB           | Near-lossless, ~1% quality loss                  |
| `Q6_K`       | ~6   | ~5.5 GB         | Great quality, ~2% loss                          |
| `Q5_K_M`     | ~5   | ~4.8 GB         | Good quality, balanced                           |
| **`Q4_K_M`** | ~4   | ~4 GB           | **Recommended default.** Best size/quality ratio |
| `Q4_K_S`     | ~4   | ~3.8 GB         | Slightly smaller, slightly worse than K_M        |
| `Q3_K_M`     | ~3   | ~3.3 GB         | Acceptable for chat, noticeable degradation      |
| `Q2_K`       | ~2   | ~2.8 GB         | Last resort, quality drops significantly         |
| `IQ2_XS`     | ~2.3 | ~2.5 GB         | "Importance quantization", better than Q2        |

The letter suffixes:

- **`_0`**: simple symmetric quantization
- **`_K`**: "K-quant" — uses different quantization scales per block (better
  than `_0`)
- **`_S`** / **`_M`** / **`_L`**: size variant within the same K-quant family
  (small/medium/large). Larger = higher quality, slightly bigger
- **`IQ`** prefix: "importance quantization" — newer, smarter quantization that
  allocates more precision to important weights. Better than the same-bit `Q`
  variants

**Rule of thumb for deployment:**

- **`Q4_K_M`** — default choice for consumer hardware. 4x smaller than fp16,
  usually indistinguishable from fp16 in blind tests for most tasks
- **`Q5_K_M` or `Q6_K`** — when you have a little more RAM and want better
  quality
- **`Q8_0`** — when quality matters most and you have the space
- **`Q3_K_M` or smaller** — only on very constrained devices; expect perceptible
  quality drops

Export a fine-tuned model to GGUF with:

```python
model.save_pretrained_gguf(
    "my-model",
    tokenizer,
    quantization_method="q4_k_m",  # or "q5_k_m", "q8_0", "f16", ...
)
```

## Picking a model for fine-tuning

Decision tree:

1. **How much VRAM?**
   - 8 GB → Gemma-4 E2B, Llama-3.2 1B, Qwen3 0.6B-1.7B
   - 12 GB → Llama-3.2 3B (benchmark against E2B), Phi-4-mini
   - 16 GB → Gemma-4 E4B, Qwen3 7B
   - 24 GB+ → Llama-3.3 8B, Qwen3 14B, larger Gemmas

2. **What's the task?**
   - Classification / extraction / structured output → any instruction-tuned
     model at the size tier that fits. Start with Gemma-4 E2B
   - Conversational / multi-turn → Llama-3 or Gemma-4 in the `-it` variant
   - Reasoning / math → Qwen3 or a thinking-capable variant (but still fine-tune
     to skip thinking for production)

3. **Variant?** Always `-it` / `-Instruct` unless you have a specific reason to
   start from a base model.

4. **Quantization for training?** Always `load_in_4bit=True` with QLoRA, except
   for models <300M params where 4-bit quantization may leave tensors on the
   meta device — use fp16 for those.

5. **Quantization for deployment?** `Q4_K_M` is the default; bump to `Q5_K_M` or
   `Q8_0` if quality matters more than size.

## Further reading

- [Unsloth model zoo](https://huggingface.co/unsloth) — pre-quantized models
  ready for `FastModel.from_pretrained()`
- [llama.cpp quantization guide](https://github.com/ggerganov/llama.cpp/blob/master/examples/quantize/README.md)
  — GGUF details
- [Unsloth docs on QLoRA](https://docs.unsloth.ai/) — training-time quantization
  details
- `bundles/llm-finetuning/SKILL.md` — the skill doc that uses all this
  terminology in practice
