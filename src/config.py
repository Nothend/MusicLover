import os
from pathlib import Path
import shutil
import yaml
import logging
from typing import Dict, Any, Optional

class Config:
    def __init__(self, config_path: str | None = None):
        # 1. 确定基准路径（config.py所在目录，即src目录）
        self.current_dir = Path(__file__).resolve().parent  # src目录（同级目录）
        self.parent_dir = self.current_dir.parent          # 父目录（项目根目录）
        # 2. 初始化目标配置路径（优先父目录）
        if config_path:
            self.config_path = Path(config_path)
        elif os.getenv("CONFIG_PATH"):
            self.config_path = Path(os.getenv("CONFIG_PATH"))
        else:
            # 默认目标路径：父目录下的config.yaml
            self.config_path = self.parent_dir / "config.yaml"

        # 3. 检查父目录配置文件是否存在，不存在则尝试拷贝同级模板
        if not self.config_path.exists() or not self.config_path.is_file():
            # 同级模板路径（src目录下的config.yaml）
            template_path = self.current_dir / "config.yaml"
            
            # 检查模板是否存在
            if template_path.exists() and template_path.is_file():
                try:
                    # 确保父目录存在（Docker环境可能需要创建）
                    self.parent_dir.mkdir(parents=True, exist_ok=True)
                    
                    # 拷贝模板到父目录
                    shutil.copy2(template_path, self.config_path)  # 保留文件元数据
                    logging.info(f"父目录未找到配置文件，已从同级模板拷贝: {template_path} -> {self.config_path}")
                except Exception as e:
                    logging.error(f"拷贝配置模板失败（可能是权限问题）: {str(e)}")
                    raise  # 拷贝失败无法继续，抛出异常
            else:
                logging.warning(f"同级目录未找到配置模板: {template_path}")
        
        # 4. 若上述步骤仍未找到配置文件，检查当前工作目录（兼容原有备用逻辑）
        if not self.config_path.exists() or not self.config_path.is_file():
            alt_path = Path.cwd() / self.config_path.name
            if alt_path.exists() and alt_path.is_file():
                self.config_path = alt_path
                logging.info(f"使用当前工作目录的配置文件: {self.config_path}")
            else:
                logging.error(f"所有路径均未找到配置文件，最终尝试路径: {self.config_path}, {alt_path}")
                raise FileNotFoundError("配置文件不存在，且无可用模板")

        logging.info(f"使用配置文件: {self.config_path} (cwd={Path.cwd()})")
        self.config: Dict[str, Any] = {}
        self.load_config()
        # 定义所有参数的默认值（与用户提供的默认值保持一致）
        self._defaults = {
            'web_host': '0.0.0.0',
            'web_port': '5151',
            'debug': False,
            'QR_PASSWORD': '1234',
            'downloads_dir': 'downloads',
            'max_file_size': 524288000,  # 500MB
            'request_timeout': 30,
            'log_level': 'INFO',
            'cors_origins': '*',
            'API_KEY': '9527',  # 替换为你的API密钥
            'RATE_LIMIT': '200/hour',  # 每小时最多100次请求（可调整）
            'IP_WHITELIST': ["127.0.0.1", "192.168.1.0/24"],  # 信任的IP白名单
            'PROTECTED_ENDPOINTS': [  # 需要保护的接口路径
                    "/song", "/search", "/playlist", "/album", 
                    "/download", "/api/qr", "/song/detail"
                ],
            'PUBLIC_ENDPOINTS': ["/health", "/api/info", "/"]  # 公开接口（无需保护）
        }
        
    def load_config(self) -> None:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
            logging.info(f"配置文件加载成功: {self.config_path}")
        except FileNotFoundError:
            logging.error(f"配置文件未找到: {self.config_path}")
            raise
        except Exception as e:
            logging.error(f"配置文件加载失败: {str(e)}")
            raise
    def is_enabled(self, type: str) -> bool:
        """
        检查指定类型的配置是否启用（支持参数大小写混用）
        :param type: 配置类型，支持'NAVIDROME'或'MYSQL'（大小写不限）
        :return: 配置是否有效启用，符合条件返回True，否则返回False
        """
        # 将参数转换为全大写，统一判断标准
        type_upper = type.upper()
        
        # 处理NAVIDROME类型检查
        if type_upper == 'NAVIDROME':
            # 检查是否存在NAVIDROME节点（配置中是大写节点）
            nav_node = self.config.get('NAVIDROME')
            if not nav_node:
                return False
            # 检查USE_NAVIDROME是否存在且为True
            return nav_node.get('USE_NAVIDROME', False) is True
        
        # 处理MYSQL类型检查（配置中是小写mysql节点）
        elif type_upper == 'MYSQL':
            # 检查是否存在mysql节点
            mysql_node = self.config.get('mysql')
            if not mysql_node:
                return False
            # 检查USE_MYSQL是否存在且为True
            return mysql_node.get('USE_MYSQL', False) is True
        
        # 其他类型返回False
        else:
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取一级配置项（兼容原有逻辑）"""
        return self.config.get(key, default)
    
    def get_nested(self, path: str, default: Optional[Any] = None) -> Any:
        """
        获取层级配置项（支持类似 'NAVIDROME.NAVIDROME_HOST' 的路径）
        :param path: 层级路径，用 '.' 分隔（如 'mysql.host'）
        :param default: 路径不存在时的默认返回值
        :return: 配置项的值，或默认值
        """
        keys = path.split('.')  # 分割路径为键列表（如 ['NAVIDROME', 'NAVIDROME_HOST']）
        current = self.config   # 从根配置开始逐层查找
        
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]  # 进入下一层级
            else:
                return default  # 任何一层不存在，返回默认值
        
        return current  # 找到最终值
    
    # 在config.py的Config类中更新save_config方法
    def save_config(self) -> None:
        """将当前配置保存到yaml文件（增加权限检查）"""
        try:
            # 检查文件是否存在
            if self.config_path.exists():
                # 已存在的文件：检查是否有写入权限
                if not os.access(self.config_path, os.W_OK):
                    raise PermissionError(f"配置文件无写入权限: {self.config_path}")
            else:
                # 文件不存在：检查父目录是否有写入权限（用于创建新文件）
                parent_dir = self.config_path.parent
                if not os.access(parent_dir, os.W_OK):
                    raise PermissionError(f"配置文件目录无写入权限: {parent_dir}")

            # 执行写入
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(self.config, f, allow_unicode=True, sort_keys=False)
            logging.info(f"配置已保存到: {self.config_path}")
        except PermissionError as e:
            logging.error(f"权限不足：{str(e)}（请检查docker-compose的文件映射权限）")
            raise  # 抛出异常让上层处理
        except Exception as e:
            logging.error(f"保存配置失败: {str(e)}")
            raise
    
    # 以下为新增的参数获取属性（直接返回配置值或默认值）
    @property
    def qr_password(self) -> str:
        return self.get('QR_PASSWORD', self._defaults['QR_PASSWORD'])

    @property
    def web_host(self) -> str:
        return self.get('web_host', self._defaults['web_host'])
    
    @property
    def web_port(self) -> str:
        return self.get('web_port', self._defaults['web_port'])
    
    @property
    def debug(self) -> bool:
        return self.get('debug', self._defaults['debug'])
    
    @property
    def downloads_dir(self) -> str:
        return self.get('downloads_dir', self._defaults['downloads_dir'])
    
    @property
    def max_file_size(self) -> int:
        return self.get('max_file_size', self._defaults['max_file_size'])
    
    @property
    def request_timeout(self) -> int:
        return self.get('request_timeout', self._defaults['request_timeout'])
    
    @property
    def log_level(self) -> str:
        return self.get('log_level', self._defaults['log_level'])
    
    @property
    def cors_origins(self) -> str:
        return self.get('cors_origins', self._defaults['cors_origins'])
    
    def __getitem__(self, key: str) -> Any:
        """通过索引获取配置项"""
        return self.config[key]
    
    def __contains__(self, key: str) -> bool:
        """检查配置项是否存在"""
        return key in self.config