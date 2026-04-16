# Model Architectures Reference

A shallow-but-substantive guide to the architectural ideas behind modern LLMs.
Intended as background material for executive-level presentations and as a
reference when evaluating model trade-offs.

## The Transformer (baseline)

Every model discussed here is a **transformer** — the architecture introduced in
"Attention Is All You Need" (Vaswani et al., 2017). The core loop:

1. **Tokenize** — split text into sub-word tokens (integers).
2. **Embed** — map each token to a high-dimensional vector.
3. **Transformer blocks** (repeated N times) — each block applies:
   - **Self-attention** — every token looks at every other token to decide what
     context matters.
   - **Feed-forward network (FFN)** — a two-layer MLP that processes each
     token's representation independently.
   - **Layer normalization + residual connections** — stabilize training.
4. **Predict** — project the final representation back to vocabulary size and
   pick the most likely next token.

The two key dimensions that determine model size:

- **Width** (hidden dimension `d_model`) — how rich each token's representation
  is. Gemma-4 E2B uses `d_model = 2304`; GPT-4 class models are rumored to be
  12,000+.
- **Depth** (number of layers) — how many rounds of attention + FFN the input
  passes through. More layers = more capacity for complex reasoning chains.

Parameter count ≈ `12 × d_model² × n_layers` (rough rule for decoder-only
models). This is why "7B" and "70B" models exist — they differ mainly in width
and depth.

## Multi-Head Attention (MHA)

Standard self-attention computes a single set of attention weights: for each
token, "how much should I attend to each other token?" **Multi-head attention**
runs multiple independent attention computations in parallel, each with its own
learned projection. The outputs are concatenated and projected back.

**Why multiple heads?** Different heads learn to attend to different things:

- Head 1 might learn syntactic relationships (subject-verb agreement)
- Head 2 might track entity coreference ("she" → "Dr. Chen")
- Head 3 might capture positional patterns (nearby tokens)

Each head operates on a slice of the full hidden dimension, so the total compute
is the same as one large attention — it's a repartitioning, not an increase.

**Parameters per attention layer:**

- Query, Key, Value projection matrices: `3 × d_model × d_model`
- Output projection: `d_model × d_model`
- Total: `4 × d_model²`

Typical head counts: 32 heads for 7B models, 64 for 70B models.

## Multi-Query Attention (MQA) and Grouped-Query Attention (GQA)

Standard MHA gives each head its own Key and Value projections. This means the
**KV cache** (stored key/value tensors from prior tokens during generation)
scales linearly with the number of heads. For long sequences on large models,
the KV cache can consume more memory than the model weights themselves.

**Multi-Query Attention (MQA)** — all heads share a single Key and single Value
projection, but each head still has its own Query. The KV cache shrinks by a
factor equal to the number of heads (e.g., 32× smaller). Quality drops slightly
because the keys and values are less expressive.

**Grouped-Query Attention (GQA)** — a middle ground. Instead of one shared KV
pair (MQA) or one per head (MHA), heads are organized into groups that share KV
projections. Llama 3 uses 8 KV groups with 32 query heads (4 query heads per KV
group).

| Approach | KV heads      | KV cache size | Quality        | Used by                  |
| -------- | ------------- | ------------- | -------------- | ------------------------ |
| MHA      | = query heads | largest       | highest        | GPT-3, older models      |
| GQA      | < query heads | moderate      | near-MHA       | **Llama 3**, Gemma 2/3/4 |
| MQA      | 1             | smallest      | slightly lower | Falcon, PaLM             |

**Executive summary:** GQA is the current industry standard because it gives
nearly the same quality as full MHA while making inference significantly cheaper
on long sequences.

## KV Cache and Why It Matters

During text generation, the model produces one token at a time. Without caching,
it would recompute attention over the entire sequence for every new token —
quadratic cost. The **KV cache** stores the Key and Value tensors from all
previous tokens so each new token only computes attention against the cached
values.

