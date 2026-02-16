# Perplexity MCP Server

[![中文文档](https://img.shields.io/badge/docs-中文-blue.svg)](README-zh.md)

An unofficial Python API for Perplexity.ai that exposes search capabilities via MCP (Model Context Protocol) and OpenAI-compatible endpoints. Supports multi-token pools for load balancing, health monitoring, and various search modes.

## Screenshots
**ADMIN Panel**
<img width="2628" height="2052" alt="image" src="https://github.com/user-attachments/assets/997f0ae0-9f76-4d53-ba28-625068b508d1" />

**Log View**
<img width="2616" height="1823" alt="image" src="https://github.com/user-attachments/assets/f6cdd0ad-8266-4e14-846a-99ed1af9dc42" />

**OpenAI Playground**
![img_v3_02u3_eada7873-379e-42c1-bcbf-3c0466a66ffg](https://github.com/user-attachments/assets/29d75f8e-2058-4945-b486-d50b09f140a1)

**MCP Integration**
<img width="1894" height="989" alt="image" src="https://github.com/user-attachments/assets/4a495432-8305-4820-8b4a-d7e54986ba45" />

## Changelog
+ **2026-02-16**: Added global incognito toggle — force all queries to run in incognito mode via Admin UI or API.
+ **2026-02-01**: Added automatic fallback mechanism (downgrades to anonymous mode when tokens fail); added real-time log viewing.
+ **2026-01-19**: Added SKILL support (`.claude/skills/perplexity-search`).
+ **2026-01-16**: Refactored project structure; added OpenAI endpoint adaptation.
+ **2026-01-13**: Added heartbeat detection to monitor token health periodically and send notifications via Telegram.
+ **2026-01-03**: Added WebUI control.
+ **2026-01-02**: Added multi-token pool support with dynamic management (list/add/remove).
+ **2026-01-02**: MCP responses now include a `sources` field with search result links.
+ **2025-12-31**: Added health check endpoint: `http://127.0.0.1:8000/health`.

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

#### Heartbeat Configuration (Optional)

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
      # - SOCKS_PROXY=${SOCKS_PROXY:-}
    volumes:
      # 挂载 token 池配置文件
      - ./token_pool_config.json:/app/token_pool_config.json
    restart: unless-stopped
```

#### .env Variables

```bash
MCP_PORT=8000
MCP_TOKEN=sk-123456
PPLX_ADMIN_TOKEN=your-admin-token
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

## OpenAI Compatible Endpoints

**Base URL:** `http://127.0.0.1:8000/v1`
**Authorization:** `Bearer <MCP_TOKEN>`

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
    "model": "perplexity-reasoning",
    "messages": [{"role": "user", "content": "Analyze AI trends"}],
    "stream": true
  }'
```

### Supported Models

| Model ID | Mode | Description |
|----------|------|-------------|
| **Search Mode (Pro)** | | |
| `perplexity-search` | pro | Default search model |
| `sonar-search` | pro | Sonar model |
| `gpt-5-2-search` | pro | GPT-5.2 |
| `claude-4-5-sonnet-search` | pro | Claude 4.5 Sonnet |
| `grok-4-1-search` | pro | Grok 4.1 |
| **Reasoning Mode** | | |
| `perplexity-reasoning` | reasoning | Default reasoning model |
| `gpt-5-2-thinking-reasoning` | reasoning | GPT-5.2 Thinking |
| `claude-4-5-sonnet-thinking-reasoning` | reasoning | Claude 4.5 Sonnet Thinking |
| `gemini-3-0-pro-reasoning` | reasoning | Gemini 3.0 Pro |
| `kimi-k2-thinking-reasoning` | reasoning | Kimi K2 Thinking |
| `grok-4-1-reasoning-reasoning` | reasoning | Grok 4.1 Reasoning |
| **Deep Research Mode** | | |
| `perplexity-deepsearch` | deep research | Deep research model |

### Client Configuration (e.g., ChatBox)

1. Settings → AI Provider → Add Custom Provider
2. Fill in:
   - API Host: `http://127.0.0.1:8000`
   - API Key: `sk-123456`
3. Select model: `perplexity-search` or `perplexity-reasoning`

## Project Structure

```
perplexity/
├── server/                  # MCP Server module
│   ├── __init__.py
│   ├── main.py              # Entry point
│   ├── app.py               # FastMCP app, auth, core logic
│   ├── mcp.py               # MCP tools
│   ├── oai.py               # OpenAI compatible API
│   ├── admin.py             # Admin endpoints
│   ├── utils.py             # Server utils
│   ├── client_pool.py       # Multi-account pool
│   └── web/                 # Web UI (React + Vite)
├── client.py                # Low-level API client
├── config.py                # Config constants
├── exceptions.py            # Custom exceptions
├── logger.py                # Logging config
└── utils.py                 # General utils
```

## Claude Code Integration

Skills are located in `.claude/commands/pp/`.

Usage:
- `/pp:query <question>` - Quick search
- `/pp:reasoning <question>` - Reasoning mode
- `/pp:research <question>` - Deep research

## Upstream Project
https://github.com/helallao/perplexity-ai
