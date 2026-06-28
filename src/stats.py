"""轻量使用统计：当期去重访问 IP 数 + 下载歌曲数。

设计要点：
- 线程安全（配合 Flask threaded=True）。
- 持久化到 JSON 文件，**务必放在挂载卷**（如 /app/logs/stats.json），
  否则 CI 重建容器(docker rm + compose up)时当期数据会丢失。
- “当期”指上一次清零到现在；由每日 20:00 的 Bark 推送在发送成功后调用 reset_period() 清零。
"""
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


class StatsTracker:
    """记录当期去重访问 IP 与下载次数，并原子持久化到磁盘。"""

    def __init__(self, storage_path: str):
        self.path = Path(storage_path)
        self._lock = threading.Lock()
        self._unique_ips: set[str] = set()
        self._downloads = 0
        self._total_downloads = 0  # 上线以来累计下载（清零不影响），仅供留存
        self._period_start = self._now_str()
        self._load()

    @staticmethod
    def _now_str() -> str:
        return datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S")

    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._unique_ips = set(data.get("period_unique_ips", []))
                self._downloads = int(data.get("period_downloads", 0))
                self._total_downloads = int(data.get("total_downloads", 0))
                self._period_start = data.get("period_start", self._period_start)
                logger.info(
                    f"已加载统计: 当期人数={len(self._unique_ips)} 当期下载={self._downloads} "
                    f"累计下载={self._total_downloads}（起始 {self._period_start}）"
                )
        except Exception as e:
            logger.warning(f"加载统计文件失败，将重新开始计数: {e}")

    def _save_locked(self) -> None:
        """调用方需已持有 self._lock。原子写入避免半截文件。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "period_start": self._period_start,
                "period_unique_ips": sorted(self._unique_ips),
                "period_downloads": self._downloads,
                "total_downloads": self._total_downloads,
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)  # 原子替换
        except Exception as e:
            logger.warning(f"保存统计文件失败: {e}")

    def record_visit(self, ip: str) -> None:
        """记录一次访问的客户端 IP（去重）。仅在出现新 IP 时落盘。"""
        if not ip:
            return
        with self._lock:
            if ip in self._unique_ips:
                return
            self._unique_ips.add(ip)
            self._save_locked()

    def record_download(self, n: int = 1) -> None:
        """下载成功时累加下载计数。"""
        with self._lock:
            self._downloads += n
            self._total_downloads += n
            self._save_locked()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "period_start": self._period_start,
                "users": len(self._unique_ips),
                "downloads": self._downloads,
                "total_downloads": self._total_downloads,
            }

    def reset_period(self) -> None:
        """清零当期计数（保留累计下载），用于每日推送后开启新一期。"""
        with self._lock:
            self._unique_ips = set()
            self._downloads = 0
            self._period_start = self._now_str()
            self._save_locked()

    def try_claim_daily_push(self, date_str: str) -> bool:
        """跨进程抢占「当天已推送」令牌：原子创建标记文件，抢到返回 True。

        用于多实例并存（如更新镜像时新旧容器短暂重叠）的场景，保证当天仅一个
        实例发送每日推送。标记文件与 stats.json 同目录，**须位于共享挂载卷内**
        才能跨容器去重。标记机制本身异常时退化为「允许推送」，不阻断通知。
        """
        marker = self.path.parent / f".bark_pushed_{date_str}"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # O_CREAT|O_EXCL 原子创建：文件已存在则抛 FileExistsError（即已有实例抢到）
            fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, self._now_str().encode("utf-8"))
            finally:
                os.close(fd)
            self._cleanup_stale_markers(keep=date_str)
            return True
        except FileExistsError:
            return False
        except Exception as e:
            logger.warning(f"创建推送标记失败，按允许推送处理: {e}")
            return True

    def release_daily_push(self, date_str: str) -> None:
        """释放当天令牌（推送失败时调用），以便下次重试。"""
        try:
            (self.path.parent / f".bark_pushed_{date_str}").unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"释放推送标记失败: {e}")

    def _cleanup_stale_markers(self, keep: str) -> None:
        """清理除 keep 当天之外的历史推送标记，避免标记文件无限堆积。"""
        try:
            for p in self.path.parent.glob(".bark_pushed_*"):
                if p.name != f".bark_pushed_{keep}":
                    p.unlink(missing_ok=True)
        except Exception:
            pass
