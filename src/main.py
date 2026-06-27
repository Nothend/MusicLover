"""网易云音乐API服务主程序

提供网易云音乐相关API服务,包括:
- 歌曲信息获取
- 音乐搜索
- 歌单和专辑详情
- 音乐下载
- 健康检查
"""

import logging
import os
import sys
import time
import traceback
import ipaddress
import requests
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from urllib.parse import quote, urlparse
from flask import Flask, jsonify, request, send_file, render_template, Response
from config import Config
from navidrome import NavidromeClient
from logger import setup_logger
from stats import StatsTracker
from notifier import start_daily_notifier

from flask_limiter import Limiter

try:
    from music_api import (
        NeteaseAPI, APIException, QualityLevel,QRLoginManager,
        url_v1, name_v1, lyric_v1, search_music, 
        playlist_detail, album_detail,user_playlist
    )
    from cookie_manager import CookieManager, CookieException
    from music_downloader import MusicDownloader, DownloadException, AudioFormat
except ImportError as e:
    print(f"导入模块失败: {e}")
    print("请确保所有依赖模块存在且可用")
    sys.exit(1)


# 支持的音质等级（取自 QualityLevel 枚举，避免在各路由重复硬编码同一份列表）
VALID_QUALITIES = [q.value for q in QualityLevel]


@dataclass
class APIConfig:
    """API配置类"""
    host: str = '0.0.0.0'
    port: int = 5000
    debug: bool = False
    downloads_dir: str = 'downloads'
    max_file_size: int = 500 * 1024 * 1024  # 500MB
    request_timeout: int = 30
    log_level: str = 'INFO'
    cors_origins: str = '*'


class APIResponse:
    """API响应工具类"""
    
    @staticmethod
    def success(data: Any = None, message: str = 'success', status_code: int = 200) -> Tuple[Dict[str, Any], int]:
        """成功响应"""
        response = {
            'status': status_code,
            'success': True,
            'message': message
        }
        if data is not None:
            response['data'] = data
        return response, status_code
    
    @staticmethod
    def error(message: str, status_code: int = 400, error_code: str = None) -> Tuple[Dict[str, Any], int]:
        """错误响应"""
        response = {
            'status': status_code,
            'success': False,
            'message': message
        }
        if error_code:
            response['error_code'] = error_code
        return response, status_code


class MusicAPIService:
    """音乐API服务类"""
    
    def __init__(self, user_config:Config):
        self._user_config=user_config
        self.cookie_manager = CookieManager(user_config)
        self.netease_api = NeteaseAPI()
        self.qr_manager=QRLoginManager()
        
        self.use_navidrome=user_config.is_enabled('NAVIDROME')
        # Navidrome 客户端无状态，启用时构建一次复用即可，避免每个请求/每首歌重复创建
        self.navidrome: Optional[NavidromeClient] = None
        if self.use_navidrome:
            self.navidrome = NavidromeClient(
                user_config.get_nested("NAVIDROME.NAVIDROME_HOST"),
                user_config.get_nested("NAVIDROME.NAVIDROME_USER"),
                user_config.get_nested("NAVIDROME.NAVIDROME_PASS"),
            )
        self.quality_level = self._user_config.get("QUALITY_LEVEL", "lossless")
        # 创建下载目录
        self.downloads_path = Path("/app/downloads")
        self.downloads_path.mkdir(exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"下载目录已设置为: /app/downloads")
        self.logger.info(f"下载音乐品质已设置为: { {"standard": "标准", "exhigh": "极高", "lossless": "无损", "hires": "Hi-Res", "sky": "沉浸环绕声", "jyeffect": "高清环绕声", "jymaster": "超清母带"}.get (self.quality_level, "未知品质")}")
        self.downloader = MusicDownloader(self.cookie_manager.parse_cookie_string(self.cookie_manager.cookie_string), "/app/downloads")
    @property
    def user_config(self) -> Config:
        return self._user_config
    
    def _get_cookies(self) -> Dict[str, str]:
        """获取Cookie"""
        try:
            cookie_str = self.cookie_manager.cookie_string
            return self.cookie_manager.parse_cookie_string(cookie_str)
        except CookieException as e:
            self.logger.warning(f"获取Cookie失败: {e}")
            return {}
        except Exception as e:
            self.logger.error(f"Cookie处理异常: {e}")
            return {}
    
    def _extract_music_id(self, id_or_url: str) -> str:
        """提取音乐ID"""
        try:
            # 处理短链接
            if '163cn.tv' in id_or_url:
                response = requests.get(id_or_url, allow_redirects=False, timeout=10)
                id_or_url = response.headers.get('Location', id_or_url)
            
            # 处理网易云链接
            if 'music.163.com' in id_or_url:
                index = id_or_url.find('id=') + 3
                if index > 2:
                    return id_or_url[index:].split('&')[0]
            
            # 直接返回ID
            return str(id_or_url).strip()
            
        except Exception as e:
            self.logger.error(f"提取音乐ID失败: {e}")
            return str(id_or_url).strip()
    
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
    
    def _get_quality_display_name(self, quality: str) -> str:
        """获取音质显示名称"""
        quality_names = {
            'standard': "标准音质",
            'exhigh': "极高音质", 
            'lossless': "无损音质",
            'hires': "Hi-Res音质",
            'sky': "沉浸环绕声",
            'jyeffect': "高清环绕声",
            'jymaster': "超清母带"
        }
        return quality_names.get(quality, f"未知音质({quality})")
    
    def _validate_request_params(self, required_params: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], int]]:
        """验证请求参数"""
        for param_name, param_value in required_params.items():
            if not param_value:
                return APIResponse.error(f"参数 '{param_name}' 不能为空", 400)
        return None
    
    def _safe_get_request_data(self) -> Dict[str, Any]:
        """安全获取请求数据"""
        try:
            if request.method == 'GET':
                return dict(request.args)
            else:
                # 优先使用JSON数据，然后是表单数据
                json_data = request.get_json(silent=True) or {}
                form_data = dict(request.form)
                # 合并数据，JSON优先
                return {**form_data, **json_data}
        except Exception as e:
            self.logger.error(f"获取请求数据失败: {e}")
            return {}

    # 辅助方法：生成空结果
    def get_empty_result(self) -> dict:
        return {
            "exists": False,
            "album": "",
            "artists": "",
            "file_type": "",
            "file_size": 0,
            "file_size_formatted": "",
            "is_mp3": False
        }

    def navidrome_status(self, name: str, artists: str, album: str) -> dict:
        """查询单曲在 Navidrome 库内的存在性，统一收敛各路由的重复逻辑。

        未启用 Navidrome 或查询异常时，返回与正常结果同构的空字典，保证响应格式一致。
        """
        if self.use_navidrome and self.navidrome:
            try:
                return self.navidrome.navidrome_song_exists(name, artists, album)
            except Exception as e:
                self.logger.error(f"Navidrome 检查失败: {e}")
        return self.get_empty_result()




    
    
    
