# 构建阶段：安装依赖
FROM python:3.12-alpine3.21 AS builder

# 设置工作目录
WORKDIR /app

# 安装构建依赖
RUN apk add --no-cache gcc musl-dev libffi-dev

# 创建虚拟环境
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# 复制依赖文件
COPY requirements.txt .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt


# 最终阶段：运行环境
FROM python:3.12-alpine3.21

# 仅保留必要基础工具（移除git/rsync/lsof等同步相关工具）
RUN apk update && apk add --no-cache \
    && rm -rf /var/cache/apk/*  # 清空缓存，减小镜像体积

# 创建所需目录（仅保留应用必要目录，删除repo目录）
RUN mkdir -p /app/logs /app/downloads /app/src \
    && chmod 755 /app/logs /app/downloads  

# 设置工作目录
WORKDIR /app

# 从构建阶段复制虚拟环境
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# 复制应用代码（仅用本地代码）
COPY src/ /app/src/

# 删除测试文件（保留原逻辑）
RUN find /app/src/static/js -name "*test*" -delete

# 设置生产环境变量
ENV RUN_MODE=production

# 复制入口脚本
COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

# 暴露端口
EXPOSE 5151

# 启动入口
ENTRYPOINT ["/app/entrypoint.sh"]