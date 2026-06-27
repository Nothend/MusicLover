# 构建阶段：安装依赖 + 混淆JS文件
FROM python:3.12-alpine3.21 AS builder

# 设置工作目录
WORKDIR /app

# 安装构建依赖（新增 Node.js 和 npm，用于混淆JS）
RUN apk add --no-cache gcc musl-dev libffi-dev \
    nodejs npm
    # 新增：安装Node.js环境（支持JavaScript混淆工具）

# 创建虚拟环境
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 新增：安装JavaScript混淆工具 javascript-obfuscator
RUN npm install -g javascript-obfuscator

# 复制应用代码（此时复制的是未混淆的源文件）
COPY src/ /app/src/

# 新增：对指定JS文件进行自动混淆（覆盖原文件）
# 混淆 main.js
RUN javascript-obfuscator /app/src/static/js/main.js \
    --output /app/src/static/js/main.js \
    --compact true \
    --control-flow-flattening true

# 保留原逻辑：删除测试文件（可选，如果你不再需要test文件）
RUN find /app/src/static/js -name "*test*" -delete


# 最终阶段：运行环境（无需修改，直接使用builder阶段处理后的文件）
FROM python:3.12-alpine3.21

# 新增：接收构建参数作为环境变量
ARG APP_VERSION=unknown
ENV APP_VERSION=$APP_VERSION

# 创建所需目录
RUN mkdir -p /app/logs /app/downloads /app/src \
    && chmod 755 /app/logs /app/downloads  

# 设置工作目录
WORKDIR /app

# 从构建阶段复制虚拟环境和处理后的代码（包含混淆后的JS）
COPY --from=builder /venv /venv
COPY --from=builder /app/src/ /app/src/

# 复制唯一配置模板：未挂载 config.yaml 时由 config.py 自动拷贝为运行配置
COPY config.sample.yaml /app/config.sample.yaml

ENV PATH="/venv/bin:$PATH"

# 复制入口脚本
COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

# 暴露端口
EXPOSE 5151

# 启动入口
ENTRYPOINT ["/app/entrypoint.sh"]