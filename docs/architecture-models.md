---
type: architecture
scope: module
module: "models"
date: "2026-07-28"
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

> 生成时间：2026-07-28
> 分析模块：`perplexity/config.py`, `perplexity/server/mcp.py`, `perplexity/server/utils.py`

## 模型定义位置

所有模型配置集中在 `perplexity/config.py`，由 `perplexity/server/mcp.py` 的 `list_models` 工具对外暴露。

## 搜索模式模型 (MODEL_MAPPINGS)

| 模式 | 用户传入 model | 内部值 |
|------|--------------|--------|
| `auto` | (默认) | `turbo` |
| `pro` | (默认) | `pplx_pro` |
| `pro` | `sonar-2` | `experimental` |
| `pro` | `sonar`（兼容别名） | `experimental` |
| `pro` | `gpt-5.6-terra` | `gpt56_terra` |
| `pro` | `claude-sonnet-5` | `claude50sonnet` |
| `pro` | `gemini-3.1-pro` | `gemini31pro_high` |
| `pro` | `grok-4.5` | `grok45low` |
| `reasoning` | (默认) | `pplx_reasoning` |
| `reasoning` | `gpt-5.6-terra-thinking` | `gpt56_terra_thinking` |
| `reasoning` | `claude-sonnet-5-thinking` | `claude50sonnetthinking` |
| `reasoning` | `gemini-3.1-pro` | `gemini31pro_high` |
| `reasoning` | `kimi-k3-thinking` | `kimik3thinking` |
| `reasoning` | `glm-5.2` | `glm_5_2` |
| `reasoning` | `grok-4.5-thinking` | `grok45medium` |
| `reasoning` | `nemotron-3-ultra` | `nv_nemotron_3_ultra` |
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

- `gpt-5.6-terra` → `gpt-5-6-terra`
- `gpt-5.6-terra-thinking` → `gpt-5-6-terra-thinking`
- `glm-5.2`（reasoning）→ `glm-5-2-thinking`
- `nemotron-3-ultra`（reasoning）→ `nemotron-3-ultra-thinking`
- GPT-5.6 Sol 与 Claude Opus 5 属于 Max 模型，不在本项目支持列表中
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
