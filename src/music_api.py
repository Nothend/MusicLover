"""网易云音乐API模块

提供网易云音乐相关API接口的封装，包括：
- 音乐URL获取
- 歌曲详情获取
- 歌词获取
- 搜索功能
- 歌单和专辑详情
- 二维码登录
"""
"""
  /// 接口
  // 音乐热歌榜接口地址  :  https://music.163.com/api/playlist/detail?id=3778678
  static const String musicApiUrl_host = "music.163.com";
  static const String musicApiUrl_path = "/api/playlist/detail";

  // 音乐搜索  http://musicapi.leanapp.cn/search?keywords=
  static const String musicSearchUrl_host = "musicapi.leanapp.cn";
  static const String musicSearchUrl_path = "/search";

  // 音乐评论  http://musicapi.leanapp.cn/comment/music?id=27588968&limit=1
  static const String musicCommentUrl_host = "musicapi.leanapp.cn";
  static const String musicCommentUrl_path = "/comment/music";

  // 音乐播放地址 https://api.imjad.cn/cloudmusic/?type=song&id=112878&br=128000
  // 音乐歌词    https://api.imjad.cn/cloudmusic/?type=lyric&id=112878&br=128000
  static const String musicPlayLyricUrl_host = "api.imjad.cn";
  static const String musicPlayLyricUrl_path = "/cloudmusic";

  // 个人歌单
  // http://music.163.com/api/user/playlist/?offset=0&limit=100&uid=1927677638
  static const String personalPlayListApiUrl_host = "music.163.com";
  static const String personalPlayListApiUrl_path = "/api/user/playlist";

  // 个人信息
  // https://music.163.com/api/v1/user/detail/1927677638
  static const String personalInfoUrl_host = "music.163.com";
  static const String personalInfoUrl_path = "/api/v1/user/detail/";

  // 歌单详情 https://music.163.com/api/playlist/detail?id=24381616
  static const String playlistDetailUrl_host = "music.163.com";
  static const String playlistDetailUrl_path = "/api/playlist/detail";

  // 歌单评论 http://musicapi.leanapp.cn/comment/playlist?id=1
  static const String playlistCommentUrl_host = "musicapi.leanapp.cn";
  static const String playlistCommentUrl_path = "/comment/playlist";

  // 精品歌单 http://musicapi.leanapp.cn/top/playlist/highquality/华语
  static const String playlistHighQualityUrl_host = "musicapi.leanapp.cn";
  static const String playlistHighQualityUrl_path = "/top/playlist/highquality";

  // 相似歌单  http://musicapi.leanapp.cn/simi/playlist?id=347230
  static const String playlistSimiUrl_host = "musicapi.leanapp.cn";
  static const String playlistSimiUrl_path = "/simi/playlist";

  // 歌手榜单  http://music.163.com/api/artist/list   http://musicapi.leanapp.cn/artist/list
  static const String singerRankUrl_host = "musicapi.leanapp.cn";
  static const String singerRankUrl_path = "/artist/list";

  // 歌手热门歌曲 http://music.163.com/api/artist/5781  歌手信息和热门歌曲
  static const String singerTopMusicUrl_host = "music.163.com";
  static const String singerTopMusicUrl_path = "/api/artist/";

  // 歌手专辑列表 http://music.163.com/api/artist/albums/3684  歌手id  http://musicapi.leanapp.cn/artist/album?id=6452&limit=30
  static const String singerAlbumUrl_host = "music.163.com";
  static const String singerAlbumUrl_path = "/api/artist/albums/";

  // 专辑详情  https://music.163.com/api/album/90743831   专辑id
  static const String albumDetailUrl_host = "music.163.com";
  static const String albumDetailUrl_path = "/api/album/";

  // 歌手描述 http://musicapi.leanapp.cn/artist/desc?id=6452
  static const String singerDescUrl_host = "musicapi.leanapp.cn";
  static const String singerDescUrl_path = "/artist/desc";

  // 歌曲MV  http://music.163.com/api/mv/detail?id=319104&type=mp4

"""
import base64
from io import BytesIO
import json
import urllib.parse
import time
from random import randrange
from typing import Dict, List, Optional, Tuple, Any
from hashlib import md5
from enum import Enum
import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from datetime import datetime

