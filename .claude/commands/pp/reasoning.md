---
name: PP: Reasoning
description: Reasoning mode for multi-step thinking and analysis.
category: Perplexity
tags: [perplexity, reasoning, thinking, analysis]
argument-hint: [query]
---

**Overview**
Use Perplexity reasoning mode for multi-step thinking and problem analysis.

**Features**
- Uses reasoning models (default: gemini-3.1-pro)
- Multi-step thinking process
- Good balance between speed and depth
- Suitable for complex questions requiring logical analysis

**Steps**
1. Use `mcp__perplexity-mcp__research` tool with the user's query.
2. Set `mode: "reasoning"` explicitly.
3. Set `language: "zh-CN"` for Chinese responses.
4. Present the results with analysis and sources.

**Query**: $ARGUMENTS
