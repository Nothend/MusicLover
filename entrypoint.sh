#!/bin/sh
set -e

# 源码为扁平 import，需以 src 为工作目录并加入 PYTHONPATH；
# exec 让 python 成为容器 1 号进程，正确接收停止信号。
export PYTHONPATH="/app/src:${PYTHONPATH}"
cd /app/src
exec python main.py
