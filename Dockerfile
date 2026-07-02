# ==================== 构建阶段：装依赖 + 混淆前端 JS ====================
FROM python:3.12-alpine3.21 AS builder
WORKDIR /app

# 构建期依赖：编译部分 Python 包用的 C 工具链 + 混淆 JS 用的 Node（都只留在 builder 阶段）
RUN apk add --no-cache gcc musl-dev libffi-dev nodejs npm \
    && npm install -g javascript-obfuscator

# 先装 Python 依赖：仅当 requirements.txt 变化时才让这层缓存失效
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码并混淆前端 JS（覆盖原文件，避免直接扒源码）
COPY src/ /app/src/
RUN for f in main.js tagwriter.js; do \
        javascript-obfuscator "/app/src/static/js/$f" \
            --output "/app/src/static/js/$f" \
            --compact true \
            --control-flow-flattening true; \
    done

# ==================== 运行阶段：干净运行环境 ====================
FROM python:3.12-alpine3.21
WORKDIR /app/src

ARG APP_VERSION=unknown
ENV APP_VERSION=$APP_VERSION \
    PATH="/venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONUNBUFFERED=1

# 日志目录（未挂载卷时也需存在）
RUN mkdir -p /app/logs

# 仅拷贝运行所需：venv、（含混淆后 JS 的）源码、配置模板、入口脚本
COPY --from=builder /venv /venv
COPY --from=builder /app/src/ /app/src/
COPY config.sample.yaml /app/config.sample.yaml
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 5151

# 健康检查：探活公开的 /health（127.0.0.1 已在 IP 白名单内，不受来源校验影响）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:5151/health >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
