"""音乐下载器模块

提供网易云音乐下载功能，包括：
- 音乐信息获取
- 文件下载到本地
- 内存下载
- 异步下载支持

说明：本项目（musiclover）不写入歌曲标签等元数据，下载的是原始音频文件。
"""

from concurrent.futures import ThreadPoolExecutor
import os
import re
import asyncio
import threading
import aiohttp
import aiofiles
from io import BytesIO
from typing import Dict, List, Optional, Tuple, Any, Union
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

import logging
import requests

from music_api import NeteaseAPI, APIException
from datetime import datetime
# 给BytesIO起别名，用于类型注解（可选，方便代码阅读）
BytesIOType = BytesIO  # 直接用io模块的BytesIO作为类型别名

class AudioFormat(Enum):
    """音频格式枚举"""
    MP3 = "mp3"
    FLAC = "flac"
    M4A = "m4a"
    UNKNOWN = "unknown"


class QualityLevel(Enum):
    """音质等级枚举"""
    STANDARD = "standard"  # 标准
    EXHIGH = "exhigh"      # 极高
    LOSSLESS = "lossless"  # 无损
    HIRES = "hires"        # Hi-Res
    SKY = "sky"            # 沉浸环绕声
    JYEFFECT = "jyeffect"  # 高清环绕声
    JYMASTER = "jymaster"  # 超清母带


@dataclass
class MusicInfo:
    """音乐信息数据类"""
    id: int
    name: str
    publishTime: str
    artists: str
    album: str
    pic_url: str
    duration: int
    track_number: int
    download_url: str
    file_type: str
    file_size: int
    quality: str
    lyric: str = ""
    tlyric: str = ""


@dataclass
class DownloadResult:
    """下载结果数据类"""
    success: bool
    file_path: Optional[str] = None
    file_size: int = 0
    error_message: str = ""
    music_info: Optional[MusicInfo] = None


class DownloadException(Exception):
    """下载异常类"""
    pass

