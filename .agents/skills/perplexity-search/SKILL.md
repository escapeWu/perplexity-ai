---
name: perplexity-search
description: Use the project's perplexity-mcp v2 tools for current public-web search, fact checking, cited comparisons, and research. Trigger whenever an answer depends on recent or changing information, even if the user does not name Perplexity or web search. Prefer perplexity_ask_v2 for focused work, perplexity_research_v2 for broad investigations, and the detached task tools only when work must survive the caller or run concurrently.
metadata:
  version: "3.0.0"
---

# Perplexity Search

Use the connected `perplexity-mcp` server as the canonical interface. Call the MCP tools directly; do not construct REST requests or use the deprecated MCP aliases for ordinary work.

## Select a tool

| Need | Tool | Notes |
|---|---|---|
| Focused current answer, news, fact check, comparison, or cited lookup | `perplexity_ask_v2` | Returns a complete answer and sources |
| Broad investigation, many subtopics, or report-like synthesis | `perplexity_research_v2` | Runs Deep Research and may take longer |
| Work that must outlive the caller, or independent concurrent work | `perplexity_task_submit` | Returns a `job_id`; observe it explicitly |
| Observe a detached task | `perplexity_task_status` | Only `state: completed` is a complete answer |
| Explicitly stop a detached task | `perplexity_task_cancel` | Cancellation is not rollback |

Use the first two tools for normal requests. Do not submit a detached task just to make a normal call asynchronous.

The legacy tools `search`, `research`, `perplexity_ask`, `perplexity_search`, `perplexity_reason`, `perplexity_research`, `list_models`, and `toggle_builtin_tools` are deprecated and marked `pending_removal`. Use them only when a caller explicitly requires compatibility with an older server.

## Standard MCP workflow

1. Decide between focused Ask and broad Research from the requested scope, not only from words such as "search" or "research".
2. Put the date range, comparison dimensions, constraints, desired evidence, and output shape in the first query.
3. Call the selected v2 tool with only the current user request.
4. Check that the result has `status: "ok"` before using it.
5. Read the answer from `data.answer` and preserve `data.sources` as direct URLs in the final response. Separate sourced facts from your own synthesis.
6. If a concrete gap remains, continue the same tool with the returned top-level `session_id` and send only the latest focused instruction. Use at most one or two useful continuations.

Example focused call:

```json
{
  "query": "What changed in Python packaging this month? Cite primary sources and include exact release dates."
}
```

Call that payload through `perplexity_ask_v2`.

Example broad call:

```json
{
  "query": "Research the 2026 enterprise AI agent market. Compare adoption, pricing, security constraints, and primary-source evidence; return a structured report."
}
```

Call that payload through `perplexity_research_v2`.

## Models and thinking

- For `perplexity_ask_v2`, omit `model` unless the user requests a specific model. Omission selects `perplexity-search`.
- When a model is requested, pass the exact OAI model ID exposed by this server, such as `gpt-5-6-terra`; do not pass old display names such as `gpt-5.6-terra` or `grok-4.6`.
- Set `thinking: true` only when the user wants the selected Ask model's paired thinking variant. It is a boolean, not a reasoning-effort level.
- `perplexity_research_v2` selects `perplexity-deepsearch` itself. Do not pass `model` or `thinking` to it.
- Do not silently switch models when a requested model is unavailable. Report the structured error and let the user choose.

Example model-controlled Ask:

```json
{
  "query": "Analyze the tradeoffs and cite current primary sources.",
  "model": "gpt-5-6-terra",
  "thinking": true
}
```

## Sessions and follow-ups

Both v2 tools create a native session when `session_id` is omitted and return the ID at the top level:

```json
{
  "status": "ok",
  "session_id": "sess_...",
  "model": "perplexity-search",
  "data": {
    "answer": "...",
    "sources": []
  }
}
```

Keep the session ID together with the tool family (`ask` or `research`). For a follow-up:

```json
{
  "query": "Add exact dates and one primary source for each claim.",
  "session_id": "sess_..."
}
```

Reuse the same v2 tool and pass only the new instruction. Start a new session when the topic changes. A session is permanently bound to its first account and has at most one unfinished task; do not assume it can fail over or run concurrent turns. If a supplied session is unknown, expired, or unavailable, report the continuation failure instead of silently starting a new session.

## Files

Pass user-provided attachments through the tool's `files` argument. Do not put file contents in the query and do not invent upload URLs. The server accepts a filename-to-content object or a list of server-visible paths when its allowed roots are configured.

Respect the server limits: at most 10 files, 20 MiB per file, 100 MiB per request, and an allowed file extension. A client-local path is not usable by a remote MCP server unless that path is also available on the server.

## Detached tasks

Use detached tasks only for work that must continue after a caller disconnects, is expected to run for a long time, or consists of genuinely independent concurrent conversations.

Before background or concurrent work, call `get_skill_index`, then read `get_tasks_use`. The guide is the contract for task states, retention, cancellation, and idempotency.

Submit a focused task:

```json
{
  "query": "Explain the current state of WebAssembly component model adoption with primary sources.",
  "model": "perplexity-search",
  "idempotency_key": "stable-client-request-1"
}
```

Submit a broad detached research task by using `model: "perplexity-deepsearch"` and omit `thinking`.

Always retain both the returned `job_id` and `session_id`. Observe without resubmitting:

```json
{
  "job_id": "job_...",
  "wait_seconds": 20,
  "include_output": false
}
```

Use `wait_seconds` from 0 through 30. Fetch `include_output: true` after the task reaches `completed`. A returned `job_id` or `status: "ok"` means admission succeeded, not that the answer is complete. Treat `failed`, `timed_out`, `cancelled`, and `interrupted` as non-success even if a draft is present. Reuse the same `idempotency_key` after a lost receipt; use a new key only for a deliberate new attempt. Use a different session for each concurrent task.

Cancel only when the user or workflow no longer needs the task, then observe until the terminal state. Cancellation can stop local execution but cannot undo upstream work already accepted.

## Errors and output handling

MCP failures are structured as `status: "error"`, with `error_type`, `message`, and sometimes `session_id` or job details. Report the non-secret error type and message. Do not expose bearer tokens, request headers, private configuration, or raw account data.

Do not treat a partial draft from a failed task as a completed answer. Do not retry blindly, change model, or create a replacement session without a concrete reason.

## Shell fallback

Only when the MCP v2 tools are not exposed, use the bundled standard-library CLI from a repository checkout:

```bash
SKILL_DIR="${SKILL_DIR:-$PWD/.agents/skills/perplexity-search}"
python3 "$SKILL_DIR/scripts/cli.py" ask \
  "What changed in Python packaging this month? Cite primary sources."
```

The CLI is a narrower compatibility path for focused Ask, Deep Research, and session continuation. It does not replace the MCP task lifecycle or file contract. Keep real credentials in `MCP_TOKEN` or `PPLX_API_KEY`; never print or commit them. If the CLI cannot connect or authenticate, report that concrete non-secret failure instead of silently switching to another service.
