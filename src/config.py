import yaml
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .crypto_config import encrypt_config, decrypt_config, is_encrypted, has_key_file

# 获取配置文件路径（基于当前文件所在目录）
BASE_DIR = Path(__file__).parent.parent.resolve()


def _resolve_default_config_file() -> Path:
    """解析默认配置文件路径，支持通过环境变量覆盖。"""
    env_config = os.getenv("AUTO_PT_CONFIG_FILE", "").strip()
    if env_config:
        config_path = Path(env_config).expanduser()
        if not config_path.is_absolute():
            config_path = (BASE_DIR / config_path).resolve()
        return config_path
    return BASE_DIR / "config.yaml"


CONFIG_FILE = _resolve_default_config_file()


def _prune_legacy_single_site_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """多站点配置存在时，移除旧版 pt.mteam 残留，避免被重新写回。"""
    if not isinstance(config, dict):
        return config

    cleaned_config = dict(config)
    pt_sites = cleaned_config.get("pt_sites")
    if not isinstance(pt_sites, list) or not pt_sites:
        return cleaned_config

    pt_config = cleaned_config.get("pt")
    if not isinstance(pt_config, dict) or "mteam" not in pt_config:
        return cleaned_config

    cleaned_pt_config = dict(pt_config)
    cleaned_pt_config.pop("mteam", None)
    if cleaned_pt_config:
        cleaned_config["pt"] = cleaned_pt_config
    else:
        cleaned_config.pop("pt", None)

    return cleaned_config


def _normalize_qbittorrent_section(config: Dict[str, Any]) -> Dict[str, Any]:
    """统一 qBittorrent 配置字段，兼容旧版 url/host 写法。"""
    if not isinstance(config, dict):
        return config

    cleaned_config = dict(config)
    qb = cleaned_config.get("qbittorrent")
    if not isinstance(qb, dict):
        return cleaned_config

    normalized_qb = dict(qb)
    host = str(normalized_qb.get("host", "") or "").strip()
    legacy_url = str(normalized_qb.get("url", "") or "").strip()

    if host:
        normalized_qb["host"] = host
    elif legacy_url:
        normalized_qb["host"] = legacy_url

    cleaned_config["qbittorrent"] = normalized_qb
    return cleaned_config


def normalize_qbittorrent_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """公开版 qBittorrent 配置规范化入口。"""
    return _normalize_qbittorrent_section(config)


def get_qbittorrent_host(qb_config: Dict[str, Any]) -> str:
    """提取 qBittorrent 主机地址，兼容 host/url 两种字段。"""
    if not isinstance(qb_config, dict):
        return ""
    return str(qb_config.get("host", "") or qb_config.get("url", "") or "").strip()


def _load_sensitive_from_env() -> Dict[str, Any]:
    """从环境变量加载敏感配置
    
    环境变量优先级高于配置文件
    支持的环境变量：
    - QB_HOST, QB_USERNAME, QB_PASSWORD - qBittorrent 配置
    - APP_SECRET - 应用密钥
    - SITE_<name>_PASSKEY - 站点 passkey
    """
    sensitive = {}
    
    # qBittorrent 配置
    if os.getenv('QB_HOST'):
        sensitive.setdefault('qbittorrent', {})['host'] = os.getenv('QB_HOST')
    if os.getenv('QB_USERNAME'):
        sensitive.setdefault('qbittorrent', {})['username'] = os.getenv('QB_USERNAME')
    if os.getenv('QB_PASSWORD'):
        sensitive.setdefault('qbittorrent', {})['password'] = os.getenv('QB_PASSWORD')
    
    # 应用密钥
    if os.getenv('APP_SECRET'):
        sensitive.setdefault('app', {})['secret'] = os.getenv('APP_SECRET')
    
    # 遍历所有环境变量，查找站点 passkey (SITE_<name>_PASSKEY)
    for key, value in os.environ.items():
        if key.startswith('SITE_') and key.endswith('_PASSKEY'):
            site_name = key[5:-8]  # 去掉 'SITE_' 前缀和 '_PASSKEY' 后缀
            if value:
                # 查找或创建站点配置
                sites = sensitive.get('pt_sites', [])
                found = False
                for site in sites:
                    if site.get('name') == site_name:
                        site['passkey'] = value
                        found = True
                        break
                if not found:
                    sites.append({'name': site_name, 'passkey': value})
                sensitive['pt_sites'] = sites
    
    return sensitive


