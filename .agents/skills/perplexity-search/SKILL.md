---
name: perplexity-search
description: Search the current public web with citations through either the perplexity-mcp v2 tools or the bundled Python REST client. Use for recent information, news, fact checks, source-backed comparisons, research, file-assisted questions, native follow-ups, and detached tasks. Both transports expose the same perplexity_ask_v2, perplexity_research_v2, and task method names and response shapes.
metadata:
  version: "3.0.0"
---

# Perplexity Search

Use one workflow regardless of transport. A connected `perplexity-mcp` server exposes tools directly; the bundled `scripts/client.py` exposes matching Python methods over REST.

| Operation | MCP tool | Python REST method |
|---|---|---|
| Focused search or cited answer | `perplexity_ask_v2` | `client.perplexity_ask_v2(...)` |
| Broad Deep Research | `perplexity_research_v2` | `client.perplexity_research_v2(...)` |
| Submit detached work | `perplexity_task_submit` | `client.perplexity_task_submit(...)` |
| Observe detached work | `perplexity_task_status` | `client.perplexity_task_status(...)` |
| Cancel detached work | `perplexity_task_cancel` | `client.perplexity_task_cancel(...)` |

Choose the available transport, then keep the same operation names, arguments, session rules, and output handling. Do not switch to legacy MCP tools such as `search`, `research`, or `perplexity_search`; they are deprecated.

## Python REST client

The client uses only the Python standard library. Load it from this skill's `scripts` directory:

```python
import sys
from pathlib import Path

skill_dir = Path(".agents/skills/perplexity-search").resolve()
sys.path.insert(0, str(skill_dir / "scripts"))

from client import PerplexityRestClient

client = PerplexityRestClient.from_config(skill_dir / "config.json")
result = client.perplexity_ask_v2(
    "What changed in Python packaging this month? Cite primary sources."
)
```

Configuration is shared by every REST method:

- `PPLX_BASE_URL`: service root, with or without `/v1`; defaults to `http://127.0.0.1:8000`.
- `MCP_TOKEN` or `PPLX_API_KEY`: bearer token; `MCP_TOKEN` takes precedence.
- `config.json`: fallback configuration when environment variables are absent.

Never print, quote, log, or commit real credentials.

## Focused Ask

Use `perplexity_ask_v2` for current facts, news, comparisons, source-backed analysis, and ordinary searches.

MCP arguments and Python arguments are identical:

```json
{
  "query": "Compare the latest Python packaging changes and cite primary sources.",
  "model": "gpt-5-6-terra",
  "thinking": true,
  "session_id": null,
  "files": null
}
```

```python
result = client.perplexity_ask_v2(
    query="Compare the latest Python packaging changes and cite primary sources.",
    model="gpt-5-6-terra",
    thinking=True,
)
```

Omit `model` to use `perplexity-search`. When selecting a model, pass the exact OAI model ID exposed by the server. Set `thinking=True` to select its paired thinking variant. Do not pass `perplexity-deepsearch` to Ask.

## Deep Research

Use `perplexity_research_v2` for broad investigations with several subtopics, many sources, or report-like synthesis.

```python
result = client.perplexity_research_v2(
    query=(
        "Research the 2026 enterprise AI agent market. Compare adoption, pricing, "
        "security constraints, and primary-source evidence."
    )
)
```

This operation always selects `perplexity-deepsearch`; it does not accept `model` or `thinking`.

## Response contract

Both transports return the same success shape for Ask and Research:

```json
{
  "status": "ok",
  "session_id": "sess_...",
  "job_id": "job_...",
  "model": "perplexity-search",
  "data": {
    "answer": "...",
    "sources": []
  }
}
```

Check `status` before using a result. Read the answer from `data.answer`, preserve direct URLs from `data.sources`, and distinguish sourced facts from your synthesis.

Failures use the same top-level convention:

```json
{
  "status": "error",
  "error_type": "...",
  "message": "..."
}
```

Report the non-secret error type and message. Do not silently change models, replace sessions, or treat incomplete task output as success.

## Sessions

Omit `session_id` to create a native session. For a same-topic follow-up, call the same operation with the returned ID and only the latest instruction:

```python
follow_up = client.perplexity_ask_v2(
    query="Add exact release dates and one primary source per claim.",
    session_id=result["session_id"],
)
```

Keep the session ID with its operation family. Start a new session when the topic changes. A session is permanently bound to its first account and supports at most one unfinished task; it does not fail over or accept concurrent turns.

## Files

Pass attachments through `files` on either Ask, Research, or task submission.

For MCP, `files` follows the server tool schema. For Python REST, use either a filename-to-content mapping or an iterable of local paths:

```python
client.perplexity_ask_v2(
    "Summarize the attached evidence and verify current claims on the web.",
    files=["reports/evidence.pdf"],
)

client.perplexity_ask_v2(
    "Review this note.",
    files={"note.txt": "local text content"},
)
```

The REST client reads local paths and sends base64 `input_file` content, so the remote server does not need access to the client's filesystem. Respect server limits: at most 10 files, 20 MiB per file, 100 MiB per request, and allowed extensions.

## Detached tasks

Use detached tasks only when work must survive caller disconnects, is expected to run for a long time, or consists of independent concurrent conversations.

MCP users should call `get_skill_index` and read `get_tasks_use` before the task tools. Python users call the same task operations through REST:

```python
accepted = client.perplexity_task_submit(
    query="Research WebAssembly component model adoption with primary sources.",
    model="perplexity-deepsearch",
    idempotency_key="wasm-adoption-1",
)

status = client.perplexity_task_status(
    accepted["job_id"],
    wait_seconds=20,
    include_output=False,
)
```

A successful submission means admission, not completion. Retain both `job_id` and `session_id`. Only `state == "completed"` is complete. Fetch output with `include_output=True`; the answer is in `snapshot.answer`. Treat `failed`, `timed_out`, `cancelled`, and `interrupted` as non-success even when a draft exists.

Reuse an `idempotency_key` only to recover the same submission after a lost receipt. Use a different session for each concurrent task. Cancel explicitly when the task is no longer needed:

```python
client.perplexity_task_cancel(accepted["job_id"])
```

Cancellation cannot undo upstream work already accepted.

## Command line

The CLI uses the exact MCP tool names:

```bash
python3 "$SKILL_DIR/scripts/client.py" perplexity_ask_v2 \
  "What changed this week? Cite primary sources."

python3 "$SKILL_DIR/scripts/client.py" perplexity_research_v2 \
  "Research current enterprise AI agent adoption."

python3 "$SKILL_DIR/scripts/client.py" perplexity_task_status job_... \
  --wait-seconds 20
```

`cli.py` remains a compatibility entry point and dispatches to the same client. Use `client.py` for new integrations.
