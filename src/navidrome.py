import re
import requests
import logging
from typing import Dict

class NavidromeClient:
    def __init__(self, host: str, username: str, password: str):
        self.navidrome_host = host
        self.navidrome_user = username
        self.navidrome_pass = password
        self.logger = logging.getLogger(__name__)

    # 辅助方法：生成空结果
    def _get_empty_result(self) -> dict:
        return {
            "exists": False,
            "album": "",
            "artists": "",
            "file_type": "",
            "file_size": 0,
            "file_size_formatted": "",
            "is_mp3": False
        }

    # 辅助方法：提取文件类型
    def _get_file_type(self,data):
        """
        提取文件类型，优先使用'suffix'字段，其次通过mime_type判断
        :param data: 包含文件信息的字典，可能包含'suffix'或'mime_type'字段
        :return: 文件后缀（如'flac'、'mp3'等）
        """
        # 1. 优先提取'suffix'字段
        if 'suffix' in data and data['suffix']:
            # 标准化后缀（去除点号、转为小写）
            suffix = data['suffix'].strip().lstrip('.').lower()
            if suffix:  # 确保后缀有效
                return suffix
        
        # 2. 若'suffix'不存在，通过mime_type映射
        mime_type = data.get('mime_type', '').lower()
        mime_map = {
            'audio/flac': 'flac',
            'audio/mpeg': 'mp3',
            'audio/wav': 'wav',
            'audio/aac': 'aac',
            'audio/ogg': 'ogg',
            'audio/x-m4a': 'm4a'
        }
        if mime_type in mime_map:
            return mime_map[mime_type]
        
        # 3. 最终fallback，默认返回未知类型
        return 'unknown'

    # 辅助方法：提取文件大小
    def _get_file_size(self, item: dict) -> int:
        raw_size = item.get('size') or item.get('fileSize') or 0
        try:
            return int(raw_size)
        except (ValueError, TypeError):
            return 0
    
    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes == 0:
            return "0B"
        
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(size_bytes)
        unit_index = 0
        
        while size >= 1024.0 and unit_index < len(units) - 1:
            size /= 1024.0
            unit_index += 1
        
        return f"{size:.2f}{units[unit_index]}"


    def _authenticate(self) -> None:
        """进行身份验证"""
        try:
            response = self.session.post(
                f"{self.host}/api/login",
                json={"username": self.username, "password": self.password}
            )
            response.raise_for_status()
            self.logger.info("Navidrome 认证成功")
        except Exception as e:
            self.logger.error(f"Navidrome 认证失败: {str(e)}")
            raise
    def navidrome_empty_result(self) -> dict:
        return self._get_empty_result()

    def navidrome_song_exists(self, title: str, artists: str, album: str) -> dict:
        """
        优化匹配逻辑：
        - 歌手名+歌曲名匹配，且格式不是MP3则存在；专辑名匹配不影响核心判定
        - 若匹配到的是MP3格式，视为不存在，继续查找其他格式
        - 支持多歌手匹配，返回完整歌手名
        """
        try:
            if not self.navidrome_host:
                self.logger.debug("Navidrome 主机地址未配置，跳过检查")
                return self._get_empty_result()

            # 清理主机地址
            clean_host = re.sub(r'^https?://', '', self.navidrome_host.strip())
            if not clean_host:
                self.logger.error("Navidrome 主机地址配置为空")
                return self._get_empty_result()
            base_url = f"http://{clean_host}"
            base_url = base_url[:-1] if base_url.endswith('/') else base_url

            # 认证信息
            username = self.navidrome_user or ""
            password = self.navidrome_pass or ""
            if not username or not password:
                self.logger.error("Navidrome 用户名或密码未配置")
                return self._get_empty_result()

            # 构建请求参数
            query = title.strip()
            params = {
                "u": username,
                "p": password,
                "v": "1.16.1",
                "c": "NeteaseDownloader",
                "f": "json",
                "query": query,
                "type": "song",
                "songCount": 20  # 适当增加候选数量
            }

            url = f"{base_url}/rest/search2"
            self.logger.debug(f"搜索 Navidrome: {url} (参数: {params})")

            # 发送请求
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            self.logger.debug(f"Navidrome 响应: {data}")

            # 解析候选歌曲
            candidates = []
            subsonic_resp = data.get("subsonic-response", {})
            if subsonic_resp.get("status") == "ok":
                search_result = subsonic_resp.get("searchResult2", {})
                candidates = search_result.get("song", []) or subsonic_resp.get("song", [])
                candidates = [candidates] if not isinstance(candidates, list) else candidates

            self.logger.debug(f"获取到 {len(candidates)} 条候选歌曲")

            # 预处理匹配条件
            title_target = title.strip().lower()
            album_target = (album or "").strip().lower()
            input_artists = [a.strip().lower() for a in re.split(r'[\/,;]', artists or '') if a.strip()]

            for item in candidates:
                # 提取候选歌曲信息
                nav_title = str(item.get('title', "")).strip().lower()
                nav_artist_full = str(item.get('artist', "")).strip()
                nav_artist_lower = nav_artist_full.lower()
                nav_album = str(item.get('album', "")).strip().lower()
                self.logger.debug(f"候选: {nav_title} - {nav_artist_full}（专辑: {nav_album}）")

                # 1. 歌曲名必须完全匹配
                if nav_title != title_target:
                    self.logger.debug(f"歌曲名不匹配: {nav_title} vs {title_target}")
                    continue

                # 2. 歌手名匹配（双向匹配逻辑）
                artist_match = False
                nav_artists_split = [a.strip().lower() for a in re.split(r'[\/,;]', nav_artist_lower) if a.strip()]
                
                if input_artists:
                    for in_artist in input_artists:
                        if in_artist in nav_artist_lower or any(nd in in_artist for nd in nav_artists_split):
                            artist_match = True
                            break
                else:
                    artist_match = bool(nav_artist_lower.strip())

                if not artist_match:
                    self.logger.debug(f"歌手名不匹配: {nav_artist_lower} vs {input_artists}")
                    continue

                # 3. 检查格式是否为MP3（核心修改点）
                file_type = self._get_file_type(item)
                is_mp3 = file_type.lower() == "mp3"
                if is_mp3:
                    self.logger.debug(f"匹配到但格式为MP3，视为不存在: {title} - {artists}")
                    continue  # 跳过MP3格式的匹配项，继续查找其他格式

                # 4. 非MP3格式且匹配，返回存在
                file_size = self._get_file_size(item)
                size_formatted = self._format_file_size(file_size) if file_size else ""
                album_match = (album_target == nav_album) if album_target else True

                self.logger.debug(
                    f"找到匹配歌曲（非MP3）: {title} - {artists} "
                    f"[专辑匹配: {album_match}, 格式: {file_type}, 大小: {size_formatted}]"
                )

                return {
                    "exists": True,
                    "album": str(item.get('album', "")).strip(),
                    "artists": nav_artist_full,
                    "file_type": file_type,
                    "file_size": file_size,
                    "file_size_formatted": size_formatted,
                    "is_mp3": is_mp3
                }

            self.logger.debug(f"未找到非MP3格式的匹配歌曲: {title} - {artists}")
            return self._get_empty_result()

        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP错误: {str(e)}，响应内容: {getattr(resp, 'text', '未知')}")
            return self._get_empty_result()
        except Exception as e:
            self.logger.error(f"Navidrome检查异常: {str(e)}")
            return self._get_empty_result()