**Trade-off:** The KV cache consumes memory proportional to
`sequence_length × n_kv_heads × d_head × 2 (K+V) × bytes_per_param`. For a 7B
model with 4096-token context in fp16, that's roughly 1–2 GB. For 128K context
windows, it can exceed the model weights themselves.

This is why GQA and MQA exist — they directly reduce KV cache size, enabling
longer contexts and higher throughput on the same hardware.

## Mixture of Experts (MoE)

A standard transformer processes every token through the same FFN in each layer.
**Mixture of Experts** replaces the single FFN with multiple "expert" FFNs and a
lightweight **router** (also called a gating network) that decides which experts
to activate for each token.

**How it works:**

1. The router (a small linear layer) scores each expert for the current token.
2. The top-K experts (typically K=2) are selected.
3. Only those K experts run their FFN computation.
4. Outputs are combined as a weighted sum based on the router's scores.

**Why this matters:**

- **Total parameters** are much larger (each expert has its own FFN weights),
  but **active parameters per token** stay small because only K experts fire.
- Mixtral 8×7B has 47B total parameters but only activates roughly 13B per token
  — it gets close to a 70B model's quality at a 13B model's compute cost.
- The model card says "47B" but it runs like a 13B. This is why MoE models seem
  to punch above their weight class.

**Trade-offs:**

- **Disk and RAM are larger** — you store all experts even though only a few
  run. Mixtral needs 47B parameters on disk, not 13B.
- **Load balancing** — if the router sends too many tokens to the same expert,
  that expert becomes a bottleneck. Training uses an auxiliary loss to encourage
  even distribution.
- **Fine-tuning complexity** — some experts may be underutilized and
  undertrained for your specific task.

**Notable MoE models:** | Model | Experts | Active | Total params | Effective
size | |---|---|---|---|---| | Mixtral 8×7B | 8 | 2 | 47B | ~13B compute | |
Mixtral 8×22B | 8 | 2 | 141B | ~39B compute | | DeepSeek-V2 | 160 | 6 | 236B |
~21B compute | | Qwen2.5-MoE | 64 | 8 | 57B | ~14B compute |

**Executive summary:** MoE gets you a bigger model's quality for a smaller
model's inference cost, at the expense of larger storage and more complex
training. It's the dominant architecture for frontier-scale models.

## Matformer (Nested / Elastic Transformers)

**Matformer** is the architecture behind Gemma 3n and Gemma 4's "effective size"
naming (E2B, E4B). The key idea: train a single model that contains multiple
sub-models of different sizes, nested inside each other like Russian dolls.

**How it works:**

1. The full model has width `d_model` (say, 4096).
2. The weight matrices are structured so that the first `d_model/2` dimensions
   form a coherent smaller model, and the first `d_model/4` form an even smaller
   one.
3. At inference, you choose which "slice" to run based on your latency/quality
   budget.
4. The training process jointly optimizes all slices simultaneously using a
   technique called **elastic width training** — each training step randomly
   samples a width and backpropagates through that slice.

**Why this matters:**

- **One checkpoint, multiple deployment targets.** Download the E4B weights
  once; deploy as E2B on a phone, E4B on a server.
- **The smaller slices inherit quality from the full model's training.** The E2B
  slice was effectively trained on the same data as the full model, just through
  a narrower bottleneck. It outperforms a standalone 2B model trained from
  scratch.
- **On-device adaptability.** A running model can dynamically switch between
  slices based on available compute (e.g., switch to the smaller slice when
  battery is low).

**Trade-off:** The checkpoint on disk is larger than a plain 2B model because it
contains the full weight matrix. But runtime memory and compute match the
effective size.

**Executive summary:** Matformer lets you ship one model that adapts to
different hardware constraints at inference time. It's why Gemma E2B punches
above a typical 2B model — it's a slice of a much larger trained network.

## Rotary Position Embeddings (RoPE)

