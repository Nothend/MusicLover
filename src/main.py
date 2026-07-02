"""网易云音乐解析下载 Web 服务主程序（纯前端下载版）。

只服务一个网页应用：解析单曲/歌单/专辑 → 浏览器直接下载。
提供的接口都是这个页面自己会调用的：
- /                 网页
- /health           健康检查
- /song             单曲解析（url/name/lyric/json）
- /song/detail      拿下载直链 + 元信息（前端下载核心）
- /playlist /album  歌单/专辑解析
- /api/qr/*         扫码登录
- /api/check-password / /api/check-cookie  密码门 / cookie 校验
服务端不落地文件、不写标签，下载由浏览器完成。
"""

import logging
import os
import sys
import time
import traceback
import ipaddress
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse
from flask import Flask, jsonify, request, render_template, Response
from config import Config
from logger import setup_logger

from flask_limiter import Limiter

try:
    from music_api import (
        NeteaseAPI, APIException, QualityLevel, QRLoginManager,
        url_v1, name_v1, lyric_v1, playlist_detail, album_detail,
    )
    from cookie_manager import CookieManager, CookieException
    from filename import sanitize_filename, file_extension
except ImportError as e:
    print(f"导入模块失败: {e}")
    print("请确保所有依赖模块存在且可用")
    sys.exit(1)


# 支持的音质等级（取自 QualityLevel 枚举，避免在各路由重复硬编码同一份列表）
VALID_QUALITIES = [q.value for q in QualityLevel]


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
    """音乐解析服务：封装 cookie、NetEase 客户端、扫码登录与单曲信息解析。"""

    def __init__(self, user_config: Config):
        self._user_config = user_config
        self.cookie_manager = CookieManager(user_config)
        self.netease_api = NeteaseAPI()
        self.qr_manager = QRLoginManager()
        self.logger = logging.getLogger(__name__)

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

    def build_download_filename(self, name: str, artists, url: str = "") -> str:
        """统一生成下载文件名：『歌手 - 歌曲名.<ext>』。

        因本项目不写入任何元信息，文件名是辨识歌曲的唯一依据，务必保证『歌手 - 歌曲名』格式。

        Args:
            name: 歌曲名
            artists: 歌手，可为名称列表/元组，或已拼接好的字符串
            url: 下载链接，用于推断扩展名；为空则不追加扩展名
        """
        if isinstance(artists, (list, tuple)):
            artist_str = '&'.join(a for a in artists if a) or '未知艺术家'
        else:
            artist_str = (artists or '').strip() or '未知艺术家'
        title = (name or '').strip() or '未知歌曲'
        safe_filename = sanitize_filename(f"{artist_str} - {title}")
        file_ext = file_extension(url) if url else ''
        return f"{safe_filename}{file_ext}"

    def resolve_song_info(self, music_id, quality: str, cookies: Dict[str, str]):
        """解析单曲完整信息（/song/detail 用）。

        统一完成：ID 归一化 → 基本信息 → 下载链接 → 歌词 → 专辑发行时间 →
        组装 music_info（含统一文件名『歌手 - 歌曲名.<ext>』与艺术家列表）。

        Returns:
            (music_info: dict, None) 成功；(None, error_response) 失败（已是可直接 return 的响应）。
        """
        music_id = self._extract_music_id(music_id)

        # 基本信息
        song_info = name_v1(music_id)
        if not song_info or 'songs' not in song_info or not song_info['songs']:
            return None, APIResponse.error("未找到歌曲信息", 404)

        # 下载链接
        url_info = url_v1(music_id, quality, cookies)
        if not url_info or 'data' not in url_info or not url_info['data'] or not url_info['data'][0].get('url'):
            return None, APIResponse.error("无法获取音乐下载链接，可能是版权限制或音质不支持", 404)

        # 歌词
        lyric_info = lyric_v1(music_id, cookies)

        song_data = song_info['songs'][0]
        url_data = url_info['data'][0]

        # 专辑详情以提取更准确的发行时间
        al = song_data.get('al') or {}
        alum_info = self.netease_api.get_album_detail(al['id'], cookies) if al.get('id') else None
        publish_timestamp = ''
        if alum_info and 'publishTime' in alum_info:
            publish_timestamp = alum_info.get('publishTime', al.get('publishTime', 0))
        publish_time = self.netease_api._timestamp_str_to_date(publish_timestamp)

        title = song_data['name']
        ar_list = song_data.get('ar', [])
        artists_list = [artist['name'] for artist in ar_list] if ar_list else ['未知艺术家']

        music_info = {
            'id': music_id,
            'name': title,
            'artist_string': '&'.join(artists_list),
            'artists': artists_list,
            'album': al.get('name', ''),
            'pic_url': al.get('picUrl', ''),
            'file_type': url_data['type'],
            'file_size': url_data['size'],
            'duration': song_data.get('dt', 0),
            'download_url': url_data['url'],
            'publishTime': publish_time,
            'filename': self.build_download_filename(title, artists_list, url_data['url']),
            'track_number': song_data.get('no', 0),
            'lyric': lyric_info.get('lrc', {}).get('lyric', '') if lyric_info else '',
            'tlyric': lyric_info.get('tlyric', {}).get('lyric', '') if lyric_info else '',
        }
        return music_info, None

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


