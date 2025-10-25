"""音乐下载器模块

提供网易云音乐下载功能，包括：
- 音乐信息获取
- 文件下载到本地
- 内存下载
- 音乐标签写入
- 异步下载支持
"""

from concurrent.futures import ThreadPoolExecutor
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
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, APIC
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
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
class MusicDownloader:
    """音乐下载器主类"""
    
    def __init__(self,cookies: Dict[str, str], download_dir: str = "downloads", max_concurrent: int = 3):
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
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的安全文件名
        """
        # 移除或替换非法字符
        illegal_chars = r'[<>:"/\\|?*]'
        filename = re.sub(illegal_chars, '_', filename)
        
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
    
    def download_music_to_memory(self, music_id: int, quality: str = "standard") -> Tuple[bool, BytesIOType, MusicInfo]:
        """下载音乐到内存（含标签写入）"""
        try:
            # 检查是否超过并发限制
            with self.download_lock:
                if self.active_downloads >= self.max_concurrent:
                    raise DownloadException(f"超过最大并发下载数（{self.max_concurrent}），请稍后再试")
                self.active_downloads += 1

            try:
                # 获取音乐信息
                music_info = self.get_music_info(music_id, quality)
                if not music_info.download_url:
                    raise DownloadException("未获取到有效下载链接")

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

                # 内存中写入标签
                # 确定文件扩展名
                file_ext = self._determine_file_extension(music_info.download_url)
                tagged_audio = self._write_music_tags_memory(audio_data, music_info, file_ext)

                return True, tagged_audio, music_info

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
        """写入MP3标签"""
        try:
            audio = MP3(str(file_path),ID3=ID3)
            
            # 添加ID3标签
            audio.tags.add(TIT2(encoding=3, text=music_info.name))
            audio.tags.add(TPE1(encoding=3, text=music_info.artists))
            audio.tags.add(TALB(encoding=3, text=music_info.album))
            
            if music_info.track_number > 0:
                audio.tags.add(TRCK(encoding=3, text=str(music_info.track_number)))
            
            # 下载并添加封面
            if music_info.pic_url:
                try:
                    pic_response = requests.get(music_info.pic_url, timeout=10)
                    pic_response.raise_for_status()
                    audio.tags.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc='Cover',
                        data=pic_response.content
                    ))
                except:
                    pass  # 封面下载失败不影响主流程
            
            audio.save()
        except Exception as e:
            print(f"写入MP3标签失败: {e}")
    
    def _write_flac_tags(self, file_path: Path, music_info: MusicInfo) -> None:
        """写入FLAC标签"""
        try:
            audio = FLAC(str(file_path))
            
            audio['TITLE'] = music_info.name
            audio['ARTIST'] = music_info.artists
            audio['ALBUM'] = music_info.album

            if music_info.track_number > 0:
                audio['TRACKNUMBER'] = str(music_info.track_number)
            
            # 新增：发行时间（需要从音乐信息中获取publishTime）
            # 注意：需要确保music_info中包含publishTime字段（后续需在MusicInfo类中添加）
            if hasattr(music_info, 'publishTime') and music_info.publishTime:
                full_date = music_info.publishTime
                
                # 单独写入年份（提高兼容性）
                if '-' in full_date:
                    audio['YEAR'] = full_date.split('-')[0]  # 提取YYYY部分
                else:
                    audio['YEAR'] = full_date  # 若本身就是年份格式
                # 写入完整日期（标准DATE字段）
                audio['DATE'] = full_date.split('-')[0]  # 提取YYYY部分
            # 新增：歌词标签（使用自定义字段存储歌词和翻译歌词）
            if music_info.lyric:
                audio['LYRICS'] = music_info.lyric.strip()  # 原歌词
            if music_info.tlyric:
                audio['TRANSLATEDLYRICS'] = music_info.tlyric.strip()  # 翻译歌词

            # 下载并添加封面
            if music_info.pic_url:
                try:
                    pic_response = requests.get(music_info.pic_url, timeout=10)
                    pic_response.raise_for_status()
                    
                    from mutagen.flac import Picture
                    picture = Picture()
                    picture.type = 3  # Cover (front)
                    picture.mime = 'image/jpeg'
                    picture.desc = 'Cover'
                    picture.data = pic_response.content
                    audio.add_picture(picture)
                except:
                    pass  # 封面下载失败不影响主流程
            
            audio.save()
        except Exception as e:
            print(f"写入FLAC标签失败: {e}")
    
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

    
    def _write_music_tags_memory(self, audio_data: BytesIOType, music_info: MusicInfo, file_ext: str) -> BytesIOType:
        """在内存中写入音乐标签
        
        Args:
            audio_data: 内存中的音频数据流
            music_info: 音乐信息
            file_ext: 文件扩展名（.mp3/.flac/.m4a）
            
        Returns:
            写入标签后的音频数据流
        """
        try:
            # 1. 检查原始音频数据是否为空
            audio_data.seek(0, 2)  # 移到末尾
            data_size = audio_data.tell()  # 获取数据大小
            if data_size == 0:
                logger.error("原始音频数据为空，无法写入标签")
                return audio_data
            # 将BytesIO内容转换为mutagen可处理的文件对象
            audio_data.seek(0)  # 确保从开头读取
            temp_data = audio_data.read()  # 读取所有内容
            temp_io = BytesIO(temp_data)  # 创建临时IO用于处理
            
            if file_ext == '.mp3':
                self._write_mp3_tags_memory(temp_io, music_info)
            elif file_ext == '.flac':
                self._write_flac_tags_memory(temp_io, music_info)
            elif file_ext == '.m4a':
                self._write_m4a_tags_memory(temp_io, music_info)
            
            # 4. 验证写入后的数据是否有效
            temp_io.seek(0, 2)
            new_size = temp_io.tell()
            if new_size == 0:
                logger.error("标签写入后内存流为空，返回原始数据")
                audio_data.seek(0)
                return audio_data

            temp_io.seek(0)
            return temp_io
            
        except Exception as e:
            logger.error(f"内存写入标签失败: {str(e)}", exc_info=True)
            audio_data.seek(0)
            return audio_data

    def _write_mp3_tags_memory(self, io: BytesIOType, music_info: MusicInfo):
        """MP3内存标签写入"""
        try:
            # 关键：确保指针在开头，否则ID3可能读不到数据
            io.seek(0)
            logger.debug(f"MP3标签写入前，内存流位置: {io.tell()}")
            try:
                audio = ID3(io)  # 读取现有标签（若无则创建）
            except:
                audio = ID3()  # 新建标签
                
            # 基本标签
            audio["TIT2"] = TIT2(encoding=3, text=music_info.name)  # 标题
            audio["TPE1"] = TPE1(encoding=3, text=music_info.artist_string)  # 艺术家
            audio["TALB"] = TALB(encoding=3, text=music_info.album)  # 专辑
            audio["TDRC"] = TDRC(encoding=3, text=str(music_info.publishTime[:4]))  # 发行年份

            if music_info.track_number > 0:
                audio["TRCK"] = TRCK(encoding=3, text=str(music_info.track_number)) # 曲目编号
            
            # 专辑封面（如果有）
            if music_info.pic_url:
                try:
                    import requests
                    cover_response = requests.get(music_info.pic_url, timeout=10)
                    cover_response.raise_for_status()
                    if cover_response.status_code == 200:
                        audio["APIC"] = APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc=u'Cover',
                            data=cover_response.content
                        )
                    logger.debug("成功添加MP3封面")
                except Exception as e:
                    logger.error(f"获取MP3封面失败: {e}")

            # 关键：保存前确保指针在开头，显式指定fileobj
            io.seek(0)
            audio.save(fileobj=io)
            logger.debug(f"MP3标签保存成功，内存流位置: {io.tell()}")        
        except Exception as e:
            logger.error(f"MP3标签写入失败: {str(e)}", exc_info=True)

    def _write_flac_tags_memory(self, io: BytesIOType, music_info: MusicInfo):
        """写入FLAC标签"""
        try:
            # 确保指针在开头
            io.seek(0)
            logger.debug(f"FLAC标签写入前，内存流位置: {io.tell()}")
            audio = FLAC(io)
            
            audio['TITLE'] = music_info.name
            audio['ARTIST'] = music_info.artists
            audio['ALBUM'] = music_info.album

            if music_info.track_number > 0:
                audio['TRACKNUMBER'] = str(music_info.track_number)
            
            # 新增：发行时间（需要从音乐信息中获取publishTime）
            # 注意：需要确保music_info中包含publishTime字段（后续需在MusicInfo类中添加）
            if hasattr(music_info, 'publishTime') and music_info.publishTime:
                full_date = music_info.publishTime
                
                # 单独写入年份（提高兼容性）
                if '-' in full_date:
                    audio['YEAR'] = full_date.split('-')[0]  # 提取YYYY部分
                else:
                    audio['YEAR'] = full_date  # 若本身就是年份格式
                # 写入完整日期（标准DATE字段）
                audio['DATE'] = full_date.split('-')[0]  # 提取YYYY部分
            # 新增：歌词标签（使用自定义字段存储歌词和翻译歌词）
            if music_info.lyric:
                audio['LYRICS'] = music_info.lyric.strip()  # 原歌词
            if music_info.tlyric:
                audio['TRANSLATEDLYRICS'] = music_info.tlyric.strip()  # 翻译歌词

            # 下载并添加封面
            if music_info.pic_url:
                try:
                    pic_response = requests.get(music_info.pic_url, timeout=10)
                    pic_response.raise_for_status()
                    
                    from mutagen.flac import Picture
                    picture = Picture()
                    picture.type = 3  # Cover (front)
                    picture.mime = 'image/jpeg'
                    picture.desc = 'Cover'
                    picture.data = pic_response.content
                    audio.add_picture(picture)
                except Exception as e:
                    logger.error(f"获取FLAC封面失败: {e}")
            
            # 保存前重置指针
            io.seek(0)
            audio.save(fileobj=io)
            logger.debug(f"FLAC标签保存成功，内存流位置: {io.tell()}")
        except Exception as e:
            logger.error(f"FLAC标签写入失败: {str(e)}", exc_info=True)

    def _write_m4a_tags_memory(self, io: BytesIOType, music_info: MusicInfo):
        """写入M4A标签"""
        try:
            # 确保指针在开头
            io.seek(0)
            logger.debug(f"M4A标签写入前，内存流位置: {io.tell()}")
            audio = MP4(io)
            
            audio['\xa9nam'] = music_info.name
            audio['\xa9ART'] = music_info.artists
            audio['\xa9alb'] = music_info.album
            audio["\xa9day"] = str(music_info['publishTime'])[:4]  # 年份
            
            if music_info.track_number > 0:
                audio['trkn'] = [(music_info.track_number, 0)]
            
            # 下载并添加封面
            if music_info.pic_url:
                try:
                    pic_response = requests.get(music_info.pic_url, timeout=10)
                    pic_response.raise_for_status()
                    audio['covr'] = [pic_response.content]
                except Exception as e:
                    logger.error(f"获取M4A封面失败: {e}")
            
            # 保存前重置指针
            io.seek(0)
            audio.save(fileobj=io)
            logger.debug(f"M4A标签保存成功，内存流位置: {io.tell()}")
        except Exception as e:
            logger.error(f"M4A标签写入失败: {str(e)}", exc_info=True)

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