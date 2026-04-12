#!/usr/bin/env python3
"""
Burst a few tiny chat completions per model and print status + rate-limit headers.
Usage: reads OPENROUTER_API_KEY from env, else ~/.claude-mem/settings.json CLAUDE_MEM_OPENROUTER_API_KEY.

  OPENROUTER_API_KEY=sk-or-... python3 scripts/openrouter-free-rate-probe.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://openrouter.ai/api/v1/chat/completions"
BODY = {
    "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
    "max_tokens": 4,
    "temperature": 0,
}

# All :free models with context >= 128k on OpenRouter (text, $0) as of API /v1/models.
# Optional: OPENROUTER_PROBE_MODELS=comma,separated,ids to subset.
MODELS = [
    "arcee-ai/trinity-large-preview:free",
    "google/gemma-3-27b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "minimax/minimax-m2.5:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "qwen/qwen3-coder:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "z-ai/glm-4.5-air:free",
]

BURST = int(os.environ.get("OPENROUTER_PROBE_BURST", "6"))


def load_key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if k:
        return k
    p = Path.home() / ".claude-mem" / "settings.json"
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            k = (data.get("CLAUDE_MEM_OPENROUTER_API_KEY") or "").strip()
        except (OSError, json.JSONDecodeError):
            return ""
    return k


def header_lookup(headers: dict[str, str], name: str) -> str:
    for hk, hv in headers.items():
        if hk.lower() == name.lower():
            return hv
    return ""


def probe_model(api_key: str, model: str) -> None:
    print(f"\n=== {model} ({BURST} back-to-back requests) ===")
    ok = 0
    r429 = 0
    last_rl = ""
    t0 = time.perf_counter()
    for i in range(BURST):
        payload = dict(BODY)
        payload["model"] = model
        req = urllib.request.Request(
            URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/claude-mem/claude-mem",
                "X-Title": "claude-mem rate probe",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                status = resp.status
                hdrs = {k: v for k, v in resp.headers.items()}
                rl = header_lookup(hdrs, "x-ratelimit-remaining")
                rl_lim = header_lookup(hdrs, "x-ratelimit-limit")
                rl_reset = header_lookup(hdrs, "x-ratelimit-reset")
                if rl or rl_lim:
                    last_rl = f"remaining={rl!r} limit={rl_lim!r} reset={rl_reset!r}"
                if status == 200:
                    ok += 1
                print(f"  [{i+1}/{BURST}] HTTP {status}  {last_rl or '(no X-RateLimit-* headers)'}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            hdrs = {k: v for k, v in e.headers.items()} if e.headers else {}
            rl = header_lookup(hdrs, "x-ratelimit-remaining")
            rl_lim = header_lookup(hdrs, "x-ratelimit-limit")
            if e.code == 429:
                r429 += 1
            print(f"  [{i+1}/{BURST}] HTTP {e.code}  remaining={rl!r} limit={rl_lim!r}  body={body!r}")
        except Exception as ex:
            print(f"  [{i+1}/{BURST}] ERROR {type(ex).__name__}: {ex}")
    elapsed = time.perf_counter() - t0
    print(f"  summary: ok_200={ok} http_429={r429} elapsed_s={elapsed:.2f}")


def main() -> int:
    key = load_key()
    if not key:
        print("No API key: set OPENROUTER_API_KEY or CLAUDE_MEM_OPENROUTER_API_KEY in ~/.claude-mem/settings.json", file=sys.stderr)
        return 1
    raw = os.environ.get("OPENROUTER_PROBE_MODELS", "").strip()
    models = [x.strip() for x in raw.split(",") if x.strip()] if raw else MODELS
    print("Xiaomi: OpenRouter has no xiaomi/*:free models in /api/v1/models — only paid xiaomi/mimo-v2-flash etc.")
    print("Tip: space bursts with sleep or use OPENROUTER_PROBE_BURST=2 — OpenRouter free-models-per-min is shared across models.")
    for m in models:
        probe_model(key, m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
