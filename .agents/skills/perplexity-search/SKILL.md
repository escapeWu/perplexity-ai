---
name: perplexity-search
description: Use the self-hosted escapeWu/perplexity-ai backend for current web search, cited answers, model-selectable thinking, deep research, file analysis, or session-aware follow-up through its OpenAI-compatible REST API or MCP v2 tools. Trigger when Codex must call GET /v1/models, POST /v1/chat/completions, perplexity_ask_v2, or perplexity_research_v2, choose a current model ID, or continue a returned session_id.
---

# Perplexity Search

把本服务视为 `escapeWu/perplexity-ai` 的自托管代理，而不是 Perplexity 官方 API。
统一使用服务返回的 OAI 模型 ID，不要使用内部 ID（如 `gpt56_terra`）或官方 Sonar API 的模型名。

## 选择调用面

- MCP 客户端已连接本服务时，优先调用 `perplexity_ask_v2` 或 `perplexity_research_v2`。
- 编写程序、集成 OpenAI SDK、需要流式响应、上传文件或发现模型时，使用 REST API。
- 需要模型清单时调用认证后的 `GET /v1/models`；不要依赖硬编码清单或已弃用的 MCP `list_models`。
- 普通搜索、事实核查和可选推理使用 Ask；真正的长耗时综合调研使用 Research。

## 认证与地址

REST 默认地址：

```text
http://127.0.0.1:8000/v1
```

MCP Streamable HTTP 地址：

```text
http://127.0.0.1:8000/mcp
```

两种调用都使用相同认证头：

```http
Authorization: Bearer <MCP_TOKEN>
```

不要打印、记录或提交真实 `MCP_TOKEN`。

## 模型发现与选择

先查询当前账户实际可见的模型：

```bash
curl -sS "${PPLX_BASE_URL:-http://127.0.0.1:8000}/v1/models" \
  -H "Authorization: Bearer ${MCP_TOKEN}"
```

响应为 `{"object":"list","data":[...]}`。从 `data[].id` 选模型，并结合
`subscription_tier`、`mode`、`label` 和 `description` 判断能力。模型会按账号的 Pro/Max
层级动态过滤。

当前常用 ID 包括：

| 用途 | 基础模型 ID | Thinking ID |
|---|---|---|
| 默认搜索 | `perplexity-search` | `perplexity-thinking` |
| GPT | `gpt-5-6-terra` | `gpt-5-6-terra-thinking` |
| Claude | `claude-sonnet-5` | `claude-sonnet-5-thinking` |
| Gemini | `gemini-3-7-flash` | `gemini-3-7-flash-thinking` |
| Grok | `grok-4-6` | `grok-4-6-thinking` |
| Deep Research | `perplexity-deepsearch` | 不适用 |

`gpt-5-6-sol`、`gpt-5-6-sol-thinking`、`claude-opus-5` 和
`claude-opus-5-thinking` 仅对兼容的 Max 账户可见。`sonar-2` 没有 Thinking 配对模型。
表格只用于快速参考；始终以 `/v1/models` 的实时结果为准。

## REST API

### 非流式 Ask/Search

显式传入 `stream: false` 以获得单个 JSON 响应。使用基础模型配合 `thinking: true`
时，服务会选择该模型的 Thinking 配对版本：

```bash
curl -sS "${PPLX_BASE_URL:-http://127.0.0.1:8000}/v1/chat/completions" \
  -H "Authorization: Bearer ${MCP_TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{
    "model": "gpt-5-6-terra",
    "thinking": true,
    "stream": false,
    "messages": [
      {"role": "user", "content": "核对今天最重要的 AI 新闻并给出来源"}
    ]
  }'
```

读取以下字段：

- `choices[0].message.content`：答案。
- `sources`：来源列表。
- `model`：实际生效的 OAI 模型 ID。
- `session_id`：后续续聊使用的会话 ID。

请求规则：

- 必须传非空 `model` 和至少一个 `role: "user"` 的消息。
- `stream` 默认是 `true`；需要普通 JSON 时始终显式设为 `false`。
- `thinking` 必须是布尔值。基础模型没有配对版本时，`thinking: true` 会返回 400。
- 不要传 `reasoning_effort`。该字段会返回 400；使用 `thinking: true`。
- 新会话可携带 system/user/assistant 初始历史；服务会把初始历史合并为首轮上游请求。

### Deep Research

使用 `perplexity-deepsearch` 发起 REST Deep Research：

```json
{
  "model": "perplexity-deepsearch",
  "stream": false,
  "messages": [
    {"role": "user", "content": "调研主题、约束、时间范围和期望输出"}
  ]
}
```

不要为 Deep Research 传 `thinking` 或其他基础模型 ID。

