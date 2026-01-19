---
name: "Perplexity Search"
description: "Real-time web search and research using Perplexity AI. Use this skill when you need real-time information like API documentation, web content, latest news, current events, or any data that may be outdated in training data."
category: Search
tags: [perplexity, search, web, realtime, research, api-docs]
argument-hint: [query]
---

# Perplexity Search Skill

Use this skill when you need to fetch **real-time data** from the web. This includes:

- **API Documentation**: Latest API references, SDK docs, library documentation
- **Current Events**: News, announcements, releases
- **Web Content**: Blog posts, tutorials, articles
- **Market Data**: Prices, statistics, trends
- **Technical Information**: Latest versions, compatibility info, changelogs

## Available Modes

### 1. Quick Search
**Use for**: Simple questions, fact-checking, quick lookups
- Fast response time
- Real-time web information
- Tool: `mcp__perplexity-mcp__search`

### 2. Reasoning
**Use for**: Complex questions requiring logical analysis
- Multi-step thinking process
- Uses reasoning models (default: gemini-3.0-pro)
- Tool: `mcp__perplexity-mcp__research` with `mode: "reasoning"`

### 3. Deep Research
**Use for**: Comprehensive investigations, academic research, market analysis
- Most thorough research mode
- Extensively explores multiple sources
- Tool: `mcp__perplexity-mcp__research` with `mode: "deep research"`

## Selection Guide

| Scenario | Mode |
|----------|------|
| "What is the latest version of React?" | Quick Search |
| "How does React 19 compare to React 18?" | Reasoning |
| "Comprehensive analysis of React vs Vue in 2024" | Deep Research |
| "Current price of Bitcoin" | Quick Search |
| "How do I use the new OpenAI API?" | Quick Search |
| "What are the pros and cons of different state management solutions?" | Reasoning |
| "In-depth analysis of microservices architecture patterns" | Deep Research |

## Execution

Based on the query complexity, choose the appropriate mode:

**For simple/quick queries:**
```
Use mcp__perplexity-mcp__search with:
- query: user's question
- language: "zh-CN" (for Chinese responses)
```

**For reasoning/analysis queries:**
```
Use mcp__perplexity-mcp__research with:
- query: user's question
- mode: "reasoning"
- language: "zh-CN"
```

**For deep research queries:**
```
Use mcp__perplexity-mcp__research with:
- query: user's question
- mode: "deep research"
- language: "zh-CN"
```

**Query**: $ARGUMENTS