# 创建Flask应用和服务实例
user_config=Config()
# 显式指定 static/templates 绝对路径，避免 Docker 中工作目录差异导致 CSS/JS 加载失败
current_dir = Path(__file__).parent
app = Flask(__name__,
            static_folder=str(current_dir / 'static'),
            template_folder=str(current_dir / 'templates'))
api_service = MusicAPIService(user_config)
APP_VERSION = os.getenv("APP_VERSION", "unknown")


def _parse_allowed_origins(raw: str) -> frozenset:
    """把配置里的来源列表解析成纯域名(去协议、保留端口)集合。"""
    domains = set()
    for origin in (raw or '').split(','):
        origin = origin.strip()
        if not origin:
            continue
        parsed = urlparse(origin)
        domains.add(parsed.netloc if parsed.netloc else origin)
    return frozenset(domains)


# 来源白名单启动时解析一次，避免每个请求都重复 split + urlparse（before_request 是热路径）
ALLOWED_ORIGINS = _parse_allowed_origins(user_config.allowed_origins)

# 使用统计：当期去重访问 IP + 下载歌曲数，每日 20:00 由 Bark 推送
stats_tracker = StatsTracker(user_config.stats_file)
# 这些路径不计入“使用人数”（探活/静态资源/纯信息接口）
STATS_IGNORE_PATHS = {"/health", "/favicon.ico", "/api/info", "/api/stats"}


def _client_ip() -> str:
    """获取真实客户端 IP：优先 X-Forwarded-For 首跳（站点走了反代），否则 remote_addr。"""
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or ''

# 初始化频率限制器（关键补充）
limiter = Limiter(
    # 基于“真实客户端 IP”限流。站点在反向代理后面，request.remote_addr 是代理的 IP，
    # 若用它做 key，会把所有访客算到同一个 IP 上、共用同一个限流桶——只要全站累计请求
    # 超过 200/hour 或某路由的分钟限额，所有人（无论解析单曲还是歌单）都会被 429。
    # 这里复用与统计一致的 _client_ip（取 X-Forwarded-For 首跳），让每个访客各自独立计数。
    _client_ip,
    app=app,
    default_limits=[user_config.rate_limit],  # 使用配置中的频率限制（如"200/hour"）
    storage_uri=user_config.rate_limit_storage,  # 可配置：默认 memory://，生产可设 redis://host:6379
    strategy="fixed-window",  # 固定窗口计数策略
    # 容错：当后端存储（如 redis）不可达时，自动退回进程内存限流，
    # 避免 redis 宕机/配错导致所有受保护接口直接 500
    in_memory_fallback_enabled=True
)


