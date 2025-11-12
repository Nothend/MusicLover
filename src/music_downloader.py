"""音乐下载器模块

提供网易云音乐下载功能，包括：
- 音乐信息获取
- 文件下载到本地
- 内存下载
- 音乐标签写入
- 异步下载支持
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
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, APIC,TYER, USLT
from mutagen.mp4 import MP4

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
        将整数时间戳（13位或11位）转换为YYYY-MM-DD格式
        
        Args:
            timestamp: 整数时间戳（如1305388800000或13053888000）
            
        Returns:
            格式化后的日期字符串，转换失败返回空字符串
        """
        try:
            # 1. 处理11位时间戳（补全为13位毫秒级）
            if 10**10 <= timestamp_int < 10**11:  # 11位数字范围（10000000000 ~ 99999999999）
                timestamp *= 100  # 转换为13位（如13053888000 → 1305388800000）
            
            # 2. 验证13位时间戳（毫秒级）
            if not (10**12 <= timestamp_int < 10**13):  # 13位数字范围（1000000000000 ~ 9999999999999）
                return ""
            
            # 3. 转换为年月日（毫秒级时间戳需÷1000）
            return datetime.fromtimestamp(timestamp_int / 1000).strftime("%Y-%m-%d")
        
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
    
    def download_music_file(self, music_info: MusicInfo, quality: str = "standard") -> DownloadResult:
        """下载音乐文件到本地
        
        Args:
            music_id: 音乐ID
            quality: 音质等级
            
        Returns:
            下载结果对象
        """
        try:
            # 生成可能的文件名
            base_filename = f"{music_info.artists} - {music_info.name}"
            safe_filename = self._sanitize_filename(base_filename)
            
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
            
            # 写入音乐标签
            self._write_music_tags(file_path, music_info)
            
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
    
    def download_song(self, music_info: MusicInfo, quality: str = "standard", re_format: str = "file") -> DownloadResult:
        """下载音乐API（保留返回格式逻辑，使用DownloadResult）"""
        try:
            # 验证音质参数
            valid_qualities = ['standard', 'exhigh', 'lossless', 'hires', 'sky', 'jyeffect', 'jymaster']
            if quality not in valid_qualities:
                return DownloadResult(
                    success=False,
                    error_message=f"无效的音质参数，支持: {', '.join(valid_qualities)}"
                )
            
            # 验证返回格式
            if re_format not in ['file', 'json']:
                return DownloadResult(
                    success=False,
                    error_message="返回格式只支持 'file' 或 'json'"
                )
            
            
            # 获取音乐基本信息
            music_id = music_info.id
            

            # 生成可能的文件名
            base_filename = f"{music_info.artists} - {music_info.name}"
            safe_filename = self._sanitize_filename(base_filename)

            file_ext = self._determine_file_extension(music_info.download_url)
            # 检查所有可能的文件
            
            file_path = self.download_dir / f"{safe_filename}{file_ext}"
            
            
            # 检查文件是否已存在
            if file_path.exists():
                self.logger.info(f"文件已存在: {safe_filename}{file_ext}")
            else:
                # 调用下载文件方法（核心下载逻辑）
                download_result = self.download_music_file(music_info, quality)
                if not download_result.success:
                    return DownloadResult(
                        success=False,
                        error_message=f"下载失败: {download_result.error_message}",
                        music_info=music_info
                    )
                file_path = Path(download_result.file_path)
                self.logger.info(f"下载完成: {safe_filename}{file_ext}")
            
            # 根据返回格式返回结果（保留核心逻辑）
            if re_format == 'json':
                # 构建JSON响应数据
                response_data = {
                    'music_id': music_id,
                    'name': music_info['name'],
                    'artist': music_info['artist_string'],
                    'album': music_info['album'],
                    'quality': quality,
                    'quality_name': self.NeteaseApi._get_quality_display_name(quality),
                    'file_type': music_info['file_type'],
                    'file_size': music_info['file_size'],
                    'file_size_formatted': self.NeteaseApi._format_file_size(music_info['file_size']),
                    'file_path': str(file_path.absolute()),
                    'filename': safe_filename + file_ext,
                    'duration': music_info['duration'],
                    'publishTime': music_info['publishTime']
                }
                return DownloadResult(
                    success=True,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size,
                    music_info=music_info,
                    data=response_data  # 将JSON数据存入data字段
                )
            else:  # re_format == 'file'
                if not file_path.exists():
                    return DownloadResult(
                        success=False,
                        error_message="文件不存在"
                    )
                # 返回文件相关信息（实际文件发送由调用方处理）
                return DownloadResult(
                    success=True,
                    file_path=str(file_path),
                    file_size=file_path.stat().st_size,
                    music_info=music_info
                )
            
        except Exception as e:
            # 简化异常日志，去掉traceback（如果不需要详细堆栈）
            self.logger.error(f"下载音乐异常: {str(e)}")
            return DownloadResult(
                success=False,
                error_message=f"下载异常: {str(e)}"
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
            
            # 写入音乐标签
            self._write_music_tags(file_path, music_info)
            
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
    
    def _write_music_tags(self, file_path: Path, music_info: MusicInfo) -> None:
        """写入音乐标签信息
        
        Args:
            file_path: 音乐文件路径
            music_info: 音乐信息
        """
        try:
            file_ext = file_path.suffix.lower()
            
            if file_ext == '.mp3':
                self._write_mp3_tags(file_path, music_info)
            elif file_ext == '.flac':
                self._write_flac_tags(file_path, music_info)
            elif file_ext == '.m4a':
                self._write_m4a_tags(file_path, music_info)
                
        except Exception as e:
            print(f"写入音乐标签失败: {e}")
    
    def _write_mp3_tags(self, file_path: Path, music_info: MusicInfo) -> None:
        """写入MP3标签（图片>5MB自动压缩，失败不影响其他标签）"""
        try:
            audio = MP3(str(file_path), ID3=ID3)
            if not audio.tags:
                audio.add_tags()
            
            # ---------------------- 1. 保存基础标签 ----------------------
            # 基础信息（标题/艺术家/专辑等）
            audio.tags.setall('TIT2', [TIT2(encoding=3, text=music_info.name)])
            audio.tags.setall('TPE1', [TPE1(encoding=3, text=music_info.artists)])
            audio.tags.setall('TALB', [TALB(encoding=3, text=music_info.album)])
            
            if music_info.track_number > 0:
                audio.tags.setall('TRCK', [TRCK(encoding=3, text=str(music_info.track_number))])
            
            # 发行时间
            if hasattr(music_info, 'publishTime') and music_info.publishTime:
                full_date = music_info.publishTime.strip()
                try:
                    year = full_date.split('-')[0] if '-' in full_date else full_date
                    audio.tags.setall('TYER', [TYER(encoding=3, text=year)])
                    audio.tags.setall('TDRC', [TDRC(encoding=3, text=full_date)])
                except Exception as e:
                    self.logger.warning(f"发行时间处理失败: {str(e)}")
            
            # 歌词
            if music_info.lyric:
                audio.tags.setall('USLT', [USLT(
                    encoding=3, lang='XXX', desc='Lyrics', text=music_info.lyric.strip()
                )])
            if music_info.tlyric:
                audio.tags.setall('USLT:Translated', [USLT(
                    encoding=3, lang='XXX', desc='Translated Lyrics', text=music_info.tlyric.strip()
                )])
            
            # 先保存基础标签
            audio.save()
            self.logger.debug(f"已保存MP3基础标签: {file_path.name}")
            
            # ---------------------- 2. 处理图片（>5MB自动压缩） ----------------------
            if music_info.pic_url:
                try:
                    # 下载图片
                    pic_response = requests.get(music_info.pic_url, timeout=10)
                    pic_response.raise_for_status()
                    image_data = pic_response.content
                    original_size = len(image_data)
                    max_size = 5 * 1024 * 1024  # 5MB
                    
                    # 压缩逻辑
                    if original_size > max_size:
                        self.logger.debug(f"MP3图片过大（{original_size}字节），开始压缩...")
                        compressed_data = self._compress_image(image_data, max_size)
                        if not compressed_data:
                            self.logger.warning("压缩后仍超过5MB，跳过封面")
                            return  # 退出图片处理逻辑
                        image_data = compressed_data
                        self.logger.debug(f"压缩后大小: {len(image_data)}字节")
                    
                    # 添加封面并保存
                    mime_type = pic_response.headers.get('content-type', 'image/jpeg')
                    audio.tags.setall('APIC', [APIC(
                        encoding=3, mime=mime_type, type=3, desc='Cover', data=image_data
                    )])
                    audio.save()
                    self.logger.debug("已添加MP3封面并保存")
                
                except Exception as e:
                    self.logger.warning(f"MP3封面处理失败（不影响其他标签）: {str(e)}")
            
        except Exception as e:
            self.logger.error(f"MP3基础标签处理失败: {str(e)}")
                    
    def _write_flac_tags(self, file_path: Path, music_info: MusicInfo) -> None:
        """写入FLAC标签（图片>5MB自动压缩，失败不影响其他标签）"""
        try:
            audio = FLAC(str(file_path))
            
            # ---------------------- 1. 保存基础标签 ----------------------
            # 基础信息
            audio['TITLE'] = music_info.name
            audio['ARTIST'] = music_info.artists
            audio['ALBUM'] = music_info.album
            if music_info.track_number > 0:
                audio['TRACKNUMBER'] = str(music_info.track_number)
            
            # 发行时间
            if hasattr(music_info, 'publishTime') and music_info.publishTime:
                full_date = music_info.publishTime
                audio['YEAR'] = full_date.split('-')[0] if '-' in full_date else full_date
                audio['DATE'] = full_date
            else:
                self.logger.debug("publishTime为空，跳过日期标签")
            
            # 歌词
            if music_info.lyric:
                audio['LYRICS'] = music_info.lyric.strip()
            if music_info.tlyric:
                audio['TRANSLATEDLYRICS'] = music_info.tlyric.strip()
            
            # 先保存基础标签
            audio.save()
            self.logger.debug(f"已保存FLAC基础标签: {file_path.name}")
            
            # ---------------------- 2. 处理图片（>5MB自动压缩） ----------------------
            if music_info.pic_url:
                try:
                    # 下载图片
                    pic_response = requests.get(music_info.pic_url, timeout=10)
                    pic_response.raise_for_status()
                    image_data = pic_response.content
                    original_size = len(image_data)
                    max_size = 5 * 1024 * 1024  # 5MB
                    
                    # 压缩逻辑
                    if original_size > max_size:
                        self.logger.debug(f"FLAC图片过大（{original_size}字节），开始压缩...")
                        compressed_data = self._compress_image(image_data, max_size)
                        if not compressed_data:
                            self.logger.warning("压缩后仍超过5MB，跳过封面")
                            return  # 退出图片处理逻辑
                        image_data = compressed_data
                        self.logger.debug(f"压缩后大小: {len(image_data)}字节")
                    
                    # 添加封面并保存
                    from mutagen.flac import Picture
                    picture = Picture()
                    picture.type = 3
                    picture.mime = 'image/jpeg' if image_data.startswith(b'\xff\xd8') else 'image/png'
                    picture.desc = 'Cover'
                    picture.data = image_data
                    audio.add_picture(picture)
                    audio.save()
                    self.logger.debug("已添加FLAC封面并保存")
                
                except Exception as e:
                    self.logger.warning(f"FLAC封面处理失败（不影响其他标签）: {str(e)}")
            
        except Exception as e:
            self.logger.error(f"FLAC基础标签处理失败: {str(e)}")
      
    def _write_m4a_tags(self, file_path: Path, music_info: MusicInfo) -> None:
        """写入M4A标签"""
        try:
            audio = MP4(str(file_path))
            
            audio['\xa9nam'] = music_info.name
            audio['\xa9ART'] = music_info.artists
            audio['\xa9alb'] = music_info.album
            
            if music_info.track_number > 0:
                audio['trkn'] = [(music_info.track_number, 0)]
            
            # 下载并添加封面
            if music_info.pic_url:
                try:
                    pic_response = requests.get(music_info.pic_url, timeout=10)
                    pic_response.raise_for_status()
                    audio['covr'] = [pic_response.content]
                except:
                    pass  # 封面下载失败不影响主流程
            
            audio.save()
        except Exception as e:
            print(f"写入M4A标签失败: {e}")

    
    
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
    print("- 音乐标签写入")
    print("- 下载进度跟踪")