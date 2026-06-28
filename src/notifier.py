"""Bark 推送 + 每日定时统计通知。

在应用内起一个后台守护线程，按北京时间每天 HH:MM 触发：
读取当期统计 → Bark 推送 → 推送成功后清零当期计数。
依赖 PyPI 的 tzdata 提供 IANA 时区库（Alpine 镜像默认无系统 tz 数据）。
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

BEIJING = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


def send_bark(bark_url: str, title: str, body: str, timeout: int = 10) -> bool:
    """通过 Bark 推送一条通知。bark_url 形如 https://api.day.app/<your_key>。"""
    if not bark_url:
        logger.warning("未配置 Bark URL，跳过推送")
        return False
    url = f"{bark_url.rstrip('/')}/{quote(title)}/{quote(body)}"
    try:
        resp = requests.get(url, params={"group": "MusicLover"}, timeout=timeout)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Bark 推送失败: {e}")
        return False


def _seconds_until(hour: int, minute: int) -> float:
    """距离下一个北京时间 hour:minute 的秒数。"""
    now = datetime.now(BEIJING)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def start_daily_notifier(stats, get_bark_url, hour: int = 20, minute: int = 0) -> threading.Thread:
    """启动后台线程，每天 hour:minute(北京时间) 推送当期统计并清零。

    stats: StatsTracker 实例
    get_bark_url: 可调用对象，返回当前 Bark URL（运行时读取配置）
    """
    def loop() -> None:
        logger.info(f"Bark 每日统计推送已启动，将于每天 {hour:02d}:{minute:02d}（北京时间）触发")
        while True:
            time.sleep(_seconds_until(hour, minute))
            try:
                today = datetime.now(BEIJING).strftime("%Y-%m-%d")
                # 跨进程去重：多实例并存（如更新镜像时新旧容器重叠）时，当天仅首个抢到令牌的实例发送
                if not stats.try_claim_daily_push(today):
                    logger.info(f"今日（{today}）推送已由其他实例发送，本实例跳过")
                    time.sleep(1)
                    continue
                snap = stats.snapshot()
                version = os.getenv("APP_VERSION", "unknown")
                title = "MusicLover 今日统计"
                body = (
                    f"📅 {today}\n"
                    f"👤 使用人数(去重IP): {snap['users']}\n"
                    f"⬇️ 下载歌曲: {snap['downloads']}\n"
                    f"Σ 累计下载: {snap['total_downloads']}\n"
                    f"🏷 版本: {version}"
                )
                if send_bark(get_bark_url(), title, body):
                    logger.info(f"已推送今日统计: 人数={snap['users']} 下载={snap['downloads']} 版本={version}")
                    stats.reset_period()  # 仅推送成功才清零，失败则保留到下次一并发送
                else:
                    stats.release_daily_push(today)  # 释放令牌，允许下次重试
                    logger.warning("今日统计推送失败，当期数据保留，将在下次推送时一并发送")
            except Exception as e:
                logger.error(f"每日统计推送异常: {e}")
            time.sleep(1)  # 跨过触发的整秒，避免在同一分钟内重复触发

    thread = threading.Thread(target=loop, name="bark-daily-notifier", daemon=True)
    thread.start()
    return thread