@app.before_request
def before_request():
    """请求前处理：包含日志记录和安全检查"""
    # 1. 定义不需要身份验证的路径列表
    #allowed_paths = [
    #    '/static',
    #    '/Playlist',  # <--- 添加这一行
    #    '/song',     # <--- 可能还有登录页等
    #    '/search',   # <--- 可能还有注册页等
    #    '/album',   # <--- 可能还有注册页等
    #    '/download',   # <--- 可能还有注册页等\
    #    '/song/detail',  # <--- 可能还有注册页等
    #    '/api/check-cookie'
    #]
    
    # 2. 检查当前请求路径是否在白名单内
    #for path in allowed_paths:
    #    if request.path.startswith(path):
    #        return None  # 直接放行，不执行后续验证逻辑
    # 1. 记录请求信息（原有逻辑）
    api_service.logger.info(
        f"{request.method} {request.path} - IP: {request.remote_addr} - "
        f"User-Agent: {request.headers.get('User-Agent', 'Unknown')}"
    )

    # 2. 安全检查逻辑
    # 2.1 先检查IP白名单（白名单内的IP直接放行）
    client_ip = request.remote_addr
    try:
        client_ip_obj = ipaddress.ip_address(client_ip)
        for ip in user_config.ip_whitelist:
            if client_ip_obj in ipaddress.ip_network(ip, strict=False):
                return None  # IP在白名单内，直接放行
    except ValueError:
        api_service.logger.warning(f"无效的IP白名单配置或客户端IP: {user_config.ip_whitelist} / {client_ip}")

    # 2.2 跳过公开接口
    if any(request.path == ep for ep in user_config.public_endpoints):
        return None

    # 3. 验证请求来源（白名单已在启动时解析为 ALLOWED_ORIGINS，此处直接复用）
    # 3.2 获取请求的Referer和Origin（同样去除协议）
    referer = request.headers.get('Referer', '')
    origin = request.headers.get('Origin', '')

    # 解析Referer的域名（去除协议）
    referer_domain = ''
    if referer:
        parsed_referer = urlparse(referer)
        referer_domain = parsed_referer.netloc  # 例如 https://dm.jfjt.cc → netloc是dm.jfjt.cc

    # 解析Origin的域名（去除协议，Origin本身通常不带路径，直接是域名）
    origin_domain = ''
    if origin:
        parsed_origin = urlparse(origin)
        origin_domain = parsed_origin.netloc if parsed_origin.netloc else origin

    # 3.3 同源放行：网页调用自己后端时（Referer/Origin 的 host 等于请求自身 Host）始终放行。
    # 来源校验的目的只是拦截第三方盗链，自部署用户用任意域名/IP 访问都应正常使用，
    # 不再依赖 ALLOWED_ORIGINS 是否预先配置了该域名。
    self_hosts = {request.host}
    forwarded_host = request.headers.get('X-Forwarded-Host', '')
    if forwarded_host:
        self_hosts.update(h.strip() for h in forwarded_host.split(',') if h.strip())

    # 3.4 严格匹配：Referer或Origin的域名完全等于允许的域名（不匹配子域名），或为同源请求
    is_from_allowed_origin = (
        referer_domain in ALLOWED_ORIGINS  # Referer域名完全匹配
        or origin_domain in ALLOWED_ORIGINS  # Origin域名完全匹配
        or (referer_domain and referer_domain in self_hosts)  # 同源 Referer
        or (origin_domain and origin_domain in self_hosts)    # 同源 Origin
    )

    # 4. 来源合法则放行，否则验证API密钥
    if is_from_allowed_origin:
        return None

    # 非合法来源，验证API密钥
    api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if not api_key or api_key != user_config.api_key:
        return APIResponse.error(
            "未授权访问：请通过官方网页使用，或提供有效的API密钥", 
            status_code=401, 
            error_code="Unauthorized"
        )


@app.after_request
def after_request(response: Response) -> Response:
    """请求后处理 - 设置CORS头"""
    response.headers.add('Access-Control-Allow-Origin', user_config.cors_origins)
    # 补充允许X-API-Key头（关键修改）
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    response.headers.add('Access-Control-Max-Age', '3600')

    # 统计“使用人数”：仅记录成功(<400)且非探活/静态的请求来源 IP（去重）
    try:
        path = request.path
        if (response.status_code < 400
                and path not in STATS_IGNORE_PATHS
                and not path.startswith('/static')):
            stats_tracker.record_visit(_client_ip())
    except Exception as e:
        api_service.logger.debug(f"记录访问统计失败(忽略): {e}")

    return response

@app.errorhandler(400)
def handle_bad_request(e):
    """处理400错误"""
    return APIResponse.error("请求参数错误", 400)


@app.errorhandler(404)
def handle_not_found(e):
    """处理404错误"""
    return APIResponse.error("请求的资源不存在", 404)


@app.errorhandler(500)
def handle_internal_error(e):
    """处理500错误"""
    api_service.logger.error(f"服务器内部错误: {e}")
    return APIResponse.error("服务器内部错误", 500)

@app.route('/')
def index():
    # 将版本号传递到模板
    return render_template("index.html", app_version=APP_VERSION)

@app.route('/api/check-password', methods=['GET'])
@limiter.limit("30/minute")  # 每分钟最多30次请求
def check_password() -> str:
    # 获取用户输入的密码
    user_password = request.args.get('password', '')
    
    # 从环境变量获取正确密码
    qr_password = user_config.qr_password
    
    # 验证密码
    if user_password.strip() == str(qr_password).strip():
        return jsonify({
            'success': True,
            'message': '密码验证成功'
        })
    else:
        return jsonify({
            'success': False,
            'message': '密码错误'
        })


@app.route('/health', methods=['GET'])
@limiter.limit("10/minute")  # 每分钟最多10次请求
def health_check():
    """健康检查API"""
    try:
        # 检查Cookie状态
        cookie_status = api_service.cookie_manager.is_cookie_valid()
        
        health_info = {
            'service': 'running',
            'timestamp': int(time.time()) if 'time' in sys.modules else None,
            'cookie_status': 'valid' if cookie_status else 'invalid',
            'downloads_dir': str(api_service.downloads_path.absolute()),
            'version': '2.0.0'
        }
        
        return APIResponse.success(health_info, "API服务运行正常")
        
    except Exception as e:
        api_service.logger.error(f"健康检查失败: {e}")
        return APIResponse.error(f"健康检查失败: {str(e)}", 500)


