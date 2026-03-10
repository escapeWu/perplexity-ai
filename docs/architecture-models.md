---
type: architecture
scope: module
module: "models"
date: "2026-03-10"
keywords:
  - 模型列表
  - MODEL_MAPPINGS
  - LABS_MODELS
  - 搜索模式
  - 模型映射
tech_stack:
  - Python
  - Perplexity AI
---

# 模型列表分析

> 生成时间：2026-03-10
> 分析模块：`perplexity/config.py`, `perplexity/server/mcp.py`, `perplexity/server/utils.py`

## 模型定义位置

所有模型配置集中在 `perplexity/config.py`，由 `perplexity/server/mcp.py` 的 `list_models` 工具对外暴露。

## 搜索模式模型 (MODEL_MAPPINGS)

| 模式 | 用户传入 model | 内部值 |
|------|--------------|--------|
| `auto` | (默认) | `turbo` |
| `pro` | (默认) | `pplx_pro` |
| `pro` | `sonar` | `experimental` |
| `pro` | `gpt-5.4` | `gpt54` |
| `pro` | `claude-4.6-sonnet` | `claude46sonnet` |
| `pro` | `gemini-3.1-pro` | `gemini31pro_high` |
| `reasoning` | (默认) | `pplx_reasoning` |
| `reasoning` | `gpt-5.4-thinking` | `gpt54_thinking` |
| `reasoning` | `claude-4.6-sonnet-thinking` | `claude46sonnetthinking` |
| `reasoning` | `gemini-3.1-pro` | `gemini31pro_high` |
| `reasoning` | `kimi-k2-thinking` | `kimik2thinking` |
| `deep research` | (默认，不可指定) | `pplx_alpha` |

## Labs 模型 (LABS_MODELS)

通过独立 Labs API 调用，不走 MODEL_MAPPINGS：

- `r1-1776`
- `sonar-pro`
- `sonar`
- `sonar-reasoning-pro`
- `sonar-reasoning`

## OpenAI 兼容模型 ID

OpenAI 兼容层不会维护单独的模型名单，而是直接从 `MODEL_MAPPINGS` 派生：

- `gpt-5.4` → `gpt-5-4`
- `gpt-5.4-thinking` → `gpt-5-4-thinking`
- `grok-4.1` / `grok-4.1-reasoning` 已不再暴露
- 默认模型仍然映射为 `perplexity-search` / `perplexity-thinking` / `perplexity-deepsearch`

相关实现位于 `perplexity/server/utils.py`：

- `sanitize_oai_model_name()`：将点号转换为连字符
- `_oai_id()`：生成 OAI 风格模型 ID
- `generate_oai_models()`：生成 `/v1/models` 列表
- `parse_oai_model()`：将 OAI 模型 ID 反解析回 `(mode, model)`

## 工具层约束

| 工具 | 允许模式 | model 限制 |
|------|---------|-----------|
| `search` | `auto`, `pro` | 按 MODEL_MAPPINGS 映射 |
| `research` | `reasoning`, `deep research` | `deep research` 强制 `model=None` |