try:
    import qrcode
    from PIL import Image
except ImportError:
    qrcode = None
    Image = None

class QualityLevel(Enum):
    """音质等级枚举"""
    STANDARD = "standard"      # 标准音质
    EXHIGH = "exhigh"          # 极高音质
    LOSSLESS = "lossless"      # 无损音质
    HIRES = "hires"            # Hi-Res音质
    SKY = "sky"                # 沉浸环绕声
    JYEFFECT = "jyeffect"      # 高清环绕声
    JYMASTER = "jymaster"      # 超清母带


# 常量定义
class APIConstants:
    """API相关常量"""
    AES_KEY = b"e82ckenh8dichen8"
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36 Chrome/91.0.4472.164 NeteaseMusicDesktop/2.10.2.200154'
    REFERER = 'https://music.163.com/'
    
    # API URLs
    USER_ACCOUNT_API = "https://interface3.music.163.com/api/nuser/account/get"
    SONG_URL_V1 = "https://interface3.music.163.com/eapi/song/enhance/player/url/v1"
    SONG_DETAIL_V3 = "https://interface3.music.163.com/api/v3/song/detail"
    LYRIC_API = "https://interface3.music.163.com/api/song/lyric"
    SEARCH_API = 'https://music.163.com/api/cloudsearch/pc'
    PLAYLIST_DETAIL_API = 'https://music.163.com/api/v6/playlist/detail'
    ALBUM_DETAIL_API = 'https://music.163.com/api/v1/album/'
    QR_UNIKEY_API = 'https://interface3.music.163.com/eapi/login/qrcode/unikey'
    QR_LOGIN_API = 'https://interface3.music.163.com/eapi/login/qrcode/client/login'

    #// 个人歌单
    PERSONAL_PLAYLIST_API='https://music.163.com/api/user/playlist'

    QR_LOGIN_CHECK = 'https://music.163.com/login?csrf_token='

    
    # 默认配置
    DEFAULT_CONFIG = {
        "os": "pc",
        "appver": "",
        "osver": "",
        "deviceId": "pyncm!"
    }
    
    DEFAULT_COOKIES = {
        "os": "pc",
        "appver": "",
        "osver": "",
        "deviceId": "pyncm!"
    }


class CryptoUtils:
    """加密工具类"""
    
    @staticmethod
    def hex_digest(data: bytes) -> str:
        """将字节数据转换为十六进制字符串"""
        return "".join([hex(d)[2:].zfill(2) for d in data])
    
    @staticmethod
    def hash_digest(text: str) -> bytes:
        """计算MD5哈希值"""
        return md5(text.encode("utf-8")).digest()
    
    @staticmethod
    def hash_hex_digest(text: str) -> str:
        """计算MD5哈希值并转换为十六进制字符串"""
        return CryptoUtils.hex_digest(CryptoUtils.hash_digest(text))
    
    @staticmethod
    def encrypt_params(url: str, payload: Dict[str, Any]) -> str:
        """加密请求参数"""
        url_path = urllib.parse.urlparse(url).path.replace("/eapi/", "/api/")
        digest = CryptoUtils.hash_hex_digest(f"nobody{url_path}use{json.dumps(payload)}md5forencrypt")
        params = f"{url_path}-36cd479b6b5-{json.dumps(payload)}-36cd479b6b5-{digest}"
        
        # AES加密
        padder = padding.PKCS7(algorithms.AES(APIConstants.AES_KEY).block_size).padder()
        padded_data = padder.update(params.encode()) + padder.finalize()
        cipher = Cipher(algorithms.AES(APIConstants.AES_KEY), modes.ECB())
        encryptor = cipher.encryptor()
        enc = encryptor.update(padded_data) + encryptor.finalize()
        
        return CryptoUtils.hex_digest(enc)