@app.route('/song', methods=['GET', 'POST'])
@app.route('/Song_V1', methods=['GET', 'POST'])  # 向后兼容
@limiter.limit("60/minute")  # 每分钟最多30次请求
def get_song_info():
    """获取歌曲信息API"""
    try:
        # 获取请求参数
        data = api_service._safe_get_request_data()
        song_ids = data.get('ids') or data.get('id')
        url = data.get('url')
        level = data.get('level', 'lossless')
        info_type = data.get('type', 'url')
        
        # 参数验证
        if not song_ids and not url:
            return APIResponse.error("必须提供 'ids'、'id' 或 'url' 参数")
        
        # 提取音乐ID
        music_id = api_service._extract_music_id(song_ids or url)
        
        # 验证音质参数
        if level not in VALID_QUALITIES:
            return APIResponse.error(f"无效的音质参数，支持: {', '.join(VALID_QUALITIES)}")
        
        # 验证类型参数
        valid_types = ['url', 'name', 'lyric', 'json']
        if info_type not in valid_types:
            return APIResponse.error(f"无效的类型参数，支持: {', '.join(valid_types)}")
        
        cookies = api_service._get_cookies()
        
        # 根据类型获取不同信息
        if info_type == 'url':
            result = url_v1(music_id, level, cookies)
            if result and result.get('data') and len(result['data']) > 0:
                song_data = result['data'][0]
                response_data = {
                    'id': song_data.get('id'),
                    'url': song_data.get('url'),
                    'level': song_data.get('level'),
                    'quality_name': api_service._get_quality_display_name(song_data.get('level', level)),
                    'size': song_data.get('size'),
                    'duration': song_data.get('dt', 0),
                    'size_formatted': api_service._format_file_size(song_data.get('size', 0)),
                    'type': song_data.get('type'),
                    'bitrate': song_data.get('br')
                }
                # 标注 Navidrome 状态（尝试通过歌曲详情获取名称/艺人/专辑）
                song_detail = name_v1(music_id)
                if song_detail and song_detail.get('songs'):
                    sd = song_detail['songs'][0]
                    artists_str = '/'.join(a['name'] for a in sd.get('ar', []))
                    album_name = sd.get('al', {}).get('name', '')
                    response_data['in_navidrome'] = api_service.navidrome_status(
                        sd.get('name', ''), artists_str, album_name
                    )
                else:
                    response_data['in_navidrome'] = api_service.get_empty_result()
                return APIResponse.success(response_data, "获取歌曲URL成功")
            else:
                return APIResponse.error("获取音乐URL失败，可能是版权限制或音质不支持", 404)
        
        elif info_type == 'name':
            result = name_v1(music_id)
            return APIResponse.success(result, "获取歌曲信息成功")
        
        elif info_type == 'lyric':
            result = lyric_v1(music_id, cookies)
            return APIResponse.success(result, "获取歌词成功")
        
        elif info_type == 'json':
            # 获取完整的歌曲信息（用于前端解析）
            song_info = name_v1(music_id)
            url_info = url_v1(music_id, level, cookies)
            lyric_info = lyric_v1(music_id, cookies)
            
            if not song_info or 'songs' not in song_info or not song_info['songs']:
                return APIResponse.error("未找到歌曲信息", 404)
            
            song_data = song_info['songs'][0]
            
            # 构建前端期望的响应格式
            response_data = {
                'id': music_id,
                'name': song_data.get('name', ''),
                'ar_name': ', '.join(artist['name'] for artist in song_data.get('ar', [])),
                'al_name': song_data.get('al', {}).get('name', ''),
                'pic': song_data.get('al', {}).get('picUrl', ''),
                'duration': song_data.get('dt', 0),
                'level': level,
                'lyric': lyric_info.get('lrc', {}).get('lyric', '') if lyric_info else '',
                'tlyric': lyric_info.get('tlyric', {}).get('lyric', '') if lyric_info else ''
            }

            # 标注 Navidrome 状态（复用上方已获取的 song_data，避免重复请求 name_v1）
            artists_str = '/'.join(a['name'] for a in song_data.get('ar', []))
            response_data['in_navidrome'] = api_service.navidrome_status(
                song_data.get('name', ''), artists_str, song_data.get('al', {}).get('name', '')
            )

            # 添加URL和大小信息
            if url_info and url_info.get('data') and len(url_info['data']) > 0:
                url_data = url_info['data'][0]
                response_data.update({
                    'url': url_data.get('url', ''),
                    'size': api_service._format_file_size(url_data.get('size', 0)),
                    'level': url_data.get('level', level)
                })
            else:
                response_data.update({
                    'url': '',
                    'size': '获取失败'
                })
            return APIResponse.success(response_data, "获取歌曲URL成功")
            
    except APIException as e:
        api_service.logger.error(f"API调用失败: {e}")
        return APIResponse.error(f"API调用失败: {str(e)}", 500)
    except Exception as e:
        api_service.logger.error(f"获取歌曲信息异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"服务器错误: {str(e)}", 500)

@app.route('/song/detail', methods=['GET', 'POST'])
@limiter.limit("60/minute")  # 每分钟最多30次请求
def song_detail_api():
    """获取歌曲详情接口（需有效Cookie才能访问）"""
    try:
        # 1. 【核心逻辑】先判断Cookie有效性，无效直接返回
        cookies = api_service._get_cookies()
        try:
            # 调用Cookie有效性检查方法
            is_cookie_valid = api_service.netease_api.is_cookie_valid(cookies)
        except Exception as e:
            api_service.logger.error(f"Cookie有效性检查异常: {e}")
            return APIResponse.error("Cookie验证失败，请重试", 500)
        
        # 若Cookie无效，直接返回错误
        if not is_cookie_valid:
            return APIResponse.error("Cookie无效或已过期，请重新登录", 401)  # 401表示未授权
        
        # 3. 仅当Cookie有效时，才执行后续逻辑

         # 1. 获取并验证请求参数
        # 获取请求参数
        data = api_service._safe_get_request_data()
        music_id = data.get('id')
        quality = data.get('quality', 'lossless')
        return_format = data.get('format', 'file')  # file 或 json
        
        # 参数验证
        validation_error = api_service._validate_request_params({'music_id': music_id})
        if validation_error:
            return validation_error
        
        # 验证音质参数
        if quality not in VALID_QUALITIES:
            return APIResponse.error(f"无效的音质参数，支持: {', '.join(VALID_QUALITIES)}")
        
        # 验证返回格式
        if return_format not in ['file', 'json']:
            return APIResponse.error("返回格式只支持 'file' 或 'json'")

        # 获取歌曲基本信息
        song_info = name_v1(music_id)
        if not song_info or 'songs' not in song_info or not song_info['songs']:
            return APIResponse.error("未找到歌曲信息", 404)

        # 获取音乐下载链接
        url_info = url_v1(music_id, quality, cookies)
        if not url_info or 'data' not in url_info or not url_info['data'] or not url_info['data'][0].get('url'):
            return APIResponse.error("无法获取音乐下载链接，可能是版权限制或音质不支持", 404)
        
        # 获取音乐歌词信息
        lyric_info = lyric_v1(music_id, cookies)
        
        # 构建音乐信息
        song_data = song_info['songs'][0]
        url_data = url_info['data'][0]
        
        # 获取专辑详情以提取更准确的发行时间
        alum_id=song_data['al']['id'] if song_data and 'al' in song_data and song_data['al'] else None
        alum_info = api_service.netease_api.get_album_detail(alum_id,cookies) if alum_id else None
        alum_publisTime=''
        if alum_info and 'publishTime' in alum_info:
            alum_publisTime = alum_info.get('publishTime', song_data['al'].get('publishTime',0))
        publish_timestamp = alum_publisTime
        # 转换为年月日格式（调用工具函数）
        publish_time = api_service.netease_api._timestamp_str_to_date(publish_timestamp)
        
        

        # 生成安全文件名
        # 获取音乐信息
        title = song_data['name']
        # 生成艺术家列表（新增）
        ar_list = song_data.get('ar', [])  # 安全获取艺术家列表，默认空列表
        artists_list = [artist['name'] for artist in ar_list] if ar_list else ['未知艺术家']
        # 生成艺术家字符串（保持不变）
        artists_str = '&'.join(artists_list)  # 复用列表生成字符串，避免重复遍历
        # 生成可能的文件名
        base_filename = f"{artists_str} - {title}"
        safe_filename = api_service.downloader.get_sanitize_filename(base_filename)

        file_ext = api_service.downloader.get_file_extension(url_data['url'])
        # 检查所有可能的文件
        filename = f"{safe_filename}{file_ext}"

        music_info = {
            'id': music_id,
            'name': title,
            'artist_string': artists_str,
            'artists': artists_list,  # 新增列表类型字段，存储多个艺术家
            'album': song_data['al']['name'],
            'pic_url': song_data['al']['picUrl'],
            'file_type': url_data['type'],
            'file_size': url_data['size'],
            'duration': song_data.get('dt', 0),
            'download_url': url_data['url'],
            'publishTime': publish_time,
            'filename': filename,
            'track_number': song_data['no'],
            'lyric': lyric_info.get('lrc', {}).get('lyric', '') if lyric_info else '',
            'tlyric': lyric_info.get('tlyric', {}).get('lyric', '') if lyric_info else ''
        }
        
        return APIResponse.success(music_info, "歌曲详情获取成功")
        
    except Exception as e:
        api_service.logger.error(f"获取歌曲详情异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"获取歌曲详情失败: {str(e)}", 500)
    

@app.route('/search', methods=['GET', 'POST'])
@app.route('/Search', methods=['GET', 'POST'])  # 向后兼容
@limiter.limit("30/minute")  # 每分钟最多30次请求
def search_music_api():
    """搜索音乐API"""
    try:
        # 获取请求参数
        data = api_service._safe_get_request_data()
        keyword = data.get('keyword') or data.get('keywords') or data.get('q')
        limit = int(data.get('limit', 30))
        offset = int(data.get('offset', 0))
        search_type = data.get('type', '1')  # 1-歌曲, 10-专辑, 100-歌手, 1000-歌单
        
        # 参数验证
        validation_error = api_service._validate_request_params({'keyword': keyword})
        if validation_error:
            return validation_error
        
        # 限制搜索数量
        if limit > 100:
            limit = 100
        
        cookies = api_service._get_cookies()
        result = search_music(keyword, cookies, limit)
        
        # search_music返回的是歌曲列表，需要包装成前端期望的格式
        if result:
            for song in result:
                # 统一艺术家字段格式（确保为字符串）
                if 'artists' in song and isinstance(song['artists'], list):
                    song['artist_string'] = '/'.join(artist.get('name', '') for artist in song['artists'])
                else:
                    song['artist_string'] = song.get('artists', '')  # 直接使用字符串
                # 标注 Navidrome 库内存在性（未启用/异常时返回空结果字典）
                song['in_navidrome'] = api_service.navidrome_status(
                    song.get('name', ''), song['artist_string'], song.get('album', '')
                )

        return APIResponse.success(result, "搜索完成")
        
    except ValueError as e:
        return APIResponse.error(f"参数格式错误: {str(e)}")
    except Exception as e:
        api_service.logger.error(f"搜索音乐异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"搜索失败: {str(e)}", 500)


@app.route('/playlist', methods=['GET', 'POST'])
@app.route('/Playlist', methods=['GET', 'POST'])  # 向后兼容
@limiter.limit("30/minute")  # 每分钟最多30次请求
def get_playlist():
    """获取歌单详情API"""
    try:
        # 获取请求参数
        data = api_service._safe_get_request_data()
        playlist_id = data.get('id')
        
        # 参数验证
        validation_error = api_service._validate_request_params({'playlist_id': playlist_id})
        if validation_error:
            return validation_error
        
        cookies = api_service._get_cookies()
        #result2 = user_playlist(4912185576, cookies)
        result = playlist_detail(playlist_id, cookies)

        # 为歌单中的每首歌标注是否在 Navidrome 库内
        for track in result.get('tracks', []):
            artists_str = '/'.join(artist.get('name', '') for artist in track.get('ar', []))
            track['in_navidrome'] = api_service.navidrome_status(
                track.get('name', ''), artists_str, track.get('al', {}).get('name', '')
            )

        # 适配前端期望的响应格式
        response_data = {
            'status': 'success',
            'playlist': result
        }
        
        return APIResponse.success(response_data, "获取歌单详情成功")
        
    except Exception as e:
        api_service.logger.error(f"获取歌单异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"获取歌单失败: {str(e)}", 500)


@app.route('/album', methods=['GET', 'POST'])
@app.route('/Album', methods=['GET', 'POST'])  # 向后兼容
@limiter.limit("30/minute")  # 每分钟最多30次请求
def get_album():
    """获取专辑详情API"""
    try:
        # 获取请求参数
        data = api_service._safe_get_request_data()
        album_id = data.get('id')
        
        # 参数验证
        validation_error = api_service._validate_request_params({'album_id': album_id})
        if validation_error:
            return validation_error
        
        cookies = api_service._get_cookies()
        result = album_detail(album_id, cookies)
        
        # 为专辑中的每首歌标注是否在 Navidrome 库内（统一用专辑整体名称作为匹配条件）
        album_name = result.get('name', '')
        for song in result.get('songs', []):
            artists_str = '/'.join(artist.get('name', '') for artist in song.get('ar', []))
            song['in_navidrome'] = api_service.navidrome_status(
                song.get('name', ''), artists_str, album_name
            )

        # 适配前端期望的响应格式
        response_data = {
            'status': 200,
            'album': result
        }
        
        return APIResponse.success(response_data, "获取专辑详情成功")
        
    except Exception as e:
        api_service.logger.error(f"获取专辑异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"获取专辑失败: {str(e)}", 500)


@app.route('/download', methods=['GET', 'POST'])
@app.route('/Download', methods=['GET', 'POST'])  # 向后兼容
@limiter.limit("30/minute")  # 每分钟最多30次下载
def download_music_api():
    """下载音乐API"""
    try:
        # 获取请求参数
        data = api_service._safe_get_request_data()
        music_id = data.get('id')
        quality = data.get('quality', 'lossless')
        return_format = data.get('format', 'file')  # file 或 json
        
        # 参数验证
        validation_error = api_service._validate_request_params({'music_id': music_id})
        if validation_error:
            return validation_error
        
        # 验证音质参数
        if quality not in VALID_QUALITIES:
            return APIResponse.error(f"无效的音质参数，支持: {', '.join(VALID_QUALITIES)}")
        
        # 验证返回格式
        if return_format not in ['file', 'json']:
            return APIResponse.error("返回格式只支持 'file' 或 'json'")
        
        music_id = api_service._extract_music_id(music_id)
        cookies = api_service._get_cookies()
        
        # 获取音乐基本信息
        song_info = name_v1(music_id)
        if not song_info or 'songs' not in song_info or not song_info['songs']:
            return APIResponse.error("未找到音乐信息", 404)
        
        # 获取音乐下载链接
        url_info = url_v1(music_id, quality, cookies)
        if not url_info or 'data' not in url_info or not url_info['data'] or not url_info['data'][0].get('url'):
            return APIResponse.error("无法获取音乐下载链接，可能是版权限制或音质不支持", 404)
        # 获取音乐歌词信息
        lyric_info = lyric_v1(music_id, cookies)

        # 构建音乐信息
        song_data = song_info['songs'][0]
        url_data = url_info['data'][0]
        
        # 获取专辑详情以提取更准确的发行时间
        alum_id=song_data['al']['id'] if song_data and 'al' in song_data and song_data['al'] else None
        alum_info = api_service.netease_api.get_album_detail(alum_id,cookies) if alum_id else None
        alum_publisTime=''
        if alum_info and 'publishTime' in alum_info:
            alum_publisTime = alum_info.get('publishTime', song_data['al'].get('publishTime',0))
        publish_timestamp = alum_publisTime
        # 转换为年月日格式（调用工具函数）
        publish_time = api_service.netease_api._timestamp_str_to_date(publish_timestamp)
        music_info = {
            'id': music_id,
            'name': song_data['name'],
            'artist_string': ', '.join(artist['name'] for artist in song_data['ar']),
            'album': song_data['al']['name'],
            'pic_url': song_data['al']['picUrl'],
            'file_type': url_data['type'],
            'file_size': url_data['size'],
            'duration': song_data.get('dt', 0),
            'download_url': url_data['url'],
            'publishTime': publish_time,
            'track_number': song_data['no'],
            'lyric': lyric_info.get('lrc', {}).get('lyric', '') if lyric_info else '',
            'tlyric': lyric_info.get('tlyric', {}).get('lyric', '') if lyric_info else ''
        }
        
        # 生成安全文件名
        # 获取音乐信息
        title = music_info['name']
        artists = music_info['artist_string']
        # 生成可能的文件名
        base_filename = f"{artists} - {title}"
        safe_filename = api_service.downloader.get_sanitize_filename(base_filename)

        file_ext = api_service.downloader.get_file_extension(music_info['download_url'])
        # 检查所有可能的文件
        filename = f"{safe_filename}{file_ext}"
        
        # 【核心修改】删除本地文件检查逻辑，改为内存下载
        try:
            # 调用内存下载方法（含标签写入）
            m_info=api_service.downloader.convert_to_music_info(music_info)
            success, audio_data, _ = api_service.downloader.download_music_to_memory(m_info, quality)
            if not success:
                return APIResponse.error("下载失败: 内存传输异常", 500)
            stats_tracker.record_download()  # 下载成功，下载歌曲数 +1
        except DownloadException as e:
            api_service.logger.error(f"下载异常: {e}")
            return APIResponse.error(f"下载失败: {str(e)}", 500)
        
        # 根据返回格式返回结果
        if return_format == 'json':
            response_data = {
                'music_id': music_id,
                'name': music_info['name'],
                'artist': music_info['artist_string'],
                'album': music_info['album'],
                'quality': quality,
                'quality_name': api_service._get_quality_display_name(quality),
                'file_type': music_info['file_type'],
                'file_size': music_info['file_size'],
                'file_size_formatted': api_service._format_file_size(music_info['file_size']),
                # 【删除本地文件路径】不再返回服务器文件路径
                'filename': filename,
                'duration': music_info['duration'],
                'publishTime': music_info['publishTime']
            }
            return APIResponse.success(response_data, "下载完成")
        else:
             # 【核心修改】从内存数据流发送文件，而非本地路径
            try:
                # 确保数据流指针在开头
                audio_data.seek(0)
                
                response = send_file(
                    audio_data,  # 内存中的数据流
                    as_attachment=True,  # 强制浏览器下载
                    download_name=filename,
                    mimetype=f"audio/{music_info['file_type']}"
                )
                # 保持原有自定义头信息
                response.headers['X-Download-Message'] = 'Download completed successfully'
                response.headers['X-Download-Filename'] = quote(filename, safe='')
                # 增强中文文件名兼容性
                response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(filename)}"
                return response
            except Exception as e:
                api_service.logger.error(f"发送文件失败: {e}")
                return APIResponse.error(f"文件发送失败: {str(e)}", 500)
            
    except Exception as e:
        api_service.logger.error(f"下载音乐异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"下载异常: {str(e)}", 500)

# 新增：二维码登录相关接口
@app.route('/api/qr/generate', methods=['GET'])
@limiter.limit("5/minute")  # 每分钟最多5次请求
def generate_qr():
    """生成登录二维码"""
    try:
        result = api_service.qr_manager.create_qr_code()
        if result['success']:
            return APIResponse.success(result, "二维码生成成功")
        else:
            return APIResponse.error(result['message'], 500)
    except Exception as e:
        api_service.logger.error(f"生成二维码异常: {e}")
        return APIResponse.error(f"生成二维码失败: {str(e)}", 500)


@app.route('/api/qr/check', methods=['GET'])
@limiter.limit("10/minute")  # 每分钟最多10次请求
def check_qr_status():
    """检查二维码登录状态"""
    try:
        qr_key = request.args.get('qr_key')
        if not qr_key:
            return APIResponse.error("缺少qr_key参数", 400)
        
        result = api_service.qr_manager.check_login_status(qr_key)
        if result['success']:
            # 如果登录成功，保存cookie
            if result.get('status_code') == 803 and 'cookie' in result:
                try:
                    res_cookie=result['cookie']
                    qr_parse_cookie=api_service.cookie_manager.get_qr_cookie(res_cookie)
                    cookie_status = api_service.netease_api.is_cookie_valid(qr_parse_cookie)
                    is_vip=cookie_status.get('is_vip',False)
                    result['is_vip'] = is_vip

                    # 仅当是VIP时才更新cookie
                    if is_vip:
                        api_service.cookie_manager.update_cookie(res_cookie)
                        api_service.logger.info("登录成功，VIP用户已保存cookie")
                    else:
                        api_service.logger.info("登录成功，但非VIP用户，不保存cookie")
                except Exception as e:
                    api_service.logger.warning(f"保存cookie失败: {e}")
                    result['is_vip'] = False
            
            return APIResponse.success(result, "检查二维码状态成功")
        else:
            return APIResponse.error(result['message'], 500)
    except Exception as e:
        api_service.logger.error(f"检查二维码状态异常: {e}")
        return APIResponse.error(f"检查二维码状态失败: {str(e)}", 500)
    
@app.route('/api/check-cookie', methods=['GET'])
@limiter.limit("10/minute")  # 每分钟最多10次请求
def check_cookie():
    """检查Cookie是否有效及VIP状态"""
    try:
        cookies = api_service._get_cookies()
        # 现在返回的是包含 'valid' 和 'is_vip' 的字典
        cookie_result = api_service.netease_api.is_cookie_valid(cookies)
        
        # 同时返回有效性和VIP状态
        return APIResponse.success(
            {
                "valid": cookie_result['valid'],
                "is_vip": cookie_result['is_vip']
            }, 
            "Cookie状态检查成功"
        )
    except Exception as e:
        api_service.logger.error(f"检查Cookie状态异常: {e}")
        return APIResponse.error(f"检查Cookie状态失败: {str(e)}", 500)

@app.route('/api/info', methods=['GET'])
@limiter.limit("10/minute")  # 每分钟最多10次请求
def api_info():
    """API信息接口"""
    try:
        info = {
            'name': '网易云音乐API服务',
            'version': '2.0.0',
            'description': '提供网易云音乐相关API服务',
            'endpoints': {
                '/health': 'GET - 健康检查',
                '/song': 'GET/POST - 获取歌曲信息',
                '/search': 'GET/POST - 搜索音乐',
                '/playlist': 'GET/POST - 获取歌单详情',
                '/album': 'GET/POST - 获取专辑详情',
                '/download': 'GET/POST - 下载音乐',
                '/api/info': 'GET - API信息'
            },
            'supported_qualities': [
                'standard', 'exhigh', 'lossless', 
                'hires', 'sky', 'jyeffect', 'jymaster'
            ],
            'config': {
                'downloads_dir': str(api_service.downloads_path.absolute()),
                'max_file_size': f"{user_config.max_file_size // (1024*1024)}MB",
                'request_timeout': f"{user_config.request_timeout}s"
            }
        }
        
        return APIResponse.success(info, "API信息获取成功")
        
    except Exception as e:
        api_service.logger.error(f"获取API信息异常: {e}")
        return APIResponse.error(f"获取API信息失败: {str(e)}", 500)


@app.route('/api/stats', methods=['GET'])
@limiter.limit("30/minute")
def api_stats():
    """查看当期使用统计（去重访问IP数 + 下载歌曲数 + 累计下载）。"""
    try:
        return APIResponse.success(stats_tracker.snapshot(), "统计获取成功")
    except Exception as e:
        api_service.logger.error(f"获取统计异常: {e}")
        return APIResponse.error(f"获取统计失败: {str(e)}", 500)


def start_api_server():
    """启动API服务器"""
    try:
        print("\n" + "="*60)
        print("🚀 网易云音乐API服务启动中...")
        print("="*60)
        print(f"📡 服务地址: http://{user_config.web_host}:{user_config.web_port}")
        print(f"📁 下载目录: {api_service.downloads_path.absolute()}")
        print(f"📋 日志级别: {user_config.log_level}")
        print("\n📚 API端点:")
        print(f"  ├─ GET  /health        - 健康检查")
        print(f"  ├─ POST /song          - 获取歌曲信息")
        print(f"  ├─ POST /search        - 搜索音乐")
        print(f"  ├─ POST /playlist      - 获取歌单详情")
        print(f"  ├─ POST /album         - 获取专辑详情")
        print(f"  ├─ POST /download      - 下载音乐")
        print(f"  └─ GET  /api/info      - API信息")
        print("\n🎵 支持的音质:")
        print(f"  standard, exhigh, lossless, hires, sky, jyeffect, jymaster")
        print("="*60)
        print(f"⏰ 启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("🌟 服务已就绪，等待请求...\n")
        # 初始化日志
        level = user_config.get("LEVEL", "INFO")
        # 用 getattr 替代 logging.getLevelName，获取日志级别常量
        log_level = getattr(logging, level, logging.INFO)  # 若级别无效，默认使用 INFO
        setup_logger(log_level)

        # 启动每日 Bark 统计推送（仅在配置开启时）
        # 注意：debug=True 时 Werkzeug reloader 会以父/子两个进程运行本函数，
        # 后台线程必须只在真正的服务进程启动一次，否则会重复启动导致每日推送两条。
        is_serving_process = (not user_config.debug) or os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        if user_config.use_bark and is_serving_process:
            try:
                hh, mm = (user_config.bark_time.split(':') + ['0'])[:2]
                start_daily_notifier(stats_tracker, lambda: user_config.bark_url, int(hh), int(mm))
            except Exception as e:
                logging.error(f"启动 Bark 每日推送失败: {e}")
        elif not user_config.use_bark and is_serving_process:
            logging.info("未启用 Bark 推送（BARK.USE_BARK=false），仅在 /api/stats 提供统计查询")

        # 启动Flask应用
        app.run(
            host=user_config.web_host,
            port=user_config.web_port,
            debug=user_config.debug,
            threaded=True
        )
        
    except KeyboardInterrupt:
        print("\n\n👋 服务已停止")
    except Exception as e:
        logging.error(f"程序启动失败: {str(e)}", exc_info=True)
        print(f"❌ 启动失败: {e}")
        sys.exit(1)


if __name__ == '__main__':
    start_api_server()
