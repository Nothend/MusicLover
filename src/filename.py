"""下载文件名相关的纯函数：文件名清洗 + 按 URL/Content-Type 推断扩展名。

原先这两个函数寄居在 music_downloader.MusicDownloader 上，但本项目改为纯前端下载后，
服务端不再落地/写标签，music_downloader 整个删除，只剩这两个无状态纯函数被
main.build_download_filename 复用，故独立到此模块。
"""

import re

# 文件名非法字符（Windows/类 Unix 通用），命中一律替换为 ' & '
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename(filename: str) -> str:
    """清理文件名：替换非法字符、去除首尾空格与点、限制长度。空则回退 'unknown'。"""
    filename = _ILLEGAL_CHARS.sub(' & ', filename)
    filename = filename.strip(' .')
    if len(filename) > 200:
        filename = filename[:200]
    return filename or "unknown"


def file_extension(url: str, content_type: str = "") -> str:
    """按下载 URL、其次 Content-Type 推断扩展名（.flac/.mp3/.m4a），无法判断默认 .mp3。"""
    lowered = url.lower()
    if '.flac' in lowered:
        return '.flac'
    if '.mp3' in lowered:
        return '.mp3'
    if '.m4a' in lowered:
        return '.m4a'

    content_type = content_type.lower()
    if 'flac' in content_type:
        return '.flac'
    if 'mpeg' in content_type or 'mp3' in content_type:
        return '.mp3'
    if 'mp4' in content_type or 'm4a' in content_type:
        return '.m4a'

    return '.mp3'
