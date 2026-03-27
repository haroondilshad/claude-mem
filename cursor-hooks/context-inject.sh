#!/bin/bash
# External context injection hook for claude-mem (Cursor)
# Fetches context from the worker API and writes to .cursor/rules/claude-mem-context.mdc
# This runs as a beforeSubmitPrompt hook, receiving JSON on stdin

WORKER_PORT="${CLAUDE_MEM_PORT:-37777}"

INPUT=$(cat)

WORKSPACE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('workspace_roots',[''])[0])" 2>/dev/null)

if [ -z "$WORKSPACE" ] || [ ! -d "$WORKSPACE" ]; then
  echo '{"continue": true}'
  exit 0
fi

PROJECT=$(basename "$WORKSPACE")

# Check if worker is available (fast fail)
CONTEXT=$(curl -sf --connect-timeout 2 --max-time 5 \
  "http://127.0.0.1:${WORKER_PORT}/api/context/inject?projects=${PROJECT}" 2>/dev/null)

if [ -z "$CONTEXT" ]; then
  echo '{"continue": true}'
  exit 0
fi

# Rewrite upstream MCP references to point to the curl instructions below
CONTEXT=$(echo "$CONTEXT" | sed \
  -e 's/Use MCP tools (search, get_observations) to fetch full observations on-demand/See "Querying Past Work" section below for curl commands to fetch full observations/g' \
  -e 's/Use MCP search tools to access memories by ID\./See "Querying Past Work" below to fetch by ID or search semantically./g')

RULES_DIR="${WORKSPACE}/.cursor/rules"
RULES_FILE="${RULES_DIR}/claude-mem-context.mdc"
mkdir -p "$RULES_DIR"

# Atomic write
TEMP_FILE="${RULES_FILE}.tmp.$$"
cat > "$TEMP_FILE" << CTXEOF
---
alwaysApply: true
description: "Claude-mem context from past sessions (auto-updated)"
---

# Memory Context from Past Sessions

The following context is from claude-mem, a persistent memory system that tracks your coding sessions.

${CONTEXT}

---

## Querying Past Work (Deep Search)

When you need implementation details, rationale, or debugging context beyond what's shown above, query the claude-mem worker API (port 37777) via shell:

**Browse observations** (most reliable, always works):
\`curl -s "http://127.0.0.1:37777/api/observations?project=${PROJECT}&limit=20"\`

**Fetch specific observations by ID** (~500-1000 tokens each):
\`curl -s -X POST http://127.0.0.1:37777/api/observations/batch -H "Content-Type: application/json" -d '{"ids":[<ID1>,<ID2>]}'\`

**Semantic search** (requires Chroma vector DB to be running):
\`curl -s "http://127.0.0.1:37777/api/search?query=<term>&project=${PROJECT}&limit=20"\`

**Save a memory** (persist important context for future sessions):
\`curl -s -X POST http://127.0.0.1:37777/api/memory/save -H "Content-Type: application/json" -d '{"text":"...","project":"${PROJECT}"}'\`

The context summary above is usually sufficient. Use deep queries only when you need specific implementation details or debugging history.
CTXEOF

mv "$TEMP_FILE" "$RULES_FILE"

# Also register this project if not already registered
REGISTRY="${HOME}/.claude-mem/cursor-projects.json"
if [ -f "$REGISTRY" ]; then
  if ! python3 -c "import json; d=json.load(open('${REGISTRY}')); exit(0 if '${PROJECT}' in d else 1)" 2>/dev/null; then
    python3 -c "
import json, datetime
r = json.load(open('${REGISTRY}'))
r['${PROJECT}'] = {'workspacePath': '${WORKSPACE}', 'installedAt': datetime.datetime.utcnow().isoformat() + 'Z'}
json.dump(r, open('${REGISTRY}', 'w'), indent=2)
" 2>/dev/null
  fi
else
  python3 -c "
import json, datetime
r = {'${PROJECT}': {'workspacePath': '${WORKSPACE}', 'installedAt': datetime.datetime.utcnow().isoformat() + 'Z'}}
json.dump(r, open('${REGISTRY}', 'w'), indent=2)
" 2>/dev/null
fi

echo '{"continue": true}'
