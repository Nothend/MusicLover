#!/bin/sh
set -e  # 遇到错误立即退出

# ==================== 配置与工具函数 ====================
# 统一日志时间格式化（含时区）
log_time() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}

# 配置参数（支持通过docker-compose环境变量覆盖）
REMOTE_REPO="${REMOTE_REPO:-https://github.com/Nothend/MusicLover.git}"
SYNC_INTERVAL="${SYNC_INTERVAL:-0 3 */2 * *}"  # 每两天凌晨3点（默认）
APP_DIR="/app"
REPO_DIR="/app/repo"
MAIN_PID=0  # 主应用进程ID

# 检查环境变量并提供友好提示
check_env() {
  if [ -z "$REMOTE_REPO" ]; then
    echo "[$(log_time)] 错误：未设置REMOTE_REPO环境变量（代码仓库地址）" >&2
    exit 1
  fi
  echo "[$(log_time)] 配置信息："
  echo "[$(log_time)] - 代码仓库: $REMOTE_REPO"
  echo "[$(log_time)] - 同步间隔: $SYNC_INTERVAL"
}

# ==================== 核心逻辑封装（模块化） ====================
# 生成独立的同步脚本（避免crontab环境变量问题）
create_sync_script() {
  cat > /usr/local/bin/sync_code <<EOF
#!/bin/sh
set -e

# 子脚本日志函数
log_time() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}

APP_DIR="$APP_DIR"
REPO_DIR="$REPO_DIR"
REMOTE_REPO="$REMOTE_REPO"

echo "[$(log_time)] 开始执行代码同步..."

# 1. 克隆或更新仓库
if [ ! -d "\$REPO_DIR/.git" ]; then
  echo "[\$(log_time)] 首次启动，克隆仓库: \$REMOTE_REPO"
  rm -rf "\$REPO_DIR"  # 清理残留目录
  git clone "\$REMOTE_REPO" "\$REPO_DIR" || {
    echo "[\$(log_time)] 错误：仓库克隆失败" >&2
    exit 1
  }
else
  echo "[\$(log_time)] 拉取最新代码..."
  cd "\$REPO_DIR" && git pull || {
    echo "[\$(log_time)] 错误：代码拉取失败" >&2
    exit 1
  }
fi

# 2. 同步代码到应用目录（排除挂载文件/目录）
echo "[\$(log_time)] 同步代码到应用目录: \$APP_DIR"
rsync -av --delete \
  --exclude="config.yaml" \
  --exclude="logs/" \
  --exclude="downloads/" \
  --exclude="repo/" \
  --exclude="src/static/js/" \
  "\$REPO_DIR/" "\$APP_DIR/" || {
  echo "[\$(log_time)] 错误：文件同步失败" >&2
  exit 1
}

# 3. 检查并安装依赖（如需）
if [ -f "\$APP_DIR/requirements.txt" ]; then
  echo "[\$(log_time)] 安装/更新依赖..."
  python -m pip install --no-cache-dir -r "\$APP_DIR/requirements.txt" || {
    echo "[\$(log_time)] 错误：依赖安装失败" >&2
    exit 1
  }
fi

echo "[\$(log_time)] 代码同步完成"
EOF

  chmod +x /usr/local/bin/sync_code
  echo "[$(log_time)] 同步脚本创建完成: /usr/local/bin/sync_code"
}

# 启动/重启Flask应用
manage_app() {
  action="$1"  # start / restart
  if [ "$action" = "restart" ] && [ $MAIN_PID -ne 0 ]; then
    echo "[$(log_time)] 重启应用服务（旧PID: $MAIN_PID）..."
    kill $MAIN_PID || {
      echo "[$(log_time)] 警告：终止旧进程失败，可能已退出" >&2
    }
    wait $MAIN_PID 2>/dev/null || true
  fi

  echo "[$(log_time)] 启动应用服务..."
  cd "$APP_DIR/src" && python main.py &
  MAIN_PID=$!
  echo "[$(log_time)] 应用服务启动完成（新PID: $MAIN_PID）"
}

# 配置定时任务
setup_cron() {
  # 创建cron任务目录（alpine专用）
  mkdir -p /etc/periodic/custom

  # 定时任务内容：同步代码后重启应用
  cat > /etc/periodic/custom/code_sync_job <<EOF
#!/bin/sh
/usr/local/bin/sync_code && /usr/local/bin/restart_app
EOF

  chmod +x /etc/periodic/custom/code_sync_job

  # 生成重启应用的独立脚本（供cron调用）
  cat > /usr/local/bin/restart_app <<EOF
#!/bin/sh
# 子脚本日志函数
log_time() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}
echo "[\$(log_time)] 触发应用重启..."

# 关键：强制杀死占用5151端口的所有进程
PORT=5151
echo "[\$(log_time)] 检查端口 \$PORT 是否被占用..."
PID=\$(lsof -i :\$PORT -t)  # 获取占用端口的进程ID
if [ -n "\$PID" ]; then
  echo "[\$(log_time)] 端口 \$PORT 被进程 \$PID 占用，强制杀死..."
  kill -9 \$PID || true  # 使用-9强制终止，确保杀死
  sleep 2  # 等待进程退出
fi
# 启动新应用
APP_DIR="$APP_DIR"
kill \$MAIN_PID || true
wait \$MAIN_PID 2>/dev/null || true
echo "[\$(log_time)] 准备进入目录 \$APP_DIR/src ..."
cd "\$APP_DIR/src" && python main.py &
export MAIN_PID=\$!
echo "[\$(log_time)] 应用重启完成（新PID: \$MAIN_PID）"
EOF

  chmod +x /usr/local/bin/restart_app

  # 写入crontab
  echo "[$(log_time)] 配置定时任务: $SYNC_INTERVAL"
  if ! (crontab -l 2>/dev/null | grep -v "/etc/periodic/custom/code_sync_job"; echo "$SYNC_INTERVAL /etc/periodic/custom/code_sync_job 2>&1") | crontab -; then
    echo "[$(log_time)] 错误：定时任务配置失败" >&2
    echo "[$(log_time)] 失败的cron配置内容：$SYNC_INTERVAL /etc/periodic/custom/code_sync_job" >&2
    exit 1
  fi
}

# ==================== 主流程执行 ====================
echo "[$(log_time)] 启动应用初始化..."

# 1. 检查环境变量
check_env

# 2. 创建同步脚本（用于后续定时更新）
create_sync_script

# 3. 使用镜像中的本地代码启动，不执行首次同步
echo "[$(log_time)] 使用镜像内置代码启动应用..."
echo "[$(log_time)] 注意：首次启动使用构建时的代码版本，定时同步功能将在后续生效"

# 4. 启动应用
manage_app "start"

# 5. 配置定时任务（用于后续代码更新）
setup_cron

# 6. 启动crond服务（前台运行，保持容器活跃）
echo "[$(log_time)] 启动定时任务服务..."
exec crond -f -l 2  # -l 2：日志级别（info）