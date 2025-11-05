#!/bin/sh
set -e  # 遇到错误立即退出

# ==================== 配置与工具函数 ====================
# 统一日志时间格式化（含时区）
log_time() {
  date +"%Y-%m-%d %H:%M:%S %Z"
}

# 应用目录配置
APP_DIR="/app"

# 简化环境检查（仅输出启动信息，无需检查远程仓库）
check_env() {
  echo "[$(log_time)] 配置信息："
  echo "[$(log_time)] - 运行模式: $RUN_MODE"
  echo "[$(log_time)] - 应用目录: $APP_DIR"
}

# ==================== 应用启动函数 ====================
# 启动Flask应用（前台运行，保持容器活跃）
start_app() {
  echo "[$(log_time)] 启动应用服务..."
  cd "$APP_DIR/src" && exec python main.py  # exec确保应用成为容器主进程
}

# ==================== 主流程执行 ====================
echo "[$(log_time)] 启动应用初始化..."

# 1. 检查环境变量
check_env

# 2. 使用本地代码直接启动应用（无同步逻辑）
echo "[$(log_time)] 使用本地代码启动应用..."
start_app