class HTTPClient:
    """HTTP客户端类"""
    
    @staticmethod
    def post_request(url: str, params: str, cookies: Dict[str, str]) -> str:
        """发送POST请求并返回文本响应"""
        headers = {
            'User-Agent': APIConstants.USER_AGENT,
            'Referer': APIConstants.REFERER,
        }
        
        request_cookies = APIConstants.DEFAULT_COOKIES.copy()
        request_cookies.update(cookies)
        
        try:
            response = requests.post(url, headers=headers, cookies=request_cookies, 
                                   data={"params": params}, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise APIException(f"HTTP请求失败: {e}")
    
    @staticmethod
    def post_request_full(url: str, params: str, cookies: Dict[str, str]) -> requests.Response:
        """发送POST请求并返回完整响应对象"""
        headers = {
            'User-Agent': APIConstants.USER_AGENT,
            'Referer': APIConstants.REFERER,
        }
        
        request_cookies = APIConstants.DEFAULT_COOKIES.copy()
        request_cookies.update(cookies)
        
        try:
            response = requests.post(url, headers=headers, cookies=request_cookies, 
                                   data={"params": params}, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            raise APIException(f"HTTP请求失败: {e}")


class APIException(Exception):
    """API异常类"""
    pass


class NeteaseAPI:
    """网易云音乐API主类"""
    
    def __init__(self):
        self.http_client = HTTPClient()
        self.crypto_utils = CryptoUtils()
    
    def get_song_url(self, song_id: int, quality: str, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取歌曲播放URL
        
        Args:
            song_id: 歌曲ID
            quality: 音质等级 (standard, exhigh, lossless, hires, sky, jyeffect, jymaster)
            cookies: 用户cookies
            
        Returns:
            包含歌曲URL信息的字典
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            config = APIConstants.DEFAULT_CONFIG.copy()
            config["requestId"] = str(randrange(20000000, 30000000))
            
            payload = {
                'ids': [song_id],
                'level': quality,
                'encodeType': 'flac',
                'header': json.dumps(config),
            }
            
            if quality == 'sky':
                payload['immerseType'] = 'c51'
            
            params = self.crypto_utils.encrypt_params(APIConstants.SONG_URL_V1, payload)
            response_text = self.http_client.post_request(APIConstants.SONG_URL_V1, params, cookies)
            
            result = json.loads(response_text)
            if result.get('code') != 200:
                raise APIException(f"获取歌曲URL失败: {result.get('message', '未知错误')}")
            
            return result
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析响应数据失败: {e}")
    
    def get_song_detail(self, song_id: int) -> Dict[str, Any]:
        """获取歌曲详细信息
        
        Args:
            song_id: 歌曲ID
            
        Returns:
            包含歌曲详细信息的字典
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {'c': json.dumps([{"id": song_id, "v": 0}])}
            response = requests.post(APIConstants.SONG_DETAIL_V3, data=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取歌曲详情失败: {result.get('message', '未知错误')}")
            
            return result
        except requests.RequestException as e:
            raise APIException(f"获取歌曲详情请求失败: {e}")
        except json.JSONDecodeError as e:
            raise APIException(f"解析歌曲详情响应失败: {e}")
    
    def get_lyric(self, song_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取歌词信息
        
        Args:
            song_id: 歌曲ID
            cookies: 用户cookies
            
        Returns:
            包含歌词信息的字典
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {
                'id': song_id, 
                'cp': 'false', 
                'tv': '0', 
                'lv': '0', 
                'rv': '0', 
                'kv': '0', 
                'yv': '0', 
                'ytv': '0', 
                'yrv': '0'
            }
            
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.post(APIConstants.LYRIC_API, data=data, 
                                   headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取歌词失败: {result.get('message', '未知错误')}")
            
            return result
        except requests.RequestException as e:
            raise APIException(f"获取歌词请求失败: {e}")
        except json.JSONDecodeError as e:
            raise APIException(f"解析歌词响应失败: {e}")
    
    def search_music(self, keywords: str, cookies: Dict[str, str], limit: int = 10) -> List[Dict[str, Any]]:
        """搜索音乐
        
        Args:
            keywords: 搜索关键词
            cookies: 用户cookies
            limit: 返回数量限制
            
        Returns:
            歌曲信息列表
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {'s': keywords, 'type': 1, 'limit': limit}
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.post(APIConstants.SEARCH_API, data=data, 
                                   headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"搜索失败: {result.get('message', '未知错误')}")
            
            songs = []
            for item in result.get('result', {}).get('songs', []):
                song_info = {
                    'id': item['id'],
                    'name': item['name'],
                    'artists': '/'.join(artist['name'] for artist in item['ar']),
                    'album': item['al']['name'],
                    'picUrl': item['al']['picUrl'],
                    'publishTime': item['publishTime']
                }
                songs.append(song_info)
            
            return songs
        except requests.RequestException as e:
            raise APIException(f"搜索请求失败: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析搜索响应失败: {e}")
        
    def get_user_playlist(self, uid: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取用户的歌单列表详情
        
        Args:
            uid: 用户ID
            cookies: 用户登录态cookies
            
        Returns:
            包含处理后的歌单列表的字典，结构如下：
            {
                "total": int,  # 歌单总数
                "playlists": [
                    {
                        "id": int,  # 歌单ID
                        "name": str,  # 歌单名称
                        "track_count": int,  # 歌曲数量
                        "update_time": str,  # 歌单更新时间（YYYY-MMMM-DDDD）
                        "track_update_time": str  # 歌曲更新时间（YYYY-MMMM-DDDD）
                    },
                    ...
                ]
            }
            
        Raises:
            APIException: API调用失败或响应解析错误时抛出
        """
        try:
            # 构建请求参数
            data = {
                'uid': uid,
                'offset': 0,
                'limit': 20
            }
            
            # 构建请求头
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            # 发送POST请求
            response = requests.post(
                url=APIConstants.PERSONAL_PLAYLIST_API,
                data=data,
                headers=headers,
                cookies=cookies,
                timeout=30
            )
            response.raise_for_status()  # 抛出HTTP错误状态码
            
            # 解析响应JSON
            result = response.json()
            
            # 检查API返回状态
            if result.get('code') != 200:
                raise APIException(f"获取用户歌单失败: {result.get('message', '未知错误')}")
            
            # 提取歌单列表（确保为列表类型）
            playlists: List[Dict[str, Any]] = result.get('playlist', [])
            processed_playlists = []
            
            # 遍历处理每个歌单
            for playlist in playlists:
                # 转换时间戳（使用类内时间转换方法）
                update_time = self._timestamp_str_to_date(playlist.get('updateTime', ''))
                track_update_time = self._timestamp_str_to_date(playlist.get('trackUpdateTime', ''))
                
                # 封装处理后的歌单信息
                processed_playlist = {
                    'id': playlist.get('id'),
                    'name': playlist.get('name'),
                    'track_count': playlist.get('trackCount'),
                    'update_time': update_time,
                    'track_update_time': track_update_time
                }
                processed_playlists.append(processed_playlist)
            
            # 构建返回结果
            return {
                'total': len(processed_playlists),
                'playlists': processed_playlists
            }
            
        except requests.RequestException as e:
            raise APIException(f"获取用户歌单请求失败: {str(e)}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析用户歌单响应失败: {str(e)}")
        except Exception as e:
            raise APIException(f"处理用户歌单时发生未知错误: {str(e)}")
    
    def get_playlist_detail(self, playlist_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取歌单详情
        
        Args:
            playlist_id: 歌单ID
            cookies: 用户cookies
            
        Returns:
            歌单详情信息
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            data = {'id': playlist_id}
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.post(APIConstants.PLAYLIST_DETAIL_API, data=data, 
                                   headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取歌单详情失败: {result.get('message', '未知错误')}")
            
            playlist = result.get('playlist', {})
            # 网易云API的album.publishTime为13位毫秒级时间戳
            create_timestamp = playlist.get('createTime')
            # 转换为年月日格式（调用工具函数）
            create_time = self._timestamp_str_to_date(create_timestamp)
            info = {
                'id': playlist.get('id'),
                'name': playlist.get('name'),
                'createTime' : create_time,
                'coverImgUrl': playlist.get('coverImgUrl'),
                'creator': playlist.get('creator', {}).get('nickname', ''),
                'trackCount': playlist.get('trackCount'),
                'description': playlist.get('description', ''),
                'tracks': []
            }
            
            # 获取所有trackIds并分批获取详细信息
            track_ids = [str(t['id']) for t in playlist.get('trackIds', [])]
            for i in range(0, len(track_ids), 100):
                batch_ids = track_ids[i:i+100]
                song_data = {'c': json.dumps([{'id': int(sid), 'v': 0} for sid in batch_ids])}
                
                song_resp = requests.post(APIConstants.SONG_DETAIL_V3, data=song_data, 
                                        headers=headers, cookies=cookies, timeout=30)
                song_resp.raise_for_status()
                
                song_result = song_resp.json()
                for song in song_result.get('songs', []):
                    info['tracks'].append({
                        'id': song['id'],
                        'name': song['name'],
                        'artists': '/'.join(artist['name'] for artist in song['ar']),
                        'album': song['al']['name'],
                        'picUrl': song['al']['picUrl']
                    })
            
            return info
        except requests.RequestException as e:
            raise APIException(f"获取歌单详情请求失败: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析歌单详情响应失败: {e}")
    
    def get_album_detail(self, album_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
        """获取专辑详情
        
        Args:
            album_id: 专辑ID
            cookies: 用户cookies
            
        Returns:
            专辑详情信息
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            url = f'{APIConstants.ALBUM_DETAIL_API}{album_id}'
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            response = requests.get(url, headers=headers, cookies=cookies, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('code') != 200:
                raise APIException(f"获取专辑详情失败: {result.get('message', '未知错误')}")
            
            album = result.get('album', {})
            info = {
                'id': album.get('id'),
                'name': album.get('name'),
                'coverImgUrl': self.get_pic_url(album.get('pic')),
                'artist': album.get('artist', {}).get('name', ''),
                'publishTime': album.get('publishTime'),
                'description': album.get('description', ''),
                'songs': []
            }
            
            for song in result.get('songs', []):
                info['songs'].append({
                    'id': song['id'],
                    'name': song['name'],
                    'artists': '/'.join(artist['name'] for artist in song['ar']),
                    'album': song['al']['name'],
                    'picUrl': self.get_pic_url(song['al'].get('pic'))
                })
            
            return info
        except requests.RequestException as e:
            raise APIException(f"获取专辑详情请求失败: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析专辑详情响应失败: {e}")
    
    def netease_encrypt_id(self, id_str: str) -> str:
        """网易云加密图片ID算法
        
        Args:
            id_str: 图片ID字符串
            
        Returns:
            加密后的字符串
        """
        import base64
        import hashlib
        
        magic = list('3go8&$8*3*3h0k(2)2')
        song_id = list(id_str)
        
        for i in range(len(song_id)):
            song_id[i] = chr(ord(song_id[i]) ^ ord(magic[i % len(magic)]))
        
        m = ''.join(song_id)
        md5_bytes = hashlib.md5(m.encode('utf-8')).digest()
        result = base64.b64encode(md5_bytes).decode('utf-8')
        result = result.replace('/', '_').replace('+', '-')
        
        return result
    
    def is_cookie_valid(self, cookies: Dict[str, str]) -> bool:
        """检查Cookie是否有效"""
        try:
            # 若未传入cookies，直接返回无效
            if not cookies:
                return False
            
            # 调用用户账号信息接口验证登录状态
            headers = {
                'User-Agent': APIConstants.USER_AGENT,
                'Referer': APIConstants.REFERER
            }
            
            # 发送请求（该接口无需复杂参数，仅需登录态Cookie）
            response = requests.post(
                APIConstants.USER_ACCOUNT_API,
                headers=headers,
                cookies=cookies,
                timeout=30
            )
            response.raise_for_status()  # 抛出HTTP错误（如403、500等）
            
            result = response.json()
            
            # 验证响应：code=200且包含用户信息（profile字段）则视为有效
            if result.get('code') == 200 and result.get('profile') is not None:
                return True
            else:
                # 打印无效原因（调试用，可保留或删除）
                if result.get('code') != 200:
                    print(f"Cookie无效：响应码非200（实际：{result.get('code')}）")
                else:
                    print(f"Cookie无效：profile为None（{result.get('profile')}）")
                return False
                
        except requests.RequestException as e:
            print(f"Cookie验证请求失败: {e}")
            return False
        except json.JSONDecodeError as e:
            print(f"解析验证响应失败: {e}")
            return False
        except Exception as e:
            print(f"Cookie验证发生未知错误: {e}")
            return False
    
    def get_pic_url(self, pic_id: Optional[int], size: int = 300) -> str:
        """获取网易云加密歌曲/专辑封面直链
        
        Args:
            pic_id: 封面ID
            size: 图片尺寸
            
        Returns:
            图片URL
        """
        if pic_id is None:
            return ''
        
        enc_id = self.netease_encrypt_id(str(pic_id))
        return f'https://p3.music.126.net/{enc_id}/{pic_id}.jpg?param={size}y{size}'

    def _timestamp_str_to_date(self, timestamp_int: int) -> str:
        """
        将整数时间戳（10-13位）转换为YYYY-MM-DD格式
        
        Args:
            timestamp_int: 整数时间戳（如1305388800（10位秒级）、984240000007（12位毫秒级）、1620000000000（13位毫秒级））
            
        Returns:
            格式化后的日期字符串，转换失败返回空字符串
        """
        try:
            # 1. 统一转换为毫秒级时间戳（根据实际值判断是否为秒级）
            # 阈值：5e11毫秒 ≈ 1985年，小于该值的10-12位可能是秒级
            if timestamp_int < 10**10:
                # 小于10位：无效
                return ""
            elif timestamp_int < 5 * 10**11:
                # 10-11位且小于5e11：视为秒级，转换为毫秒级（×1000）
                timestamp_int *= 1000
            # 12-13位且>=5e11：视为毫秒级，不转换（保持原数）
            
            # 2. 验证时间范围（1970-01-01 ~ 2100-12-31）
            min_ts = 0  # 1970-01-01 00:00:00（毫秒级）
            max_ts = 4102444799000  # 2100-12-31 23:59:59（毫秒级，修正后的值）
            if not (min_ts <= timestamp_int <= max_ts):
                return ""
            
            # 3. 转换为日期（毫秒级→秒级）
            return datetime.fromtimestamp(timestamp_int / 1000).strftime("%Y-%m-%d")
        
        except (ValueError, TypeError, OSError):
            return ""

class QRLoginManager:
    """二维码登录管理器"""
    
    def __init__(self):
        self.http_client = HTTPClient()
        self.crypto_utils = CryptoUtils()
    
    def generate_qr_key(self) -> Optional[str]:
        """生成二维码的key
        
        Returns:
            成功返回unikey，失败返回None
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            config = APIConstants.DEFAULT_CONFIG.copy()
            config["requestId"] = str(randrange(20000000, 30000000))
            
            payload = {
                'type': 1,
                'header': json.dumps(config)
            }
            
            params = self.crypto_utils.encrypt_params(APIConstants.QR_UNIKEY_API, payload)
            response = self.http_client.post_request_full(APIConstants.QR_UNIKEY_API, params, {})
            
            result = json.loads(response.text)
            if result.get('code') == 200:
                return result.get('unikey')
            else:
                raise APIException(f"生成二维码key失败: {result.get('message', '未知错误')}")
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析二维码key响应失败: {e}")
    
    def create_qr_code(self) -> Dict[str, Any]:
        """创建登录二维码并返回base64格式图片
        
        Returns:
            字典包含success状态、qr_key、qr_base64和消息
        """
        try:
            if not qrcode or not Image:
                return {
                    'success': False, 
                    'message': '请安装qrcode和PIL库: pip install qrcode pillow'
                }
            
            # 获取unikey
            unikey = self.generate_qr_key()
            if not unikey:
                return {'success': False, 'message': '生成二维码key失败'}
            
            self.qr_key = unikey  # 保存qr_key
            
            # 创建二维码图片
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            # 二维码内容：网易云音乐登录链接
            qr_content = f'https://music.163.com/login?codekey={unikey}'
            qr.add_data(qr_content)
            qr.make(fit=True)
            
            # 生成图片（RGB模式，白色背景，黑色前景）
            img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
            
            # 将图片保存到内存字节流
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='PNG')  # 保存为PNG格式
            img_byte_arr.seek(0)  # 重置文件指针
            
            # 转换为base64
            qr_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
            self.qr_img_base64 = qr_base64
            
            return {
                'success': True,
                'qr_key': unikey,
                'qr_base64': qr_base64,
                'message': '二维码生成成功，请使用网易云音乐APP扫描'
            }
            
        except Exception as e:
            return {'success': False, 'message': f'创建二维码失败: {str(e)}'}

    def create_qr_login(self) -> Optional[str]:
        """创建登录二维码并在控制台显示
        
        Returns:
            成功返回unikey，失败返回None
        """
        try:
            import qrcode
            
            unikey = self.generate_qr_key()
            if not unikey:
                print("生成二维码key失败")
                return None
            
            # 创建二维码
            qr = qrcode.QRCode()
            qr.add_data(f'https://music.163.com/login?codekey={unikey}')
            qr.make(fit=True)
            
            # 在控制台显示二维码
            qr.print_ascii(tty=True)
            print("\n请使用网易云音乐APP扫描上方二维码登录")
            return unikey
        except ImportError:
            print("请安装qrcode库: pip install qrcode")
            return None
        except Exception as e:
            print(f"创建二维码失败: {e}")
            return None
    
    def check_qr_login(self, unikey: str) -> Tuple[int, Dict[str, str]]:
        """检查二维码登录状态
        
        Args:
            unikey: 二维码key
            
        Returns:
            (登录状态码, cookie字典)
            
        Raises:
            APIException: API调用失败时抛出
        """
        try:
            config = APIConstants.DEFAULT_CONFIG.copy()
            config["requestId"] = str(randrange(20000000, 30000000))
            
            payload = {
                'key': unikey,
                'type': 1,
                'header': json.dumps(config)
            }
            
            params = self.crypto_utils.encrypt_params(APIConstants.QR_LOGIN_API, payload)
            response = self.http_client.post_request_full(APIConstants.QR_LOGIN_API, params, {})
            
            result = json.loads(response.text)
            cookie_dict = {}
            
            if result.get('code') == 803:
                # 登录成功，提取cookie
                all_cookies = response.headers.get('Set-Cookie', '').split(', ')
                for cookie_str in all_cookies:
                    if 'MUSIC_U=' in cookie_str:
                        cookie_dict['MUSIC_U'] = cookie_str.split('MUSIC_U=')[1].split(';')[0]
            
            return result.get('code', -1), cookie_dict
        except (json.JSONDecodeError, KeyError) as e:
            raise APIException(f"解析登录状态响应失败: {e}")
    
    def check_login_status(self, qr_key: str) -> Dict[str, Any]:
        """检查二维码登录状态"""
        try:
            config = APIConstants.DEFAULT_CONFIG.copy()
            config["requestId"] = str(randrange(20000000, 30000000))
            
            payload = {
                'key': qr_key,
                'type': 1,
                'header': json.dumps(config)
            }
            
            params = self.crypto_utils.encrypt_params(APIConstants.QR_LOGIN_API, payload)
            response = self.http_client.post_request_full(APIConstants.QR_LOGIN_API, params, {})
            
            result = json.loads(response.text)
            cookie_dict = {}
            
            self.login_status = result.get('code', -1)

            # 状态码说明：
            # 800 - 二维码已过期
            # 801 - 等待扫码
            # 802 - 已扫码待确认
            # 803 - 登录成功
            
            res = {
                'success': True,
                'status_code': self.login_status,
                'message': self._get_status_message(self.login_status)
            }

            if result.get('code') == 803:
                # 登录成功，提取cookie
                all_cookies = response.headers.get('Set-Cookie', '').split(', ')
                for cookie_str in all_cookies:
                    if 'MUSIC_U=' in cookie_str:
                        cookie_dict['MUSIC_U'] = cookie_str.split('MUSIC_U=')[1].split(';')[0]

                res['cookie'] = cookie_dict['MUSIC_U']
            return res
           
        except Exception as e:
            return {'success': False, 'message': f'检查登录状态时发生错误：{str(e)}'}
    
    def _get_status_message(self, status_code: int) -> str:
        """根据状态码返回对应的消息"""
        messages = {
            800: '二维码已过期',
            801: '等待扫码中...',
            802: '已扫码，请在手机上确认',
            803: '登录成功'
        }
        return messages.get(status_code, f'未知状态：{status_code}')

    def qr_login(self) -> Optional[str]:
        """完整的二维码登录流程
        
        Returns:
            成功返回cookie字符串，失败返回None
        """
        try:
            unikey = self.create_qr_login()
            if not unikey:
                return None
            
            while True:
                code, cookies = self.check_qr_login(unikey)
                
                if code == 803:
                    print("\n登录成功！")
                    return f"MUSIC_U={cookies['MUSIC_U']};os=pc;appver=8.9.70;"
                elif code == 801:
                    print("\r等待扫码...", end='')
                elif code == 802:
                    print("\r扫码成功，请在手机上确认登录...", end='')
                else:
                    print(f"\n登录失败，错误码：{code}")
                    return None
                
                time.sleep(2)
        except KeyboardInterrupt:
            print("\n用户取消登录")
            return None
        except Exception as e:
            print(f"\n登录过程中发生错误: {e}")
            return None

    

# 向后兼容的函数接口
def url_v1(song_id: int, level: str, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取歌曲URL（向后兼容）"""
    api = NeteaseAPI()
    return api.get_song_url(song_id, level, cookies)


def name_v1(song_id: int) -> Dict[str, Any]:
    """获取歌曲详情（向后兼容）"""
    api = NeteaseAPI()
    return api.get_song_detail(song_id)


def lyric_v1(song_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取歌词（向后兼容）"""
    api = NeteaseAPI()
    return api.get_lyric(song_id, cookies)


def search_music(keywords: str, cookies: Dict[str, str], limit: int = 10) -> List[Dict[str, Any]]:
    """搜索音乐（向后兼容）"""
    api = NeteaseAPI()
    return api.search_music(keywords, cookies, limit)


def playlist_detail(playlist_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取歌单详情（向后兼容）"""
    api = NeteaseAPI()
    return api.get_playlist_detail(playlist_id, cookies)

def user_playlist(uid: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取用户（向后兼容）"""
    api = NeteaseAPI()
    return api.get_user_playlist(uid, cookies)


def album_detail(album_id: int, cookies: Dict[str, str]) -> Dict[str, Any]:
    """获取专辑详情（向后兼容）"""
    api = NeteaseAPI()
    return api.get_album_detail(album_id, cookies)


def get_pic_url(pic_id: Optional[int], size: int = 300) -> str:
    """获取图片URL（向后兼容）"""
    api = NeteaseAPI()
    return api.get_pic_url(pic_id, size)


def qr_login() -> Optional[str]:
    """二维码登录（向后兼容）"""
    manager = QRLoginManager()
    return manager.qr_login()


if __name__ == "__main__":
    # 测试代码
    print("网易云音乐API模块")
    print("支持的功能:")
    print("- 歌曲URL获取")
    print("- 歌曲详情获取")
    print("- 歌词获取")
    print("- 音乐搜索")
    print("- 歌单详情")
    print("- 专辑详情")
    print("- 二维码登录")