# 配置日志，方便调试
class MusicDownloader:
    """音乐下载器主类"""
    
    def __init__(self,cookies: Dict[str, str], download_dir: str = "/app/downloads", max_concurrent: int = 3):
        """
        初始化音乐下载器
        
        Args:
            download_dir: 下载目录
            max_concurrent: 最大并发下载数
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.max_concurrent = max_concurrent

        self.active_downloads = 0  # 当前活跃下载数
        self.download_lock = threading.Lock()  # 线程安全锁
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent)  # 线程池
        
        # 初始化依赖
        self.cookies = cookies
        self.api = NeteaseAPI()
        
        # 支持的文件格式
        self.supported_formats = {
            'mp3': AudioFormat.MP3,
            'flac': AudioFormat.FLAC,
            'm4a': AudioFormat.M4A
        }
        self.logger = logging.getLogger(__name__)


    def get_sanitize_filename(self, filename: str) -> str:
        """公开的文件名清理方法
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的安全文件名
        """
        return self._sanitize_filename(filename)
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的安全文件名
        """
        # 移除或替换非法字符
        illegal_chars = r'[<>:"/\\|?*]'
        filename = re.sub(illegal_chars, ' & ', filename)
        
        # 移除前后空格和点
        filename = filename.strip(' .')
        
        # 限制长度
        if len(filename) > 200:
            filename = filename[:200]
        
        return filename or "unknown"
    
    def _timestamp_str_to_date(self, timestamp_int: int) -> str:
        """
        将整数时间戳（10-13位）转换为YYYY-MM-DD格式

        Args:
            timestamp_int: 整数时间戳（10位秒级 / 11-13位毫秒级）

        Returns:
            格式化后的日期字符串，转换失败返回空字符串
        """
        try:
            # 1. 按位数判断单位（10位为秒级，11-13位为毫秒级）
            ts_len = len(str(timestamp_int))
            if ts_len == 10:
                timestamp_ms = timestamp_int * 1000
            elif 11 <= ts_len <= 13:
                timestamp_ms = timestamp_int
            else:
                return ""

            # 2. 验证时间范围（1970-01-01 ~ 2100-12-31，毫秒级）
            if not (0 <= timestamp_ms <= 4102444799000):
                return ""

            # 3. 转换为年月日（毫秒级→秒级，除以1000）
            return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d")

        except (ValueError, TypeError, OSError):
            # 处理异常情况（如数值溢出、非整数类型等）
            return ""

    def _determine_file_extension(self, url: str, content_type: str = "") -> str:
        """根据URL和Content-Type确定文件扩展名
        
        Args:
            url: 下载URL
            content_type: HTTP Content-Type头
            
        Returns:
            文件扩展名
        """
        # 首先尝试从URL获取
        if '.flac' in url.lower():
            return '.flac'
        elif '.mp3' in url.lower():
            return '.mp3'
        elif '.m4a' in url.lower():
            return '.m4a'
        
        # 从Content-Type获取
        content_type = content_type.lower()
        if 'flac' in content_type:
            return '.flac'
        elif 'mpeg' in content_type or 'mp3' in content_type:
            return '.mp3'
        elif 'mp4' in content_type or 'm4a' in content_type:
            return '.m4a'
        
        return '.mp3'  # 默认
    
    def get_music_info(self, music_id: int, quality: str = "standard") -> MusicInfo:
        """获取音乐详细信息
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            音乐信息对象
            
        Raises:
            DownloadException: 获取信息失败时抛出
        """
        try:
            # 获取cookies
            cookies = self.cookies
            
            # 获取音乐URL信息
            url_result = self.api.get_song_url(music_id, quality, cookies)
            if not url_result.get('data') or not url_result['data']:
                raise DownloadException(f"无法获取音乐ID {music_id} 的播放链接")
            
            song_data = url_result['data'][0]
            download_url = song_data.get('url', '')
            if not download_url:
                raise DownloadException(f"音乐ID {music_id} 无可用的下载链接")
            
            # 获取音乐详情
            detail_result = self.api.get_song_detail(music_id)
            if not detail_result.get('songs') or not detail_result['songs']:
                raise DownloadException(f"无法获取音乐ID {music_id} 的详细信息")
            
            song_detail = detail_result['songs'][0]
            
            # 获取歌词
            lyric_result = self.api.get_lyric(music_id, cookies)
            lyric = lyric_result.get('lrc', {}).get('lyric', '') if lyric_result else ''
            tlyric = lyric_result.get('tlyric', {}).get('lyric', '') if lyric_result else ''
            
            # 构建艺术家字符串
            artists = '/'.join(artist['name'] for artist in song_detail.get('ar', []))
            # 提取发行时间（处理13位/11位时间戳）
            # 网易云API的album.publishTime为13位毫秒级时间戳
            publish_timestamp = song_detail.get('publishTime', '2025')
            # 转换为年月日格式（调用工具函数）
            publish_time = self._timestamp_str_to_date(publish_timestamp)
            # 创建MusicInfo对象
            music_info = MusicInfo(
                id=music_id,
                name=song_detail.get('name', '未知歌曲'),
                publishTime=publish_time,
                artists=artists or '未知艺术家',
                album=song_detail.get('al', {}).get('name', '未知专辑'),
                pic_url=song_detail.get('al', {}).get('picUrl', ''),
                duration=song_detail.get('dt', 0) // 1000,  # 转换为秒
                track_number=song_detail.get('no', 0),
                download_url=download_url,
                file_type=song_data.get('type', 'mp3').lower(),
                file_size=song_data.get('size', 0),
                quality=quality,
                lyric=lyric,
                tlyric=tlyric
            )
            
            return music_info
            
        except APIException as e:
            raise DownloadException(f"API调用失败: {e}")
        except Exception as e:
            raise DownloadException(f"获取音乐信息时发生错误: {e}")
    
    def download_music_file(self, music_id: int, quality: str = "standard") -> DownloadResult:
        """下载音乐文件到本地
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            下载结果对象
        """
        try:
            # 获取音乐信息
            music_info = self.get_music_info(music_id, quality)
            
            # 生成文件名
            filename = f"{music_info.artists} - {music_info.name}"
            safe_filename = self._sanitize_filename(filename)
            
            # 确定文件扩展名
            file_ext = self._determine_file_extension(music_info.download_url)
            file_path = self.download_dir / f"{safe_filename}{file_ext}"
            
            # 检查文件是否已存在
            if file_path.exists():
                return DownloadResult(
                    success=True,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size,
                    music_info=music_info
                )
            
            # 下载文件
            response = requests.get(music_info.download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            # 写入文件
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            return DownloadResult(
                success=True,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
                music_info=music_info
            )
            
        except DownloadException:
            raise
        except requests.RequestException as e:
            return DownloadResult(
                success=False,
                error_message=f"下载请求失败: {e}"
            )
        except Exception as e:
            return DownloadResult(
                success=False,
                error_message=f"下载过程中发生错误: {e}"
            )
    
    async def download_music_file_async(self, music_id: int, quality: str = "standard") -> DownloadResult:
        """异步下载音乐文件到本地
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            下载结果对象
        """
        try:
            # 获取音乐信息（同步操作）
            music_info = self.get_music_info(music_id, quality)
            
            # 生成文件名
            filename = f"{music_info.artists} - {music_info.name}"
            safe_filename = self._sanitize_filename(filename)
            
            # 确定文件扩展名
            file_ext = self._determine_file_extension(music_info.download_url)
            file_path = self.download_dir / f"{safe_filename}{file_ext}"
            
            # 检查文件是否已存在
            if file_path.exists():
                return DownloadResult(
                    success=True,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size,
                    music_info=music_info
                )
            
            # 异步下载文件
            async with aiohttp.ClientSession() as session:
                async with session.get(music_info.download_url) as response:
                    response.raise_for_status()
                    
                    async with aiofiles.open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
            
            return DownloadResult(
                success=True,
                file_path=str(file_path),
                file_size=file_path.stat().st_size,
                music_info=music_info
            )
            
        except DownloadException:
            raise
        except aiohttp.ClientError as e:
            return DownloadResult(
                success=False,
                error_message=f"异步下载请求失败: {e}"
            )
        except Exception as e:
            return DownloadResult(
                success=False,
                error_message=f"异步下载过程中发生错误: {e}"
            )
    
    def download_music_to_memory(self, music_info:MusicInfo, quality: str = "standard") -> Tuple[bool, BytesIOType, MusicInfo]:
        """下载音乐到内存（本项目不写入任何标签/元信息，返回原始音频）"""
        try:
            # 检查是否超过并发限制
            with self.download_lock:
                if self.active_downloads >= self.max_concurrent:
                    raise DownloadException(f"超过最大并发下载数（{self.max_concurrent}），请稍后再试")
                self.active_downloads += 1

            try:
                # 流式下载到内存
                response = requests.get(
                    music_info.download_url,
                    stream=True,
                    timeout=30,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                )
                response.raise_for_status()

                # 写入内存
                audio_data = BytesIO()
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        audio_data.write(chunk)
                audio_data.seek(0)

                return True, audio_data, music_info

            finally:
                # 无论成功失败，都减少活跃计数
                with self.download_lock:
                    self.active_downloads -= 1

        except Exception as e:
            raise DownloadException(f"内存下载失败: {str(e)}")
        
    def async_download_multiple(self, music_ids: List[int], quality: str = "standard") -> List[Dict]:
        """异步下载多个音乐到内存
        
        Args:
            music_ids: 音乐ID列表
            quality: 音质等级
            
        Returns:
            下载结果列表，每个元素包含id、success、data/error信息
        """
        # 限制单次最大下载数量（防止内存爆炸）
        if len(music_ids) > 10:
            raise DownloadException("单次最多下载10个文件")

        futures = []
        results = []

        # 提交所有下载任务到线程池
        for music_id in music_ids:
            future = self.executor.submit(
                self._wrap_single_download,  # 包装单个下载任务
                music_id,
                quality
            )
            futures.append((music_id, future))

        # 收集结果
        for music_id, future in futures:
            try:
                success, audio_data, music_info = future.result(timeout=60)  # 单个任务超时60秒
                results.append({
                    "id": music_id,
                    "success": True,
                    "data": {
                        "audio_data": audio_data,
                        "music_info": music_info
                    }
                })
            except Exception as e:
                results.append({
                    "id": music_id,
                    "success": False,
                    "error": str(e)
                })

        return results

    def _wrap_single_download(self, music_id: int, quality: str) -> Tuple[bool, BytesIOType, MusicInfo]:
        """包装单个下载任务，用于线程池调用"""
        return self.download_music_to_memory(music_id, quality)
    
    async def download_batch_async(self, music_ids: List[int], quality: str = "standard") -> List[DownloadResult]:
        """批量异步下载音乐
        
        Args:
            music_ids: 音乐ID列表
            quality: 音质等级
            
        Returns:
            下载结果列表
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def download_with_semaphore(music_id: int) -> DownloadResult:
            async with semaphore:
                return await self.download_music_file_async(music_id, quality)
        
        tasks = [download_with_semaphore(music_id) for music_id in music_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理异常结果
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(DownloadResult(
                    success=False,
                    error_message=f"下载音乐ID {music_ids[i]} 时发生异常: {result}"
                ))
            else:
                processed_results.append(result)
        
        return processed_results
    
    def convert_to_music_info(self,music_info_dict: dict) -> MusicInfo:
        """
        将音乐信息字典转换为MusicInfo实例
        
        参数:
            music_info_dict: 包含音乐信息的字典（对应题中json数据结构）
        
        返回:
            MusicInfo实例
        """
        return MusicInfo(
            id=music_info_dict['id'],
            name=music_info_dict['name'],
            publishTime=music_info_dict['publishTime'],
            # 字典中的artist_string对应类中的artists字段
            artists=music_info_dict['artist_string'],
            album=music_info_dict['album'],
            pic_url=music_info_dict['pic_url'],
            duration=music_info_dict['duration'],
            track_number=music_info_dict['track_number'],
            download_url=music_info_dict['download_url'],
            file_type=music_info_dict['file_type'],
            file_size=music_info_dict['file_size'],
            # 字典中未包含quality，这里使用默认空字符串（可根据实际需求调整）
            quality=music_info_dict.get('quality', ''),
            lyric=music_info_dict['lyric'],
            tlyric=music_info_dict['tlyric']
        )

    def get_file_extension(self, url: str, content_type: str = "") -> str:
        """获取音乐文件扩展名
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            文件扩展名字符串（如'.mp3'）
        """
        try:
            return self._determine_file_extension(url, content_type)
        except Exception as e:
            raise DownloadException(f"获取文件扩展名失败: {e}")

    def get_download_progress(self, music_id: int, quality: str = "standard") -> Dict[str, Any]:
        """获取下载进度信息
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            包含进度信息的字典
        """
        try:
            music_info = self.get_music_info(music_id, quality)
            
            filename = f"{music_info.artists} - {music_info.name}"
            safe_filename = self._sanitize_filename(filename)
            file_ext = self._determine_file_extension(music_info.download_url)
            file_path = self.download_dir / f"{safe_filename}{file_ext}"
            
            if file_path.exists():
                current_size = file_path.stat().st_size
                progress = (current_size / music_info.file_size * 100) if music_info.file_size > 0 else 0
                
                return {
                    'music_id': music_id,
                    'filename': safe_filename + file_ext,
                    'total_size': music_info.file_size,
                    'current_size': current_size,
                    'progress': min(progress, 100),
                    'completed': current_size >= music_info.file_size
                }
            else:
                return {
                    'music_id': music_id,
                    'filename': safe_filename + file_ext,
                    'total_size': music_info.file_size,
                    'current_size': 0,
                    'progress': 0,
                    'completed': False
                }
                
        except Exception as e:
            return {
                'music_id': music_id,
                'error': str(e),
                'progress': 0,
                'completed': False
            }

    # 动态获取配置文件路径：
    # 本地调试时，通过环境变量指定本地路径；Docker中使用默认的/app/downloads路径
    def get_config_path():
        # 优先读取环境变量"CONFIG_PATH"（本地调试时设置）
        env_path = os.getenv("DOWNLOAD_PATH")
        if env_path:
            return env_path
        # 否则默认使用Docker路径
        return "/app/downloads"

if __name__ == "__main__":
    # 测试代码
    #downloader = MusicDownloader()
    print("音乐下载器模块")
    print("支持的功能:")
    print("- 同步下载")
    print("- 异步下载")
    print("- 批量下载")
    print("- 内存下载")
    print("- 下载进度跟踪")