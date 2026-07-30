# SOCKS Proxy 数据流分析

> 生成时间：2026-02-11
> 分析模块：`perplexity/config.py`, `perplexity/client.py`, `perplexity/server/client_pool.py`

## 分析目标

- 功能：SOCKS5 代理在项目中的配置、传递与生效机制
- 入口点：环境变量 `SOCKS_PROXY` → `config.py` → `Client` / Telegram 通知

## 时序图

```mermaid
sequenceDiagram
    participant ENV as 环境变量 / .env 文件
    participant CFG as config.py
    participant POOL as ClientPool (server)
    participant CLI as Client
    participant CURL as curl_cffi.Session
    participant AIO as aiohttp.ClientSession
    participant NET as 网络层 (SOCKS5)
    participant PPLX as Perplexity API
    participant TG as Telegram API

    ENV->>CFG: 加载 SOCKS_PROXY
    CFG->>CFG: dotenv 多路径搜索 .env
    CFG-->>CLI: import SOCKS_PROXY
    CFG-->>POOL: import SOCKS_PROXY

    POOL->>CLI: 创建 Client(cookies)
    CLI->>CLI: 解析 proxy_url (去除 #remark)
    CLI->>CURL: Session(proxy=proxy_url, impersonate="chrome")
    CURL->>NET: 所有 HTTP 请求经 SOCKS5 隧道
    NET->>PPLX: GET /api/auth/session
    PPLX-->>NET: 会话信息
    NET-->>CURL: 响应
    CURL-->>CLI: 响应

    CLI->>CLI: search() 调用
    CLI->>CURL: POST /rest/sse/perplexity_ask (SSE)
    CURL->>NET: SOCKS5 隧道
    NET->>PPLX: 搜索请求
    PPLX-->>NET: SSE 流式响应
    NET-->>CURL: 代理转发
    CURL-->>CLI: iter_lines() 逐块返回

    POOL->>POOL: 心跳发现账号状态变化
    POOL->>AIO: ClientSession(ProxyConnector)
    AIO->>NET: SOCKS5 隧道
    NET->>TG: POST /sendMessage
    TG-->>NET: 通知结果
    NET-->>AIO: 响应
```

## 数据流图

```mermaid
flowchart TB
    subgraph 配置层["配置层 (Configuration)"]
        ENV["SOCKS_PROXY 环境变量<br/>格式: socks5://[user:pass@]host:port[#remark]"]
        DOTENV[".env 文件<br/>(cwd / 项目根 / ~/.perplexity/)"]
        DOCKER["docker-compose.yml<br/>环境变量透传"]
    end

    subgraph 解析层["解析层 (Parsing)"]
        CONFIG["config.py:36<br/>SOCKS_PROXY = os.getenv()"]
        STRIP_C["Client.__init__<br/>去除 #remark 后缀"]
        STRIP_T["ClientPool Telegram 通知<br/>去除 #remark 后缀"]
    end

    subgraph 会话层["会话层 (Session)"]
        SESS_C["Client.session<br/>curl_cffi.requests.Session<br/>proxy=proxy_url<br/>impersonate='chrome'"]
        SESS_T["Telegram notifier<br/>aiohttp.ClientSession<br/>ProxyConnector.from_url(proxy_url)"]
    end

    subgraph 网络层["网络层 (Network)"]
        SOCKS["SOCKS5 代理服务器"]
    end

    subgraph 目标服务["目标服务 (Targets)"]
        PPLX_AUTH["Perplexity Auth<br/>/api/auth/session"]
        PPLX_SEARCH["Perplexity Search<br/>/rest/sse/perplexity_ask"]
        PPLX_UPLOAD["Perplexity Upload<br/>/rest/uploads/create_upload_url"]
        TG_API["Telegram API<br/>/sendMessage"]
    end

    ENV --> CONFIG
    DOTENV --> CONFIG
    DOCKER --> ENV
    CONFIG --> STRIP_C
    CONFIG --> STRIP_T
    STRIP_C --> SESS_C
    STRIP_T --> SESS_T
    SESS_C --> SOCKS
    SESS_T --> SOCKS
    SOCKS --> PPLX_AUTH
    SOCKS --> PPLX_SEARCH
    SOCKS --> PPLX_UPLOAD
    SOCKS --> TG_API
```

## 关键节点说明

| 节点 | 文件位置 | 数据变换 |
|------|---------|---------|
| 环境变量加载 | `config.py:16-28` | dotenv 按优先级搜索 `.env` (cwd > 项目根 > `~/.perplexity/`) |
| SOCKS_PROXY 读取 | `config.py` | `os.getenv("SOCKS_PROXY", None)` → `Optional[str]` |
| Client 代理解析 | `Client.__init__` | 去除 URL 中 `#` 后的备注部分，得到纯净 proxy URL |
| Client Session 初始化 | `Client.__init__` | `curl_cffi.Session(proxy=proxy_url, impersonate="chrome")` |
| Telegram 代理解析 | `ClientPool._send_telegram_notification` | 去除 `#remark` 后创建 `aiohttp_socks.ProxyConnector` |
| HTTP 出站请求 | `client.py` / `client_pool.py` | 搜索与可选 Telegram 通知均使用对应 Session 的代理配置 |

## 数据模型

### 输入结构

```
SOCKS_PROXY 环境变量格式:
  socks5://127.0.0.1:1080
  socks5://user:pass@127.0.0.1:1080
  socks5://user:pass@127.0.0.1:1080#my-proxy-remark
```

### 内部处理

```python
# 1. config.py 原样读取
SOCKS_PROXY: Optional[str] = os.getenv("SOCKS_PROXY", None)
# 结果: "socks5://user:pass@127.0.0.1:1080#my-proxy-remark" 或 None

# 2. Client/Telegram 通知去除备注
proxy_url = SOCKS_PROXY.split("#")[0] if "#" in SOCKS_PROXY else SOCKS_PROXY
# 结果: "socks5://user:pass@127.0.0.1:1080"

# 3. 传入 curl_cffi Session
session = requests.Session(proxy=proxy_url)
# curl_cffi 内部建立 SOCKS5 隧道，所有请求经代理转发
```

### 代理覆盖范围

| 组件 | 代理生效 | 目标服务 |
|------|---------|---------|
| `Client.session` | 是 | Perplexity AI 所有 API (认证、搜索、文件上传) |
| `ClientPool` | 间接 | 通过创建 `Client` 实例间接使用代理 |
| Telegram 通知 | 是 | 配置 Telegram 心跳通知时，通过 `aiohttp_socks` 访问 Telegram API |
| Server 层 (`app.py`, `mcp.py`, `oai.py`) | 间接 | 不直接处理代理，通过 `Client` 透传 |

## 设计特点

1. **全局单一配置**：`SOCKS_PROXY` 在 `config.py` 中统一读取，所有消费方 import 同一变量，保证一致性。

2. **Session 级代理**：代理设置在 `curl_cffi.Session` 构造时注入，后续该 Session 的所有请求自动经代理，无需每次请求单独指定。

3. **备注兼容**：支持 `#remark` 后缀格式（常见于代理订阅链接），解析时自动剥离。

4. **可选配置**：`SOCKS_PROXY` 默认为 `None`，不配置时 `proxy=None` 传入 Session，curl_cffi 直连，不影响功能。

5. **浏览器伪装**：`Client` 的 Session 同时启用 `impersonate="chrome"`，代理流量的 TLS 指纹模拟 Chrome 浏览器，降低被目标服务识别为爬虫的风险。
