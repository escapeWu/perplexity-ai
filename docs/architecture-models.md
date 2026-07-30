---
type: architecture
scope: module
module: "models"
date: "2026-07-29"
keywords:
  - 模型列表
  - subscription_tier
  - 动态缓存
  - 模型路由
tech_stack:
  - Python
  - Perplexity AI
---

# 动态模型目录

## 数据源

模型目录来自 Perplexity 公共 GET 接口：

`https://www.perplexity.ai/rest/models/config/v2?version=2.18&source=default`

服务使用 Chrome TLS impersonation 发起请求，不携带账号 Cookie。响应中的
`search_config` 决定前端可选项和 `subscription_tier`，`models` 用于确认内部
模型确实属于 `mode=search`。`mode=browser_agent` 的条目属于另一套协议，
不会暴露给 MCP 或 OpenAI 搜索接口。

## 缓存生命周期

`perplexity/model_registry.py` 是唯一模型目录来源：

1. 启动时读取服务器磁盘缓存；
2. 缓存超过 24 小时时请求公共接口；
3. 新响应通过 schema 和可调用模型校验后，以临时文件 + `os.replace` 原子落盘；
4. 运行期间每小时检查一次过期状态，实际最多每天请求一次；
5. 网络、解析或落盘失败时继续使用上一份有效缓存；
6. 没有有效缓存时使用 `config.py` 的静态保底映射。

默认缓存位于 `.cache/perplexity/model_config_v2.json`。Docker 镜像使用
`/app/data/model_config_v2.json`，Compose 将 `./data` 挂载为持久目录。
可用 `PPLX_MODEL_CACHE_PATH` 和 `PPLX_MODEL_CACHE_TTL` 覆盖。

## Pro / Max 分层

`Client` 在初始化及后续 `/api/auth/session` 请求时读取
`user.subscription_tier`。`ClientWrapper` 缓存该等级，号池按模型要求筛选：

| 模型等级 | 可选账号 |
|---------|---------|
| Pro | Pro、Max |
| Max | 仅 Max |

账号响应缺少等级时，为兼容旧会话可执行 Pro 请求，但绝不执行 Max 请求。
Max 模型不可降级到匿名 Auto，以免返回内容时实际换用了其他模型。

## 对外一致性

以下入口全部读取同一个 `ModelRegistry` 快照：

- MCP `list_models`
- OpenAI `GET /v1/models`
- OpenAI 模型 ID 反解析
- 参数校验
- 上游 `model_preference`
- Playground 模型选择器

`/v1/models` 只返回当前已配置账号能够使用的模型，并额外提供 `label`、
`description`、`subscription_tier` 和 `mode`。Max 账号存在时，Pro 与 Max
模型都会展示；仅有 Pro 账号时不会展示 Max 模型。

默认 OpenAI ID 保持稳定：

- `perplexity-search`
- `perplexity-thinking`
- `perplexity-deepsearch`

具体供应商模型把 MCP 名称中的点号转成连字符；Reasoning 模型统一使用
`-thinking` 结尾。历史 `sonar` 别名仍可请求，但不会在列表中重复展示。
