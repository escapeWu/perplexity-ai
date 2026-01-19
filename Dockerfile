# Perplexity MCP Server Docker Image
# 使用多阶段构建优化镜像大小

# ============ 阶段1: 前端构建 ============
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

# 复制前端项目文件
COPY perplexity/server/web/package.json perplexity/server/web/package-lock.json* ./

# 安装依赖
RUN npm ci --prefer-offline --no-audit

# 复制前端源码
COPY perplexity/server/web/ ./

# 构建前端
RUN npm run build

# ============ 阶段2: Python 构建 ============
FROM python:3.12-slim AS python-builder

WORKDIR /build

# 安装构建依赖 (curl_cffi 需要编译)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 缓存
COPY pyproject.toml README.md ./
COPY perplexity/ ./perplexity/
COPY perplexity_async/ ./perplexity_async/

# 安装到独立目录，方便后续复制
RUN pip install --no-cache-dir --prefix=/install .

# ============ 阶段3: 运行时镜像 ============
FROM python:3.12-slim

WORKDIR /app

# 只安装运行时必需的系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从 Python 构建阶段复制已安装的 Python 包
COPY --from=python-builder /install/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# 复制应用代码
COPY perplexity/ ./perplexity/

# 从前端构建阶段复制构建产物
COPY --from=frontend-builder /frontend/dist ./perplexity/server/web/dist

# 设置默认 token pool 配置路径（通过 volume 挂载）
ENV PPLX_TOKEN_POOL_CONFIG=/app/token_pool_config.json

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "-m", "perplexity.server"]