### 持续对话

保存首轮响应的 `session_id`，并在后续请求中原样传回：

```json
{
  "model": "gpt-5-6-terra",
  "thinking": true,
  "stream": false,
  "session_id": "sess_...",
  "messages": [
    {"role": "user", "content": "继续比较第二个方案"}
  ]
}
```

续聊只把最新的 user turn 发送给上游；不要重复发送整段历史。会话会固定到首轮选中的
账户并复用 Perplexity 原生线程。未知或失效的 ID 返回 404。继续使用同一服务实例和
会话数据库；API/MCP 会话不会显示在 WebUI 侧边栏。

### 流式响应

省略 `stream` 或传 `true` 以接收 SSE：

- 从 `choices[0].delta.content` 累积正文。
- 从响应头 `X-Session-ID` 或每个 chunk 的 `session_id` 保存会话。
- 从最终 chunk 读取 `sources` 和 `finish_reason: "stop"`。
- 收到 `data: [DONE]` 后结束。
- 若需阶段进度，传 `"perplexity": {"include_progress": true}`。
- 若 chunk 的 `finish_reason` 为 `error`，读取同一 chunk 的 `error` 对象。

只有已完整提交的流式轮次才能用于后续续聊；客户端中断的轮次不会持久化。

### 文件

上传文件并取得进程内有效的 `file_id`：

```bash
curl -sS "${PPLX_BASE_URL:-http://127.0.0.1:8000}/v1/files" \
  -H "Authorization: Bearer ${MCP_TOKEN}" \
  -F "purpose=assistants" \
  -F "file=@./report.pdf"
```

在消息 content 中引用文件：

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "分析这份报告并核对关键数字"},
    {"type": "input_file", "file_id": "file-..."}
  ]
}
```

`input_file` 也支持 `file_data` 加 `filename` 的 base64 内联内容，或可下载的
`file_url`。文件 ID 仅在当前服务进程生命周期内有效。仅在用户明确要求时调用
`DELETE /v1/files/{file_id}`。

## MCP v2

使用如下客户端配置连接：

```json
{
  "mcpServers": {
    "perplexity": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_TOKEN>"
      }
    }
  }
}
```

### `perplexity_ask_v2`

使用与 `/v1/models` 完全一致的 OAI 模型 ID：

```json
{
  "query": "核对该说法并附来源",
  "model": "gpt-5-6-terra",
  "thinking": true,
  "session_id": null,
  "files": null
}
```

- 省略 `model` 时默认使用 `perplexity-search`。
- 传 `thinking: true` 时选择配对的 Thinking 模型。
- 不要把 `perplexity-deepsearch` 传给此工具。
- `files` 可为 `filename -> data` 字典或服务端可读取的文件路径数组；远程 MCP
  客户端不要把本机路径误当成服务器路径。

成功结果：

```json
{
  "status": "ok",
  "session_id": "sess_...",
  "model": "gpt-5-6-terra-thinking",
  "data": {"answer": "...", "sources": []}
}
```

### `perplexity_research_v2`

仅用于 Deep Research：

```json
{
  "query": "完成多来源深度调研并给出结论",
  "session_id": null,
  "files": null
}
```

该工具固定使用 `perplexity-deepsearch`，不接受 `model`、`thinking` 或
`reasoning_effort`。

### MCP 持续对话与错误

从成功结果顶层保存 `session_id`，后续调用同一个 v2 工具时传回该 ID。不要自行构造
或修改 ID。错误结果形如：

```json
{
  "status": "error",
  "error_type": "ValidationError",
  "message": "...",
  "session_id": "sess_..."
}
```

未知会话的 `error_type` 为 `SessionNotFound`。会话仍绑定原账户；绑定账户不可用时，
不要偷偷创建新会话，先向用户说明续聊暂时不可用。

## 旧 MCP 工具迁移

不要在新调用中使用以下已标记 `deprecated` / `pending_removal` 的工具：

- `list_models`：改用 REST `GET /v1/models`。
- `search`、`perplexity_ask`、`perplexity_search`、`perplexity_reason`：改用
  `perplexity_ask_v2`。
- `research`、`perplexity_research`：改用 `perplexity_research_v2`。
- `toggle_builtin_tools`：不要依赖；没有 v2 替代项。

## 执行检查

1. 先确认调用面、Base URL 和认证方式。
2. 需要指定模型时先读取 `/v1/models`，再使用返回的完整 ID。
3. 普通检索使用 Ask；需要更强推理时使用基础模型加 `thinking: true`；深度调研使用 Research。
4. 首轮保存 `session_id`；只有用户需要续聊时才在下一轮传回。
5. 返回答案时保留来源链接，并明确区分上游事实、模型推断和调用错误。
