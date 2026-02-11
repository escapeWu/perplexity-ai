# SOCKS Proxy 数据流分析

> 生成时间：2026-02-11
> 分析模块：`perplexity/config.py`, `perplexity/client.py`, `perplexity/emailnator.py`

## 分析目标

- 功能：SOCKS5 代理在项目中的配置、传递与生效机制
- 入口点：环境变量 `SOCKS_PROXY` → `config.py` → `Client` / `Emailnator`

## 时序图

```mermaid
sequenceDiagram
    participant ENV as 环境变量 / .env 文件
    participant CFG as config.py
    participant POOL as ClientPool (server)
    participant CLI as Client
    participant EMAIL as Emailnator
    participant SESS as curl_cffi.Session
    participant NET as 网络层 (SOCKS5)
    participant PPLX as Perplexity API
    participant ENATOR as Emailnator API

    ENV->>CFG: 加载 SOCKS_PROXY
    CFG->>CFG: dotenv 多路径搜索 .env
    CFG-->>CLI: import SOCKS_PROXY
    CFG-->>EMAIL: import SOCKS_PROXY

    POOL->>CLI: 创建 Client(cookies)
    CLI->>CLI: 解析 proxy_url (去除 #remark)
    CLI->>SESS: Session(proxy=proxy_url, impersonate="chrome")
    SESS->>NET: 所有 HTTP 请求经 SOCKS5 隧道
    NET->>PPLX: GET /api/auth/session
    PPLX-->>NET: 会话信息
    NET-->>SESS: 响应
    SESS-->>CLI: 响应

    CLI->>CLI: search() 调用
    CLI->>SESS: POST /rest/sse/perplexity_ask (SSE)
    SESS->>NET: SOCKS5 隧道
    NET->>PPLX: 搜索请求
    PPLX-->>NET: SSE 流式响应
    NET-->>SESS: 代理转发
    SESS-->>CLI: iter_lines() 逐块返回

    CLI->>EMAIL: Emailnator(cookies)
    EMAIL->>EMAIL: 解析 proxy_url (去除 #remark)
    EMAIL->>SESS: Session(proxy=proxy_url)
    SESS->>NET: SOCKS5 隧道
    NET->>ENATOR: POST /generate-email
    ENATOR-->>NET: 邮箱地址
    NET-->>SESS: 响应
    SESS-->>EMAIL: 响应
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
        STRIP_C["Client.__init__:54<br/>去除 #remark 后缀"]
        STRIP_E["Emailnator.__init__:54<br/>去除 #remark 后缀"]
    end

    subgraph 会话层["会话层 (Session)"]
        SESS_C["Client.session<br/>curl_cffi.requests.Session<br/>proxy=proxy_url<br/>impersonate='chrome'"]
        SESS_E["Emailnator.s<br/>curl_cffi.requests.Session<br/>proxy=proxy_url"]
    end

    subgraph 网络层["网络层 (Network)"]
        SOCKS["SOCKS5 代理服务器"]
    end

    subgraph 目标服务["目标服务 (Targets)"]
        PPLX_AUTH["Perplexity Auth<br/>/api/auth/session<br/>/api/auth/signin/email"]
        PPLX_SEARCH["Perplexity Search<br/>/rest/sse/perplexity_ask"]
        PPLX_UPLOAD["Perplexity Upload<br/>/rest/uploads/create_upload_url"]
        ENATOR_API["Emailnator API<br/>/generate-email<br/>/message-list"]
    end

    ENV --> CONFIG
    DOTENV --> CONFIG
    DOCKER --> ENV
    CONFIG --> STRIP_C
    CONFIG --> STRIP_E
    STRIP_C --> SESS_C
    STRIP_E --> SESS_E
    SESS_C --> SOCKS
    SESS_E --> SOCKS
    SOCKS --> PPLX_AUTH
    SOCKS --> PPLX_SEARCH
    SOCKS --> PPLX_UPLOAD
    SOCKS --> ENATOR_API
```

## 关键节点说明

| 节点 | 文件位置 | 数据变换 |
|------|---------|---------|
| 环境变量加载 | `config.py:16-28` | dotenv 按优先级搜索 `.env` (cwd > 项目根 > `~/.perplexity/`) |
| SOCKS_PROXY 读取 | `config.py:36` | `os.getenv("SOCKS_PROXY", None)` → `Optional[str]` |
| Client 代理解析 | `client.py:51-54` | 去除 URL 中 `#` 后的备注部分，得到纯净 proxy URL |
| Client Session 初始化 | `client.py:60-65` | `curl_cffi.Session(proxy=proxy_url, impersonate="chrome")` |
| Emailnator 代理解析 | `emailnator.py:51-54` | 同 Client，去除 `#remark` |
| Emailnator Session 初始化 | `emailnator.py:57` | `curl_cffi.Session(proxy=proxy_url)` |
| 所有 HTTP 出站请求 | `client.py` / `emailnator.py` 全文 | Session 级别代理，所有 `.get()` / `.post()` 自动走 SOCKS5 |

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

# 2. Client/Emailnator 去除备注
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
| `Emailnator.s` | 是 | Emailnator 所有 API (生成邮箱、收取邮件) |
| `ClientPool` | 间接 | 通过创建 `Client` 实例间接使用代理 |
| Server 层 (`app.py`, `mcp.py`, `oai.py`) | 间接 | 不直接处理代理，通过 `Client` 透传 |

## 设计特点

1. **全局单一配置**：`SOCKS_PROXY` 在 `config.py` 中统一读取，所有消费方 import 同一变量，保证一致性。

2. **Session 级代理**：代理设置在 `curl_cffi.Session` 构造时注入，后续该 Session 的所有请求自动经代理，无需每次请求单独指定。

3. **备注兼容**：支持 `#remark` 后缀格式（常见于代理订阅链接），解析时自动剥离。

4. **可选配置**：`SOCKS_PROXY` 默认为 `None`，不配置时 `proxy=None` 传入 Session，curl_cffi 直连，不影响功能。

5. **浏览器伪装**：`Client` 的 Session 同时启用 `impersonate="chrome"`，代理流量的 TLS 指纹模拟 Chrome 浏览器，降低被目标服务识别为爬虫的风险。
