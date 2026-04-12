#!/usr/bin/env python3
"""
Structured-output probe for claude-mem: ask OpenRouter models to emit <observation> XML
parseable like src/sdk/parser.ts (regex on <observation>...</observation>).

Usage:
  python3 scripts/openrouter-structured-xml-probe.py
  OPENROUTER_STRUCTURED_MODELS=model1,model2 python3 scripts/openrouter-structured-xml-probe.py

Reads OPENROUTER_API_KEY or ~/.claude-mem/settings.json (CLAUDE_MEM_OPENROUTER_API_KEY).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODELS = [
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "google/gemma-4-31b-it:free",
]

VALID_TYPES = frozenset(
    {"bugfix", "feature", "refactor", "change", "discovery", "decision"}
)

SYSTEM = """You extract structured memories from tool usage. Respond with EXACTLY ONE root element:
<observation>
  <type>...</type>
  <title>...</title>
  <subtitle>...</subtitle>
  <narrative>...</narrative>
  <facts>
    <fact>...</fact>
  </facts>
  <concepts>
    <concept>...</concept>
  </concepts>
  <files_read>
    <file>...</file>
  </files_read>
  <files_modified>
    <file>...</file>
  </files_modified>
</observation>
No markdown fences. No text before or after the observation block. Use type "discovery" for this task."""

USER = """<observed_from_primary_session>
  <what_happened>Bash</what_happened>
  <occurred_at>2026-04-12T12:00:00.000Z</occurred_at>
  <working_directory>/tmp/claude-mem-probe</working_directory>
  <parameters>{"command": "ls -la"}</parameters>
  <outcome>{"exitCode": 0, "stdout": "total 0"}</outcome>
</observed_from_primary_session>"""


def load_key() -> str:
    k = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if k:
        return k
    p = Path.home() / ".claude-mem" / "settings.json"
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        k = (data.get("CLAUDE_MEM_OPENROUTER_API_KEY") or "").strip()
    return k


def extract_field(block: str, name: str) -> str | None:
    m = re.search(rf"<{name}>([\s\S]*?)</{name}>", block)
    if not m:
        return None
    t = m.group(1).strip()
    return t or None


def parse_observations(text: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for m in re.finditer(r"<observation>([\s\S]*?)</observation>", text):
        inner = m.group(1)
        out.append(
            {
                "type": extract_field(inner, "type"),
                "title": extract_field(inner, "title"),
                "has_facts": "<facts>" in inner,
                "has_concepts": "<concepts>" in inner,
            }
        )
    return out


def call_model(api_key: str, model: str) -> tuple[int, str, float]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
        ],
        "temperature": 0.2,
        "max_tokens": 2048,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/thedotmack/claude-mem",
            "X-Title": "claude-mem structured-xml-probe",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return resp.status, content or "", time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:500]
        return e.code, err, time.perf_counter() - t0
    except Exception as ex:
        return -1, str(ex), time.perf_counter() - t0


def main() -> int:
    key = load_key()
    if not key:
        print(
            "No API key: OPENROUTER_API_KEY or ~/.claude-mem/settings.json",
            file=sys.stderr,
        )
        return 1

    raw = os.environ.get("OPENROUTER_STRUCTURED_MODELS", "").strip()
    models = [x.strip() for x in raw.split(",") if x.strip()] if raw else DEFAULT_MODELS
    pause = float(os.environ.get("OPENROUTER_STRUCTURED_PAUSE_SEC", "20"))

    print("--- claude-mem <observation> XML probe (parser-compatible regex) ---\n")
    results: list[tuple[str, str, str]] = []

    for i, model in enumerate(models):
        if i and pause > 0:
            time.sleep(pause)
        status, text, elapsed = call_model(key, model)
        if status != 200:
            results.append((model, "FAIL", f"HTTP {status} in {elapsed:.2f}s — {text[:200]}"))
            print(f"### {model}\n  FAIL: HTTP {status} ({elapsed:.2f}s)\n  {text[:400]}\n")
            continue

        obs = parse_observations(text)
        if not obs:
            results.append((model, "FAIL", f"no <observation> block ({elapsed:.2f}s)"))
            print(f"### {model}\n  FAIL: no <observation> block ({elapsed:.2f}s)\n  preview: {text[:500]!r}\n")
            continue

        o0 = obs[0]
        typ = o0.get("type")
        ok_type = isinstance(typ, str) and typ in VALID_TYPES
        title_ok = bool(o0.get("title"))

        status_label = "PASS" if (ok_type and title_ok and len(obs) == 1) else "WEAK"
        detail = (
            f"type={typ!r} valid_type={ok_type} title={bool(title_ok)} "
            f"blocks={len(obs)} elapsed_s={elapsed:.2f}"
        )
        results.append((model, status_label, detail))

        print(f"### {model}\n  {status_label}: {detail}\n  response_tail: {text[-400:]!r}\n")

    print("--- summary ---")
    for m, s, d in results:
        print(f"  {s:4} {m} — {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
