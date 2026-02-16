# Perplexity MCP Server

[![English Docs](https://img.shields.io/badge/docs-English-blue.svg)](README.md)

非官方的 Perplexity.ai Python API，通过 MCP (Model Context Protocol) 和 OpenAI 兼容端点暴露搜索能力。支持多 Token 池负载均衡、健康监测和多种搜索模式。

## 展示
**ADMIN 管理面板**
<img width="2628" height="2052" alt="image" src="https://github.com/user-attachments/assets/997f0ae0-9f76-4d53-ba28-625068b508d1" />

**日志查看**
<img width="2616" height="1823" alt="image" src="https://github.com/user-attachments/assets/f6cdd0ad-8266-4e14-846a-99ed1af9dc42" />

**OpenAI Playground**
![img_v3_02u3_eada7873-379e-42c1-bcbf-3c0466a66ffg](https://github.com/user-attachments/assets/29d75f8e-2058-4945-b486-d50b09f140a1)

**MCP 集成**
<img width="1894" height="989" alt="image" src="https://github.com/user-attachments/assets/4a495432-8305-4820-8b4a-d7e54986ba45" />

## 更新记录
+ **2026-02-16**：新增全局隐身模式开关，可通过管理面板或 API 强制所有查询使用隐身模式
+ **2026-02-01**：新增自动回退机制，当 Token 失效时自动降级到匿名模式；新增实时日志查看
+ **2026-01-19**：增加 SKILL 支持，位于 `.claude/skills/perplexity-search`
+ **2026-01-16**：重构项目结构，增加 OpenAI 端点适配
+ **2026-01-13**：新增心跳检测功能，支持定时检测 token 健康状态并通过 Telegram 通知
+ **2026-01-03**：增加 WebUI 控制
+ **2026-01-02**：新增多 token 池支持，支持动态管理号池（列举/新增/删除）
+ **2026-01-02**：MCP 响应现在包含 `sources` 字段，返回搜索结果的来源链接
+ **2025-12-31**：增加健康检查 endpoint: `http://127.0.0.1:8000/health`

## 快速开始

### Docker Compose 一键部署

#### 1. 准备配置文件

从示例文件复制并编辑 `token_pool_config.json`：

```bash
# 复制示例配置文件
cp token_pool_config-example.json token_pool_config.json
```

编辑 `token_pool_config.json`，填入你的 Perplexity 账户 token：

```json
{
  "heart_beat": {
    "enable": true,
    "question": "今天是几号？",
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

> **获取 Token 的方法：** 打开 perplexity.ai -> F12 开发者工具 -> Application -> Cookies
> - `csrf_token` 对应 `next-auth.csrf-token`
> - `session_token` 对应 `__Secure-next-auth.session-token`

#### 心跳检测配置（可选）

心跳检测功能可以定期检查每个 token 的健康状态，并通过 Telegram 通知结果：

| 配置项 | 说明 |
|--------|------|
| `enable` | 是否启用心跳检测 |
| `question` | 用于检测的测试问题 |
| `interval` | 检测间隔时间（小时） |
| `tg_bot_token` | Telegram Bot Token（用于发送通知） |
| `tg_chat_id` | Telegram Chat ID（接收通知的聊天ID） |

#### 自动回退配置（可选）

当所有配置的 Token 都不可用（如额度耗尽或失效）时，系统可以自动回退到匿名 Auto 模式继续服务：

| 配置项 | 说明 |
|--------|------|
| `fallback_to_auto` | 当所有 token 失败时，是否自动降级到匿名模式 (默认 `true`) |

> 如果不需要此功能，可以在配置文件中将 `fallback_to_auto` 设为 `false`，或者通过 Web UI 进行动态开关。

#### 隐身模式配置（可选）

启用后，所有查询（MCP 和 OpenAI 端点）将强制使用隐身模式，不会在 Perplexity 账户中保存搜索历史：

| 配置项 | 说明 |
|--------|------|
| `enabled` | 强制所有查询使用隐身模式 (默认 `false`) |

> 也可以通过管理面板或 `POST /incognito/config` API 在运行时动态开关。

> 如果不需要心跳检测功能，可以省略 `heart_beat` 配置或将 `enable` 设为 `false`

#### 2. 启动服务

```bash
# 创建 .env 文件（可选）
cp .env.example .env

# 启动服务
docker compose up -d
```

#### docker-compose.yml 配置示例

```yml
services:
  perplexity-mcp:
    image: shancw/perplexity-mcp:latest
    container_name: perplexity-mcp
    ports:
      - "${MCP_PORT:-8000}:8000"
    environment:
      # MCP 认证密钥
      - MCP_TOKEN=${MCP_TOKEN:-sk-123456}
      # 管理员 Token（用于号池管理 API，可选）
      - PPLX_ADMIN_TOKEN=${PPLX_ADMIN_TOKEN:-}
      # SOCKS 代理配置 (可选)
      # 格式: socks5://[user[:pass]@]host[:port][#remark]
      # - SOCKS_PROXY=${SOCKS_PROXY:-}
    volumes:
      # 挂载 token 池配置文件
      - ./token_pool_config.json:/app/token_pool_config.json
    restart: unless-stopped
```

#### .env 环境变量

```bash
# Perplexity MCP Server 环境变量配置
# 复制此文件为 .env 并填入实际值

# ============================================
# MCP 服务配置
# ============================================

# MCP 服务端口
MCP_PORT=8000

# MCP API 认证密钥 (客户端需要在 Authorization header 中携带此密钥)
MCP_TOKEN=sk-123456

# 管理员 Token（用于号池管理 API：新增/删除 token 等操作）
PPLX_ADMIN_TOKEN=your-admin-token
```

## 多 Token 池配置（负载均衡）

支持配置多个 Perplexity 账户 token，实现负载均衡和高可用。具体配置请参考上文 "准备配置文件" 部分。

## MCP 配置

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

## OpenAI 兼容端点

### 使用方式

**Base URL:** `http://127.0.0.1:8000/v1`

**认证:** 在请求头中添加 `Authorization: Bearer <MCP_TOKEN>`

#### 获取模型列表

```bash
curl http://127.0.0.1:8000/v1/models \
  -H "Authorization: Bearer sk-123456"
```

#### 聊天补全（非流式）

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-123456" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "perplexity-search",
    "messages": [{"role": "user", "content": "今天天气怎么样"}],
    "stream": false
  }'
```

#### 聊天补全（流式）

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-123456" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "perplexity-reasoning",
    "messages": [{"role": "user", "content": "分析一下人工智能的发展趋势"}],
    "stream": true
  }'
```

### 支持的模型

| 模型 ID | 模式 | 说明 |
|---------|------|------|
| **Search 模式（Pro）** | | |
| `perplexity-search` | pro | 默认搜索模型 |
| `sonar-search` | pro | Sonar 模型 |
| `gpt-5-2-search` | pro | GPT-5.2 |
| `claude-4-5-sonnet-search` | pro | Claude 4.5 Sonnet |
| `grok-4-1-search` | pro | Grok 4.1 |
| **Reasoning 模式** | | |
| `perplexity-reasoning` | reasoning | 默认推理模型 |
| `gpt-5-2-thinking-reasoning` | reasoning | GPT-5.2 Thinking |
| `claude-4-5-sonnet-thinking-reasoning` | reasoning | Claude 4.5 Sonnet Thinking |
| `gemini-3-0-pro-reasoning` | reasoning | Gemini 3.0 Pro |
| `kimi-k2-thinking-reasoning` | reasoning | Kimi K2 Thinking |
| `grok-4-1-reasoning-reasoning` | reasoning | Grok 4.1 Reasoning |
| **Deep Research 模式** | | |
| `perplexity-deepsearch` | deep research | 深度研究模型 |

### 客户端配置示例

以 ChatBox 为例：

1. 打开设置 → AI 模型提供商 → 添加自定义提供商
2. 填入：
   - API Host: `http://127.0.0.1:8000`
   - API Key: `sk-123456`（与 MCP_TOKEN 一致）
3. 选择模型如 `perplexity-search` 或 `perplexity-reasoning`

## 项目结构

```
perplexity/
├── server/                  # MCP 服务器模块
│   ├── __init__.py          # 包入口，导出主要组件
│   ├── main.py              # 服务启动入口
│   ├── app.py               # FastMCP 应用实例、认证中间件、核心查询逻辑
│   ├── mcp.py               # MCP 工具定义 (list_models, search, research)
│   ├── oai.py               # OpenAI 兼容 API (/v1/models, /v1/chat/completions)
│   ├── admin.py             # 管理端点 (健康检查、号池管理、心跳控制)
│   ├── utils.py             # 服务器专用工具函数 (验证、OAI模型映射)
│   ├── client_pool.py       # 多账户连接池管理
│   └── web/                 # 前端 Web UI (React + Vite)
│       ├── src/
│       │   ├── components/  # 组件
│       │   ├── hooks/       # React Hooks
│       │   ├── lib/
│       │   │   └── api.ts   # API 请求封装
│       │   ├── pages/
│       │   │   └── Playground.tsx  # Playground 页面
│       │   └── index.tsx    # 入口文件
│       └── vite.config.ts   # Vite 配置
├── client.py                # Perplexity API 客户端
├── config.py                # 配置常量
├── exceptions.py            # 自定义异常
├── logger.py                # 日志配置
└── utils.py                 # 通用工具函数 (重试、限流、JSON解析)
```

## 注册为 Claude Code 指令

复制 `.claude/commands/pp/` 目录下创建指令文件：

使用方式：
- `/pp:query 你的问题` - 快速搜索
- `/pp:reasoning 你的问题` - 推理模式，多步思考分析
- `/pp:research 你的问题` - 深度研究，最全面彻底

## 上游项目
https://github.com/helallao/perplexity-ai
