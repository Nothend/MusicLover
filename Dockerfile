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


# 最终阶段：运行环境（使用 root 用户）
FROM python:3.12-alpine3.21

# 安装运行时依赖（git用于拉代码，busybox提供crond等工具）
RUN apk update && apk add --no-cache \
    busybox \
    git \
    rsync \
    lsof \
    && rm -rf /var/cache/apk/*

# 创建所需目录（root 用户默认有完全权限，简化权限设置）# 确保目录可读写
RUN mkdir -p /app/logs /app/downloads /app/repo /app/src \
    && chmod 755 /app/logs /app/downloads /app/repo  

# 保持 root 用户（默认，无需切换）
# USER root  # 可省略，基础镜像默认即为 root

# 设置工作目录
WORKDIR /app

# 从构建阶段复制虚拟环境（root 权限下无需指定 chown）
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# 复制应用代码
COPY src/ /app/src/

# 复制入口脚本
COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

# 暴露端口
EXPOSE 5151
# 启动入口
ENTRYPOINT ["/app/entrypoint.sh"]