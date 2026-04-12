# OpenRouter free models: shared limits & evaluation (April 2026)

This document records **how OpenRouter free-tier limits work**, **empirical burst tests** on every `:free` model with **≥128k context** (text in / text out, $0), and **how to re-run or extend** the evaluation when new models appear.

Canonical filter used: [OpenRouter models — 128k+ context, text, max price $0](https://openrouter.ai/models?context=128000&fmt=cards&input_modalities=text&max_price=0&output_modalities=text).

## What “shared limits on free models” means

OpenRouter applies **at least two different** rate-limit mechanisms:

### 1. Account-level free throughput (`free-models-per-min`)

- When this trips, errors often look like: `Rate limit exceeded: free-models-per-min`.
- Response metadata may include headers such as **`X-RateLimit-Limit`** (commonly **16–20** in observed errors), **`X-RateLimit-Remaining: 0`**, and **`X-RateLimit-Reset`**.
- This limit is **shared across all free-model calls on your OpenRouter API key** for a time window (per-minute style behavior). **Hammering model A can exhaust the bucket for model B** in the same minute.
- **Mitigation:** space out requests; reduce hook/worker concurrency; use `OPENROUTER_PROBE_BURST=1` or add pauses between probe models; add credits or **provider keys** in OpenRouter settings if you need higher throughput.

### 2. Upstream provider throttling

- When the **host behind OpenRouter** (e.g. Google, Meta, Qwen) is saturated, errors often include text like: `temporarily rate-limited upstream`.
- This is **not** the same counter as `free-models-per-min`; cooldown/retry behavior can differ per provider.
- **Mitigation:** retry with backoff; pick a different model; use BYOK where supported.

Always inspect **HTTP status**, **JSON error `message` / `metadata`**, and **rate-limit headers** to see which regime you hit.

## Xiaomi / StepFun “free” slugs

- As of API checks in **April 2026**, **`xiaomi/mimo-v2-flash:free`** does **not** appear in `GET https://openrouter.ai/api/v1/models` (paid `xiaomi/mimo-v2-flash` exists).
- **`stepfun/step-3.5-flash:free`** is also absent; only **`stepfun/step-3.5-flash`** (paid) is listed. Historical setups that referenced `:free` may **silently break** until the model id is updated.

## Test harness (repository)

### Rate limits (throughput)

Script: **`scripts/openrouter-free-rate-probe.py`**

- Reads **`OPENROUTER_API_KEY`** or **`~/.claude-mem/settings.json`** → `CLAUDE_MEM_OPENROUTER_API_KEY`.
- For each model (or `OPENROUTER_PROBE_MODELS=id1,id2`), sends **`OPENROUTER_PROBE_BURST`** (default **6**) **back-to-back** tiny chat completions (`max_tokens: 4`, “reply ok”).
- Prints per-request HTTP status and any **`X-RateLimit-*`** headers.

Examples:

```bash
# Full list (all free models with 128k+ context in script)
python3 scripts/openrouter-free-rate-probe.py

# Lighter burst
OPENROUTER_PROBE_BURST=2 python3 scripts/openrouter-free-rate-probe.py

# One model
OPENROUTER_PROBE_MODELS=google/gemma-4-31b-it:free OPENROUTER_PROBE_BURST=8 python3 scripts/openrouter-free-rate-probe.py
```

**Interpreting results:** A long run across **many** models in one minute will hit **`free-models-per-min`** even if each individual model is healthy. Re-test suspicious “all 429” models **alone** after **60–90s** cooldown. Single-request success after cooldown usually means the model is fine and the **account free bucket** was empty.

### Structured `<observation>` XML (claude-mem parser)

Script: **`scripts/openrouter-structured-xml-probe.py`**

- Sends a **system + user** prompt requiring a single `<observation>...</observation>` block compatible with `src/sdk/parser.ts` (regex extraction).
- Default models: **`nvidia/nemotron-3-nano-30b-a3b:free`**, **`nvidia/nemotron-nano-9b-v2:free`**, **`google/gemma-4-31b-it:free`** (override with `OPENROUTER_STRUCTURED_MODELS`).
- **Session (April 2026):** all three returned **PASS** (valid `type` ∈ code mode ids, non-empty `title`, exactly one block). Approx. latency ~5s / ~28s / variable with ~25s pause between models.

**Gate for defaults:** A model is **not** a viable claude-mem candidate until it **PASS**es this structured probe (throughput alone is insufficient). Re-run it for any candidate before promoting to `CLAUDE_MEM_OPENROUTER_MODEL` / fallbacks.

```bash
OPENROUTER_STRUCTURED_PAUSE_SEC=25 python3 scripts/openrouter-structured-xml-probe.py
```

## Models in scope (16 ids)

All **`…:free`** models with **`context_length` ≥ 128000** from OpenRouter `/api/v1/models` at evaluation time.

| Model id | Notes |
|----------|--------|
| `arcee-ai/trinity-large-preview:free` | Card text on OpenRouter: **preview ending ~2026-04-22** — avoid for long-term defaults. |
| `google/gemma-3-27b-it:free` | See results below. |
| `google/gemma-4-26b-a4b-it:free` | MoE; sometimes upstream 429 under burst then recovers. |
| `google/gemma-4-31b-it:free` | Strong burst results in our run. |
| `meta-llama/llama-3.2-3b-instruct:free` | Often upstream-limited under burst. |
| `minimax/minimax-m2.5:free` | Works; may show `free-models-per-min` if account bucket exhausted. |
| `nousresearch/hermes-3-llama-3.1-405b:free` | Large; often upstream 429 under burst. |
| `nvidia/nemotron-3-super-120b-a12b:free` | Slower but passed burst in our run. |
| `nvidia/nemotron-3-nano-30b-a3b:free` | Fast, passed burst. |
| `nvidia/nemotron-nano-12b-v2-vl:free` | VL; occasional `free-models-per-min` when bucket tight. |
| `nvidia/nemotron-nano-9b-v2:free` | Fastest passes in our run. |
| `openai/gpt-oss-120b:free` | Same account-level free bucket story as other free ids. |
| `openai/gpt-oss-20b:free` | Same. |
| `qwen/qwen3-coder:free` | Often upstream 429 under burst. |
| `qwen/qwen3-next-80b-a3b-instruct:free` | Upstream 429 persisted in cooldown single-shot test in our run. |
| `z-ai/glm-4.5-air:free` | Works when account bucket has quota. |

## Empirical results (April 2026, one session)

Environment: local run against user’s OpenRouter key; **not** a guarantee of future capacity.

**Burst = 6 rapid requests per model** in sequence (so later models are more likely to see **shared `free-models-per-min`** exhaustion).

### Strong under burst (mostly or all HTTP 200)

- `google/gemma-4-31b-it:free` — **6/6** OK.
- `arcee-ai/trinity-large-preview:free` — **6/6** OK (still avoid for longevity).
- `nvidia/nemotron-3-super-120b-a12b:free` — **6/6** OK (higher latency).
- `nvidia/nemotron-3-nano-30b-a3b:free` — **6/6** OK.
- `nvidia/nemotron-nano-9b-v2:free` — **6/6** OK.

### Mixed

- `google/gemma-4-26b-a4b-it:free` — **2×** upstream 429, then **4×** OK.
- `nvidia/nemotron-nano-12b-v2-vl:free` — **5/6** (one **`free-models-per-min`** 429).

### Mostly upstream 429 in burst

- `meta-llama/llama-3.2-3b-instruct:free` — **0/6**.
- `nousresearch/hermes-3-llama-3.1-405b:free` — **0/6**.
- `qwen/qwen3-coder:free` — **0/6**.
- `qwen/qwen3-next-80b-a3b-instruct:free` — **0/6**; **still 429** on a **single** request after ~75s cooldown (upstream).

### `free-models-per-min` during megaburst (recover after cooldown)

These returned **only** account-level free RPM errors when run **after** many successful calls in the same minute; **~75s later**, **single** requests returned **200**:

- `minimax/minimax-m2.5:free`
- `openai/gpt-oss-20b:free`
- `z-ai/glm-4.5-air:free`

`openai/gpt-oss-120b:free` showed the same pattern in the megaburst (all 429) — treat like other free ids tied to the **shared** bucket.

### `google/gemma-3-27b-it:free` (requested follow-up)

- **Burst 6/6:** upstream 429.
- **Single request ~75s later:** still **429** upstream in our session.

So Gemma 3 free was **not** viable at that moment; **retry** off-peak or after provider capacity changes. Do **not** rely on a one-time probe as permanent—re-run `OPENROUTER_PROBE_MODELS=google/gemma-3-27b-it:free`.

## Recommendations for claude-mem (speed + limits + “not dumb”)

1. **Shipped defaults (code + settings):** primary **`nvidia/nemotron-3-nano-30b-a3b:free`**, fallbacks **`nvidia/nemotron-nano-9b-v2:free`**, **`google/gemma-4-31b-it:free`** (`CLAUDE_MEM_OPENROUTER_MODEL` / `CLAUDE_MEM_OPENROUTER_MODEL_FALLBACKS`). The worker tries each OpenRouter id in order on **429** or **405**, then Mistral if configured.
2. **Do not use** `arcee-ai/trinity-large-preview:free` as a long-lived default (preview sunset on OpenRouter’s card).
3. **Avoid relying on** models that showed **persistent upstream 429** until re-validated (`qwen/qwen3-next-80b-a3b-instruct:free`, `google/gemma-3-27b-it:free` in this session).
4. **Always** validate with real worker traffic after probes.

## How to evaluate a **new** incoming free model

1. Confirm it exists: `GET https://openrouter.ai/api/v1/models` and check `id`, `context_length`, `pricing` ($0).
2. Add the id to **`OPENROUTER_PROBE_MODELS`** (or extend `MODELS` in the script temporarily).
3. Run **`OPENROUTER_PROBE_BURST=6`** after a **cooldown** from other free traffic.
4. If **429**, distinguish **`free-models-per-min`** vs **upstream** from the error body.
5. Run **`scripts/openrouter-structured-xml-probe.py`** for that id — must **PASS** (see gate above).
6. Run **claude-mem E2E** (session + observations + summary) before changing defaults.

## Related docs

- Published usage: `docs/public/usage/openrouter-provider.mdx`
- Worker implementation: `src/services/worker/OpenRouterAgent.ts`
- Probes: `scripts/openrouter-free-rate-probe.py`, `scripts/openrouter-structured-xml-probe.py`