# 创建Flask应用和服务实例
user_config = Config()
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


def _client_ip() -> str:
    """获取真实客户端 IP：优先 X-Forwarded-For 首跳（站点走了反代），否则 remote_addr。"""
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or ''


# 初始化频率限制器
limiter = Limiter(
    # 基于“真实客户端 IP”限流。站点在反向代理后面，request.remote_addr 是代理的 IP，
    # 若用它做 key，会把所有访客算到同一个 IP 上、共用同一个限流桶——只要全站累计请求
    # 超过限额，所有人都会被 429。这里用 _client_ip（取 X-Forwarded-For 首跳），让每个访客各自独立计数。
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
    # 1. 记录请求信息
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
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
    response.headers.add('Access-Control-Max-Age', '3600')
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
@limiter.limit("30/minute")
def check_password() -> str:
    # 获取用户输入的密码
    user_password = request.args.get('password', '')
    # 从配置获取正确密码
    qr_password = user_config.qr_password
    # 验证密码
    if user_password.strip() == str(qr_password).strip():
        return jsonify({'success': True, 'message': '密码验证成功'})
    return jsonify({'success': False, 'message': '密码错误'})


@app.route('/health', methods=['GET'])
@limiter.limit("10/minute")
def health_check():
    """健康检查API"""
    try:
        cookie_status = api_service.cookie_manager.is_cookie_valid()
        health_info = {
            'service': 'running',
            'timestamp': int(time.time()),
            'cookie_status': 'valid' if cookie_status else 'invalid',
            'version': APP_VERSION,
        }
        return APIResponse.success(health_info, "API服务运行正常")
    except Exception as e:
        api_service.logger.error(f"健康检查失败: {e}")
        return APIResponse.error(f"健康检查失败: {str(e)}", 500)


@app.route('/song', methods=['GET', 'POST'])
@limiter.limit("60/minute")
def get_song_info():
    """获取歌曲信息API（type: url/name/lyric/json）"""
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

            # 添加URL和大小信息
            if url_info and url_info.get('data') and len(url_info['data']) > 0:
                url_data = url_info['data'][0]
                response_data.update({
                    'url': url_data.get('url', ''),
                    'size': api_service._format_file_size(url_data.get('size', 0)),
                    'level': url_data.get('level', level)
                })
            else:
                response_data.update({'url': '', 'size': '获取失败'})
            return APIResponse.success(response_data, "获取歌曲URL成功")

    except APIException as e:
        api_service.logger.error(f"API调用失败: {e}")
        return APIResponse.error(f"API调用失败: {str(e)}", 500)
    except Exception as e:
        api_service.logger.error(f"获取歌曲信息异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"服务器错误: {str(e)}", 500)


@app.route('/song/detail', methods=['GET', 'POST'])
@limiter.limit("60/minute")
def song_detail_api():
    """获取歌曲详情接口（前端下载核心，需有效Cookie才能访问）"""
    try:
        # 1. 先判断Cookie有效性，无效直接返回
        cookies = api_service._get_cookies()
        try:
            is_cookie_valid = api_service.netease_api.is_cookie_valid(cookies)
        except Exception as e:
            api_service.logger.error(f"Cookie有效性检查异常: {e}")
            return APIResponse.error("Cookie验证失败，请重试", 500)

        if not is_cookie_valid:
            return APIResponse.error("Cookie无效或已过期，请重新登录", 401)

        # 2. 获取并验证请求参数
        data = api_service._safe_get_request_data()
        music_id = data.get('id')
        quality = data.get('quality', 'lossless')

        validation_error = api_service._validate_request_params({'music_id': music_id})
        if validation_error:
            return validation_error

        if quality not in VALID_QUALITIES:
            return APIResponse.error(f"无效的音质参数，支持: {', '.join(VALID_QUALITIES)}")

        # 3. 解析单曲完整信息（含下载直链，浏览器据此直接下载）
        music_info, error = api_service.resolve_song_info(music_id, quality, cookies)
        if error:
            return error

        return APIResponse.success(music_info, "歌曲详情获取成功")

    except Exception as e:
        api_service.logger.error(f"获取歌曲详情异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"获取歌曲详情失败: {str(e)}", 500)


@app.route('/playlist', methods=['GET', 'POST'])
@limiter.limit("30/minute")
def get_playlist():
    """获取歌单详情API"""
    try:
        data = api_service._safe_get_request_data()
        playlist_id = data.get('id')

        validation_error = api_service._validate_request_params({'playlist_id': playlist_id})
        if validation_error:
            return validation_error

        cookies = api_service._get_cookies()
        result = playlist_detail(playlist_id, cookies)

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
@limiter.limit("30/minute")
def get_album():
    """获取专辑详情API"""
    try:
        data = api_service._safe_get_request_data()
        album_id = data.get('id')

        validation_error = api_service._validate_request_params({'album_id': album_id})
        if validation_error:
            return validation_error

        cookies = api_service._get_cookies()
        result = album_detail(album_id, cookies)

        # 适配前端期望的响应格式
        response_data = {
            'status': 200,
            'album': result
        }
        return APIResponse.success(response_data, "获取专辑详情成功")

    except Exception as e:
        api_service.logger.error(f"获取专辑异常: {e}\n{traceback.format_exc()}")
        return APIResponse.error(f"获取专辑失败: {str(e)}", 500)


@app.route('/api/qr/generate', methods=['GET'])
@limiter.limit("5/minute")
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
@limiter.limit("10/minute")
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
                    res_cookie = result['cookie']
                    qr_parse_cookie = api_service.cookie_manager.get_qr_cookie(res_cookie)
                    cookie_status = api_service.netease_api.is_cookie_valid(qr_parse_cookie)
                    is_vip = cookie_status.get('is_vip', False)
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
@limiter.limit("10/minute")
def check_cookie():
    """检查Cookie是否有效及VIP状态"""
    try:
        cookies = api_service._get_cookies()
        cookie_result = api_service.netease_api.is_cookie_valid(cookies)
        return APIResponse.success(
            {"valid": cookie_result['valid'], "is_vip": cookie_result['is_vip']},
            "Cookie状态检查成功"
        )
    except Exception as e:
        api_service.logger.error(f"检查Cookie状态异常: {e}")
        return APIResponse.error(f"检查Cookie状态失败: {str(e)}", 500)


def start_api_server():
    """启动API服务器"""
    try:
        # 初始化日志
        level = user_config.get("LEVEL", "INFO")
        log_level = getattr(logging, str(level).upper(), logging.INFO)
        if not isinstance(log_level, int):
            log_level = logging.INFO
        setup_logger(log_level)

        print("\n" + "=" * 60)
        print("🚀 网易云音乐解析下载服务启动中...")
        print("=" * 60)
        print(f"📡 服务地址: http://{user_config.web_host}:{user_config.web_port}")
        print(f"📋 日志级别: {level}")
        print(f"⏰ 启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("🌟 服务已就绪，等待请求...\n")

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