class Config:
    def __init__(self, config_path: str = None):
        self.config_path = Path(config_path) if config_path else CONFIG_FILE
        self._config = self._load_config()
        # 合并环境变量配置（环境变量优先级更高）
        self._merge_env_config()

    def _merge_env_config(self):
        """合并环境变量配置"""
        env_config = _load_sensitive_from_env()
        
        # 合并 app 配置
        if 'app' in env_config:
            if 'app' not in self._config:
                self._config['app'] = {}
            self._config['app'].update(env_config['app'])
        
        # 合并 qbittorrent 配置
        if 'qbittorrent' in env_config:
            if 'qbittorrent' not in self._config:
                self._config['qbittorrent'] = {}
            self._config['qbittorrent'].update(env_config['qbittorrent'])
        
        # 合并站点配置
        if 'pt_sites' in env_config:
            existing_sites = self._config.get('pt_sites', [])
            for env_site in env_config['pt_sites']:
                found = False
                for existing in existing_sites:
                    if existing.get('name') == env_site.get('name'):
                        existing.update(env_site)
                        found = True
                        break
                if not found:
                    existing_sites.append(env_site)
            self._config['pt_sites'] = existing_sites

        self._config = _normalize_qbittorrent_section(self._config)

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

            # 字段迁移：兼容旧版 qbittorrent.url
            qb = config.get("qbittorrent", {})
            if isinstance(qb, dict) and "url" in qb and "host" not in qb:
                qb["host"] = qb.pop("url")
                config["qbittorrent"] = qb
            
            # 解密敏感字段
            if is_encrypted() and has_key_file():
                config = decrypt_config(config)

            config = _normalize_qbittorrent_section(config)
            return _prune_legacy_single_site_config(config)
        return {}

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    # ==================== 多站点配置支持 ====================
    @property
    def pt_sites(self) -> List[Dict[str, Any]]:
        """获取所有 PT 站点配置列表"""
        return self._config.get("pt_sites", [])

    def get_site_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """根据站点名称获取配置"""
        for site in self.pt_sites:
            if site.get("name") == name:
                return site
        return None

    def get_enabled_sites(self) -> List[Dict[str, Any]]:
        """获取所有启用的站点"""
        return [site for site in self.pt_sites if site.get("enabled", True)]

    def get_site_filter(self, site_name: str) -> Dict[str, Any]:
        """获取指定站点的过滤规则"""
        site = self.get_site_by_name(site_name)
        if site:
            return site.get("filter", {})
        return {}

    def get_site_schedule(self, site_name: str) -> Dict[str, Any]:
        """获取指定站点的运行设置"""
        site = self.get_site_by_name(site_name)
        if site:
            return site.get("schedule", {})
        return {}

    # ==================== 向后兼容的旧属性（已废弃）====================
    @property
    def mteam(self) -> Dict[str, Any]:
        """@deprecated 使用 get_site_by_name('mteam') 替代"""
        site = self.get_site_by_name('mteam')
        return site if site else {}

    @property
    def filter_config(self) -> Dict[str, Any]:
        """@deprecated 使用 get_site_filter(site_name) 替代"""
        # 返回第一个站点的过滤规则作为兼容
        sites = self.pt_sites
        return sites[0].get("filter", {}) if sites else {}

    @property
    def schedule(self) -> Dict[str, Any]:
        """@deprecated 使用 get_site_schedule(site_name) 替代"""
        # 返回第一个站点的运行设置作为兼容
        sites = self.pt_sites
        return sites[0].get("schedule", {}) if sites else {}

    # ==================== 全局配置 ====================
    @property
    def global_schedule(self) -> Dict[str, Any]:
        """获取顶层全局调度配置。"""
        return self._config.get("schedule", {})

    @property
    def qbittorrent(self) -> Dict[str, Any]:
        return self._config.get("qbittorrent", {})

    @property
    def notifications(self) -> Dict[str, Any]:
        return self._config.get("notifications", {})

    @property
    def logging_config(self) -> Dict[str, Any]:
        return self._config.get("logging", {})

    def reload(self):
        self._config = self._load_config()
        # 重新加载后仍需叠加环境变量覆盖
        self._merge_env_config()


# ==================== 工具函数 ====================

def save_config(config_data: Dict[str, Any], config_path: str = None):
    """保存配置文件，自动加密敏感字段
    
    Args:
        config_data: 配置字典
        config_path: 配置文件路径（默认为 config.yaml）
    """
    config_file = config_path or CONFIG_FILE
    try:
        normalized_config = _prune_legacy_single_site_config(config_data)
        normalized_config = _normalize_qbittorrent_section(normalized_config)
        # 加密敏感字段后再保存
        if is_encrypted():
            config_to_save = encrypt_config(normalized_config)
        else:
            config_to_save = normalized_config
        
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config_to_save, f, allow_unicode=True, default_flow_style=False)
            f.flush()
    except Exception as e:
        raise Exception(f"保存配置文件失败：{e}")
