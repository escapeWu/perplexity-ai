# Thanks for [LINUX DO](https://linux.do/)

# Perplexity MCP Server

[![中文文档](https://img.shields.io/badge/docs-中文-blue.svg)](README-zh.md)

An unofficial Perplexity.ai server that exposes search capabilities through MCP (Model Context Protocol) and OpenAI-compatible endpoints. Supports multi-token pools for load balancing, health monitoring, and various search modes.

## Screenshots
**ADMIN Panel**
`https://yourdomain.com/admin/`
<img width="2628" height="2052" alt="image" src="https://github.com/user-attachments/assets/997f0ae0-9f76-4d53-ba28-625068b508d1" />

**OpenAI Playground**
`https://yourdomain.com/playground/`
![OpenAI Playground with persistent native follow-up conversations](docs/images/openai-playground-native-sessions.png)

## Getting Started

### Docker Compose Deployment

#### 1. Prepare Configuration

Copy and edit the configuration file:

```bash
cp token_pool_config-example.json token_pool_config.json
```

Edit `token_pool_config.json` with your Perplexity account tokens:

```json
{
  "heart_beat": {
    "enable": true,
    "question": "What is the date today?",
    "interval": 6,
    "tg_bot_token": "your-telegram-bot-token",
    "tg_chat_id": "your-telegram-chat-id"
  },
  "fallback": {
    "fallback_to_auto": true
  },
  "incognito": {
    "enabled": false
  },
  "tokens": [
    {
      "id": "account1@example.com",
      "csrf_token": "your-csrf-token-1",
      "session_token": "your-session-token-1"
    },
    {
      "id": "account2@example.com",
      "csrf_token": "your-csrf-token-2",
      "session_token": "your-session-token-2"
    }
  ]
}
```

> **How to get tokens:** Open perplexity.ai -> F12 Developer Tools -> Application -> Cookies
> - `csrf_token` corresponds to `next-auth.csrf-token`
> - `session_token` corresponds to `__Secure-next-auth.session-token`

#### Heartbeat Configuration (Recommand, handle cookie expire!)

Periodically checks token health and notifies via Telegram:

| Option | Description |
|--------|-------------|
| `enable` | Enable heartbeat checks |
| `question` | Question used for testing |
| `interval` | Check interval (in hours) |
| `tg_bot_token` | Telegram Bot Token |
| `tg_chat_id` | Telegram Chat ID |

#### Fallback Configuration (Optional)

Automatically downgrades to anonymous Auto mode when all tokens are unavailable:

| Option | Description |
|--------|-------------|
| `fallback_to_auto` | Enable fallback to anonymous mode (default `true`) |

#### Incognito Configuration (Optional)

When enabled, forces all queries (MCP and OpenAI endpoints) to run in incognito mode, preventing search history from being saved on Perplexity accounts:

| Option | Description |
|--------|-------------|
| `enabled` | Force incognito mode for all queries (default `false`) |

> Can also be toggled at runtime via the Admin UI or `POST /incognito/config` API.

#### 2. Start the Service

```bash
# Create .env file (optional)
cp .env.example .env

# Start services
docker compose up -d
```

#### docker-compose.yml Example

```yml
services:
  perplexity-mcp:
    image: shancw/perplexity-mcp:latest
    container_name: perplexity-mcp
    ports:
      - "${MCP_PORT:-8000}:8000"
    environment:
      - MCP_TOKEN=${MCP_TOKEN:-sk-123456}
      - PPLX_ADMIN_TOKEN=${PPLX_ADMIN_TOKEN:-}
      # - PPLX_WEBUI_SESSION_DB=/app/data/webui_sessions.sqlite3
      # - SOCKS_PROXY=${SOCKS_PROXY:-}
    volumes:
      # Mount the token pool and persistent daily model cache
      - ./token_pool_config.json:/app/token_pool_config.json
      - ./data:/app/data
    restart: unless-stopped
```

#### .env Variables

```bash
MCP_PORT=8000
MCP_TOKEN=sk-123456
PPLX_ADMIN_TOKEN=your-admin-token
# PPLX_WEBUI_SESSION_DB=./data/webui_sessions.sqlite3
# Optional outside Docker:
# PPLX_MODELS_CONFIG_URL=https://raw.githubusercontent.com/escapeWu/perplexity-ai/main/catalog/model_config_v2.json
# PPLX_MODEL_CACHE_PATH=./data/model_config_v2.json
# PPLX_MODEL_CACHE_TTL=86400
```

## Multi-Token Pool (Load Balancing)

Configure multiple Perplexity account tokens to enable load balancing and high availability. See the "Prepare Configuration" section above for the JSON structure.


## MCP Configuration

```json
{
  "mcpServers": {
    "perplexity": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer sk-123456"
      }
    }
  }
}
```

### MCP Tools

| Tool | When to use |
|------|-------------|
| `perplexity_ask` | Quick general questions using low-cost auto mode |
| `perplexity_search` | Current web search with Pro mode and web sources |
| `perplexity_reason` | Multi-step reasoning with the default reasoning model |
| `perplexity_research` | Slower, comprehensive deep research |
| `search` | Parameterized auto/pro search with model, source, language, file, and fallback controls |
| `research` | Parameterized reasoning/deep research with model, source, language, file, and fallback controls |
| `list_models` | Inspect supported modes and model mappings |

## OpenAI Compatible Endpoints

**Base URL:** `http://127.0.0.1:8000/v1`
**Authorization:** `Bearer <MCP_TOKEN>`

Chat completions stream live upstream events by default. Pass `"stream": false`
to wait for a complete JSON response. The Playground also requests optional
Perplexity progress chunks so it can display analysis, web search, source review,
and answer-writing stages. Other OpenAI clients can opt in with
`"perplexity": {"include_progress": true}`; the extension is disabled by default
for API compatibility.

### Examples

#### List Models
```bash
curl http://127.0.0.1:8000/v1/models -H "Authorization: Bearer sk-123456"
```

#### Chat Completions (Non-streaming)
```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-123456" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "perplexity-search",
    "messages": [{"role": "user", "content": "How is the weather today?"}],
    "stream": false
  }'
```

#### Chat Completions (Streaming)
```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-123456" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "perplexity-thinking",
    "messages": [{"role": "user", "content": "Analyze AI trends"}],
    "perplexity": {"include_progress": true}
  }'
```

Progress updates remain regular `chat.completion.chunk` events with an empty
content delta and an additional `perplexity_progress` field. Clients that do not
understand the extension can leave it disabled.

### Supported Models

The repository publishes a validated Perplexity v2 model snapshot at
`catalog/model_config_v2.json`. Servers fetch that snapshot from GitHub Raw
every 24 hours and persist a local cache. `/v1/models`, MCP `list_models`,
validation, and upstream `model_preference` routing all use that same catalog.

- Pro accounts expose Pro models.
- Max accounts expose both Pro and Max models.
- Max-only requests are routed only to Max accounts.
- Browser-agent entries are excluded because they do not use the search API.
- `perplexity-search`, `perplexity-thinking`, and `perplexity-deepsearch`
  remain stable default IDs. Use `GET /v1/models` for the current full list.

If the daily refresh fails, the last valid on-disk catalog remains active.
Static built-in mappings are used only when no valid cache exists.

## Star History

<a href="https://www.star-history.com/?type=date&repos=escapeWu%2Fperplexity-ai">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=escapeWu/perplexity-ai&type=date&theme=dark&legend=top-left&sealed_token=rp3Vi8ZSB1OEa331-tOQMgrr5wv-1nwAH-1AG_dSGwbIazYZebUsvw3naomkRhFRbGZ47UUwNWiRarYYr4sV7nvIJsi1k-IBJVVUF9zUN6AgkQMp_dLulw" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=escapeWu/perplexity-ai&type=date&legend=top-left&sealed_token=rp3Vi8ZSB1OEa331-tOQMgrr5wv-1nwAH-1AG_dSGwbIazYZebUsvw3naomkRhFRbGZ47UUwNWiRarYYr4sV7nvIJsi1k-IBJVVUF9zUN6AgkQMp_dLulw" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=escapeWu/perplexity-ai&type=date&legend=top-left&sealed_token=rp3Vi8ZSB1OEa331-tOQMgrr5wv-1nwAH-1AG_dSGwbIazYZebUsvw3naomkRhFRbGZ47UUwNWiRarYYr4sV7nvIJsi1k-IBJVVUF9zUN6AgkQMp_dLulw" />
 </picture>
</a>

## What's New
+ **2026-08-13**: v1.14.0 — Add server-backed Playground conversations with a responsive session sidebar, native Perplexity follow-up threads, persistent history, and immutable per-conversation account binding without cross-account failover.
+ **2026-08-12**: v1.13.3 — Upgrade curl-cffi browser fingerprints to stop Grok 4.5 and Claude Sonnet 5 requests from silently falling back to Best/turbo, and expose requested-versus-effective model metadata with a server warning when upstream downgrades recur.
+ **2026-07-31**: v1.13.2 — Prevent all explicitly selected models from being silently downgraded by matching Perplexity's current browser request protocol, and publish a validated Pro/Max model snapshot that servers refresh daily from GitHub Raw.
+ **2026-07-30**: v1.13.1 — Restore real-time Playground progress and answer streaming for Perplexity's new block-based response protocol, reconstruct offset Markdown chunks, and deduplicate repeated lifecycle stages.
+ **2026-07-30**: v1.13.0 — Add a daily cached Perplexity model catalog with Pro/Max-aware discovery and account routing, expose live model metadata in the Playground, and remove unused client-side SDK, account automation, Labs, examples, and legacy assets for server-only deployment.
+ **2026-07-29**: v1.12.0 — Add optional structured Perplexity progress events and a live Playground stage timeline, preserve partial output across stream failures and cancellation, and align service requests with the browser `query_source` required by current models.
+ **2026-07-29**: v1.11.0 — Stream OpenAI-compatible chat completions from upstream in real time by default, retain opt-in complete JSON responses with `stream: false`, add WebUI stream mode controls and working cancellation, and harden stream failover and cleanup.
+ **2026-07-29**: v1.10.1 — Close synchronous streaming responses reliably, move user-info network calls outside the pool lock, use starvation-free smooth weighted round-robin scheduling, sync runtime dependencies, and make Playground cancellation abort active requests.
+ **2026-07-28**: v1.10.0 — Add the current non-Max model lineup (Sonar 2, GPT-5.6 Terra, Gemini 3.1 Pro, Claude Sonnet 5, Kimi K3, GLM 5.2, Grok 4.5, and Nemotron 3 Ultra), centralize model mappings, and sync MCP/OpenAI discovery, tests, and docs.

## Upstream Project
https://github.com/helallao/perplexity-ai 
+ fix param lack, auto redirect to GPT-5.6-nano, and add fancy mcp/restapi server 
<img width="745" height="229" alt="image" src="https://github.com/user-attachments/assets/2513e13e-cfc3-49d7-82cd-8dbae20f8991" />
