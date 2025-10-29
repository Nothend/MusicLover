import logging
import os
from datetime import datetime
import sys
from typing import Optional

def setup_logger(level: int = logging.INFO) -> logging.Logger:
    """配置日志系统（确保控制台和文件输出正常）"""
    # 1. 获取根日志器（确保全局唯一）
    logger = logging.getLogger()
    # 清除已有处理器（避免重复输出，解决首次配置失败后无法重试的问题）
    if logger.handlers:
        logger.handlers.clear()
    
    # 2. 创建日志目录（使用绝对路径，避免相对路径歧义）
    log_dir = os.path.abspath("logs")  # 转为绝对路径
    try:
        os.makedirs(log_dir, exist_ok=True)
    except PermissionError:
        print(f"警告：无权限创建日志目录 {log_dir}，日志可能无法写入文件")  # 降级提示
    
    # 3. 日志文件名（绝对路径）
    log_file = os.path.join(log_dir, f"{datetime.now().strftime('%Y%m%d')}.log")
    
    # 4. 配置日志格式（包含更多调试信息）
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s'  # 增加行号，便于定位
    )
    
    # 5. 控制台处理器（确保输出到stdout，兼容终端）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)  # 显式设置级别，与根日志一致
    
    # 6. 文件处理器（确保编码和权限）
    try:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)  # 显式设置级别
    except PermissionError:
        file_handler = None
        print(f"警告：无权限写入日志文件 {log_file}，仅输出到控制台")  # 降级提示
    
    # 7. 配置根日志
    logger.setLevel(level)
    logger.addHandler(console_handler)  # 确保添加控制台处理器
    if file_handler:
        logger.addHandler(file_handler)
    
    # 调试：确认处理器已添加
    logger.debug(f"日志系统初始化完成，级别：{logging.getLevelName(level)}")
    logger.debug(f"控制台处理器已添加：{bool(console_handler in logger.handlers)}")
    logger.debug(f"文件日志路径：{log_file if file_handler else '无'}")
    
    return logger