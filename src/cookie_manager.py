"""Cookie管理器模块

提供网易云音乐Cookie管理功能，包括：
- Cookie文件读取和写入
- Cookie格式验证和解析
- Cookie有效性检查
- 自动过期处理
"""
from typing import Dict, Optional, List, Tuple, Any
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from config import Config

@dataclass
class CookieInfo:
    """Cookie信息数据类"""
    name: str
    value: str
    domain: str = ""
    path: str = "/"
    expires: Optional[int] = None
    secure: bool = False
    http_only: bool = False


class CookieException(Exception):
    """Cookie相关异常类"""
    pass


class CookieManager:
    """Cookie管理器主类"""
    
    def __init__(self, config: Config):
        """
        初始化Cookie管理器
        
        Args:
            cookie_file: Cookie文件路径
        """
        self.logger = logging.getLogger(__name__)
        """初始化Cookie管理器（无文件依赖）"""
        self.cookie_string: str = "" # 存储原始Cookie字符串
        self.parsed_cookies: Dict[str, str] = []  # 解析后的Cookie字典
        self.set_cookie_string(config.get("cookie"))
        # 网易云音乐相关的重要Cookie字段
        self.important_cookies = {
            'MUSIC_U',      # 用户标识
            'MUSIC_A',      # 用户认证
            '__csrf',       # CSRF令牌
            'NMTID',        # 设备标识
            'WEVNSM',       # 会话管理
            'WNMCID',       # 客户端标识
        }
        
    
    def set_cookie_string(self, cookie_str: str) -> None:
        """
        设置Cookie原始字符串并解析
        
        Args:
            cookie_string: 从配置获取的Cookie字符串
        """
        self.cookie_string = cookie_str.strip()
        # 立即解析并缓存
        self.parsed_cookies = self.parse_cookie_string(self.cookie_string)
        self.logger.debug(f"已设置并解析Cookie，包含 {len(self.parsed_cookies)} 个字段")
    
    def parse_cookie_string(self, cookie_string: str) -> Dict[str, str]:
        """解析Cookie字符串
        
        Args:
            cookie_string: Cookie字符串
            
        Returns:
            Cookie字典
        """
        if not cookie_string or not cookie_string.strip():
            return {}
        
        cookies = {}
        
        try:
            # 处理多种Cookie格式
            cookie_string = cookie_string.strip()
            
            # 分割Cookie项
            cookie_pairs = []
            if ';' in cookie_string:
                cookie_pairs = cookie_string.split(';')
            elif '\n' in cookie_string:
                cookie_pairs = cookie_string.split('\n')
            else:
                cookie_pairs = [cookie_string]
            
            for pair in cookie_pairs:
                pair = pair.strip()
                if not pair or '=' not in pair:
                    continue
                
                # 分割键值对
                key, value = pair.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                if key and value:
                    cookies[key] = value
            
            self.logger.debug(f"解析得到 {len(cookies)} 个Cookie项")
            return cookies
            
        except Exception as e:
            self.logger.error(f"解析Cookie字符串失败: {e}")
            return {}
        
    def write_cookie(self, cookie_content: str) -> bool:
        """将Cookie写入config.yaml配置文件（增加权限异常处理）"""
        try:
            if not cookie_content or not cookie_content.strip():
                raise CookieException("Cookie内容不能为空")
            
            if not self.validate_cookie_format(cookie_content):
                raise CookieException("Cookie格式无效")
            
            # 更新配置并保存（可能触发权限检查）
            self.config.config['cookie'] = cookie_content.strip()
            try:
                self.config.save_config()  # 这里会触发Config类的权限检查
            except PermissionError as e:
                # 针对Docker环境的友好提示
                raise CookieException(
                    f"无权限写入config.yaml，请检查docker-compose映射的文件权限。详情：{str(e)}"
                ) from e
            
            self.set_cookie_string(cookie_content.strip())
            self.logger.info(f"Cookie已更新到配置文件: {self.config.config_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"写入Cookie失败: {e}")
            raise CookieException(f"写入Cookie失败: {e}")
        
    def update_cookie(self, new_cookies: Dict[str, str]) -> bool:
        """更新Cookie
        
        Args:
            new_cookies: 新的Cookie字典
            
        Returns:
            是否更新成功
        """
        try:
            if not new_cookies:
                raise CookieException("新Cookie不能为空")
            
            # 读取现有Cookie
            existing_cookies = self.parsed_cookies.copy()
            
            # 合并Cookie
            existing_cookies.update(new_cookies)
            
            # 转换为Cookie字符串
            cookie_string = self.format_cookie_string(existing_cookies)
            
            # 写入文件
            return self.write_cookie(cookie_string)
            
        except Exception as e:
            self.logger.error(f"更新Cookie失败: {e}")
            return False
    
    def get_cookie_for_request(self) -> Dict[str, str]:
        """获取用于HTTP请求的Cookie字典
        
        Returns:
            适用于requests库的Cookie字典
        """
        try:
            cookies = self.parse_cookies()
            
            # 过滤掉空值
            filtered_cookies = {k: v for k, v in cookies.items() if k and v}
            
            return filtered_cookies
            
        except Exception as e:
            self.logger.error(f"获取请求Cookie失败: {e}")
            return {}
        
    def validate_cookie_format(self, cookie_string: str) -> bool:
        """验证Cookie格式是否有效
        
        Args:
            cookie_string: Cookie字符串
            
        Returns:
            是否格式有效
        """
        if not cookie_string or not cookie_string.strip():
            return False
        
        try:
            # 尝试解析Cookie
            cookies = self.parse_cookie_string(cookie_string)
            
            # 检查是否至少包含一个有效的Cookie
            if not cookies:
                return False
            
            # 检查Cookie名称是否合法
            for name, value in cookies.items():
                if not name or not isinstance(name, str):
                    return False
                if not isinstance(value, str):
                    return False
                # 检查是否包含非法字符
                if any(char in name for char in [' ', '\t', '\n', '\r', ';', ',']):
                    return False
            
            return True
            
        except Exception:
            return False
    
    def is_cookie_valid(self) -> bool:
        """检查Cookie是否有效
        
        Returns:
            Cookie是否有效
        """
        try:
            cookies = self.parse_cookies()
            
            if not cookies:
                self.logger.warning("Cookie为空")
                return False
            
            # 检查重要Cookie是否存在
            missing_cookies = self.important_cookies - set(cookies.keys())
            if missing_cookies:
                self.logger.warning(f"缺少重要Cookie: {missing_cookies}")
                return False
            
            # 检查MUSIC_U是否有效（基本验证）
            music_u = cookies.get('MUSIC_U', '')
            if not music_u or len(music_u) < 10:
                self.logger.warning("MUSIC_U Cookie无效")
                return False
            
            self.logger.debug("Cookie验证通过")
            return True
            
        except Exception as e:
            self.logger.error(f"Cookie验证失败: {e}")
            return False
    
    def get_cookie_info(self) -> Dict[str, Any]:
        """获取Cookie详细信息（适配配置文件）"""
        try:
            cookies = self.parsed_cookies
            config_path = self.config.config_path
            
            info = {
                'config_path': str(config_path),  # 配置文件路径
                'config_exists': config_path.exists(),
                'cookie_count': len(cookies),
                'is_valid': self.is_cookie_valid(),
                'important_cookies_present': list(self.important_cookies & set(cookies.keys())),
                'missing_important_cookies': list(self.important_cookies - set(cookies.keys())),
                'all_cookie_names': list(cookies.keys())
            }
            
            # 添加配置文件修改时间
            if config_path.exists():
                mtime = config_path.stat().st_mtime
                info['config_last_modified'] = datetime.fromtimestamp(mtime).isoformat()
            
            return info
            
        except Exception as e:
            return {
                'error': str(e),
                'config_path': str(self.config.config_path),
                'is_valid': False
            }
        
    def format_cookie_string(self, cookies: Dict[str, str]) -> str:
        """将Cookie字典格式化为字符串
        
        Args:
            cookies: Cookie字典
            
        Returns:
            Cookie字符串
        """
        if not cookies:
            return ""
        
        return '; '.join(f"{k}={v}" for k, v in cookies.items() if k and v)
    
    def __str__(self) -> str:
        """字符串表示"""
        info = self.get_cookie_info()
        return f"CookieManager(file={info['file_path']}, valid={info['is_valid']}, count={info['cookie_count']})"
    
    def __repr__(self) -> str:
        """详细字符串表示"""
        return self.__str__()


if __name__ == "__main__":
    # 测试代码
    import sys
    
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    manager = CookieManager()
    
    print("Cookie管理器模块")
    print("支持的功能:")
    print("- Cookie文件读写")
    print("- Cookie格式验证")
    print("- Cookie有效性检查")
    print("- Cookie备份和恢复")
    print("- Cookie信息查看")
    
    # 显示当前Cookie信息
    info = manager.get_cookie_info()
    print(f"\n当前Cookie状态: {manager}")
    print(f"详细信息: {info}")