Transformers are inherently position-unaware — the self-attention mechanism
treats token order as arbitrary unless you inject positional information.
**RoPE** encodes position by rotating the query and key vectors in 2D subspaces
at frequencies that vary across dimensions.

**Why RoPE won:** Earlier approaches (sinusoidal embeddings, learned position
embeddings) were fixed at training time — a model trained on 2048 tokens
couldn't generalize to 4096. RoPE's rotation-based encoding degrades gracefully
beyond the training length and can be extended with techniques like **YaRN**
(Yet another RoPE extensioN) or **NTK-aware scaling** to support context lengths
far beyond what the model saw in training.

Nearly all modern open models (Llama 2+, Gemma, Qwen, Mistral, Phi) use RoPE.

## Flash Attention

Not an architectural change but an implementation optimization that's become
standard. Standard self-attention materializes the full `n × n` attention matrix
in GPU memory (where n is sequence length). **Flash Attention** computes the
same result without ever materializing the full matrix, using tiling and online
softmax to keep the computation in fast SRAM.

**Impact:** 2–4× faster attention, enabling longer sequences without running out
of memory. Flash Attention 2 and 3 add further optimizations. It's now the
default in most training and inference frameworks.

**Executive summary:** Flash Attention made long-context models practical. It
doesn't change what the model computes — just makes it feasible to compute.

## LoRA and QLoRA (how fine-tuning fits in)

Not architectures themselves, but adapters that modify how you interact with
these architectures during fine-tuning.

**LoRA** (Low-Rank Adaptation) freezes the pre-trained weights and injects small
trainable matrices into each attention layer. Instead of updating a
`d_model × d_model` weight matrix (millions of parameters), you train two small
matrices of rank `r` (typically 8–32): one `d_model × r` and one `r × d_model`.
The product is added to the frozen weights.

**QLoRA** combines LoRA with 4-bit quantization of the frozen weights. The base
model runs in 4-bit precision (saving 4× memory), while the LoRA adapters train
in full precision. This is how you fine-tune a 7B model on an 8 GB GPU.

**Relationship to architecture:** LoRA/QLoRA work with all the architectures
above — MHA, GQA, MoE, Matformer. The LoRA adapters are injected into the
attention and FFN projection matrices regardless of the underlying architecture.
For MoE models, adapters are typically added to all experts (some frameworks
allow selective expert adaptation).

## Architecture Decision Matrix

When evaluating a model for fine-tuning or deployment, these architectural
features determine the practical trade-offs:

| Feature            | Affects                        | What to check                                      |
| ------------------ | ------------------------------ | -------------------------------------------------- |
| MHA vs GQA         | Inference speed, KV cache size | GQA preferred for long-context serving             |
| Dense vs MoE       | Disk size vs compute cost      | MoE needs more disk/RAM but less compute per token |
| Matformer          | Deployment flexibility         | One checkpoint, multiple effective sizes           |
| RoPE + extension   | Max context length             | Check if YaRN/NTK scaling is applied               |
| Flash Attention    | Training and inference speed   | Usually automatic in modern frameworks             |
| LoRA compatibility | Fine-tuning feasibility        | All architectures support it; MoE may need care    |

## Further Reading

- "Attention Is All You Need" (Vaswani et al., 2017) — the original transformer
- "GQA: Training Generalized Multi-Query Transformer Models from Multi-Head
  Checkpoints" (Ainslie et al., 2023)
- "Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts
  Layer" (Shazeer et al., 2017)
- "Matformer: Nested Transformer for Elastic Inference" (Devvrit et al., 2023)
- "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness"
  (Dao et al., 2022)
- "LoRA: Low-Rank Adaptation of Large Language Models" (Hu et al., 2021)
- `bundles/llm-finetuning/MODEL_NAMING.md` — naming conventions and quantization
- `bundles/llm-finetuning/SKILL.md` — the fine-tuning workflow that uses these
  models
