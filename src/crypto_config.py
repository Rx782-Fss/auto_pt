"""
AES 加密模块 - 用于加密敏感配置信息

功能：
- 自动生成/加载密钥文件
- 加密敏感字段（密码、passkey、secret）
- 解密字段供程序使用

密钥文件位置：项目目录下的 auto_pt.key
"""

import os
import base64
import secrets
from pathlib import Path
from typing import Any, Dict, Optional

# 尝试导入 cryptography 库
try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


BASE_DIR = Path(__file__).parent.parent.resolve()
KEY_FILE_ENV = "AUTO_PT_KEY_FILE"


def _default_key_file() -> Path:
    """返回项目默认的旧密钥文件位置。"""
    return BASE_DIR / "auto_pt.key"


def _resolve_key_file() -> Path:
    """解析加密密钥文件路径，Docker 环境可通过环境变量覆盖。"""
    env_key_file = os.getenv(KEY_FILE_ENV, "").strip()
    if env_key_file:
        key_file = Path(env_key_file).expanduser()
        if not key_file.is_absolute():
            key_file = (BASE_DIR / key_file).resolve()
        return key_file

    return _default_key_file()


def _ensure_legacy_key_file_mirrored(key_file: Path, key_data: bytes) -> None:
    """把旧位置的密钥镜像到新位置，避免容器重启后丢失。"""
    legacy_key_file = _default_key_file()
    if key_file == legacy_key_file:
        return

    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        with open(key_file, 'wb') as f:
            f.write(key_data)
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
    except Exception:
        pass

# 需要加密的敏感字段
SENSITIVE_FIELDS = [
    'password',
    'passkey',
    'secret',
    'recovery_code',
    'uid',
    'rss_key',
    'api_key',
]


def _get_key() -> Optional[bytes]:
    """获取或生成加密密钥"""
    if not CRYPTO_AVAILABLE:
        return None

    key_file = _resolve_key_file()
    legacy_key_file = _default_key_file()
    candidate_files = [key_file]
    if key_file != legacy_key_file:
        candidate_files.append(legacy_key_file)

    for candidate_file in candidate_files:
        if not candidate_file.exists():
            continue
        try:
            with open(candidate_file, 'rb') as f:
                key_data = f.read()
            key = base64.urlsafe_b64decode(key_data)
            if candidate_file != key_file:
                _ensure_legacy_key_file_mirrored(key_file, key_data)
            return key
        except Exception:
            continue

    # 生成新密钥
    key = Fernet.generate_key()

    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        with open(key_file, 'wb') as f:
            f.write(base64.urlsafe_b64encode(key))
        # 设置文件权限（Unix-like 系统）
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        return key
    except Exception:
        return None


def _is_value_sensitive(key: str, value: Any) -> bool:
    """判断值是否应该加密
    
    只根据字段名判断，不根据值的内容判断
    """
    if not isinstance(value, str) or not value:
        return False
    
    key_lower = key.lower()
    
    # 检查字段名是否包含敏感关键词
    for field in SENSITIVE_FIELDS:
        if field in key_lower:
            return True
    
    # 额外的字段名检查
    sensitive_keywords = [
        'token',
        'key',
    ]
    for kw in sensitive_keywords:
        if kw in key_lower and ('secret' in key_lower or 'api' in key_lower or 'auth' in key_lower):
            return True
    
    return False


def encrypt_value(value: str) -> str:
    """加密单个值"""
    if not value or not CRYPTO_AVAILABLE:
        return value
    
    key = _get_key()
    if not key:
        return value
    
    try:
        f = Fernet(key)
        encrypted = f.encrypt(value.encode('utf-8'))
        # 添加前缀标记这是加密值
        return f"ENCRYPTED:{base64.urlsafe_b64encode(encrypted).decode('utf-8')}"
    except Exception:
        return value


def decrypt_value(value: str) -> str:
    """解密单个值"""
    if not value or not isinstance(value, str):
        return value
    
    # 检查是否是加密值
    if not value.startswith('ENCRYPTED:'):
        return value
    
    if not CRYPTO_AVAILABLE:
        # 无法解密，返回原值（可能需要用户重新输入）
        return value
    
    try:
        key = _get_key()
        if not key:
            return value
        
        # 去掉前缀，解码
        encrypted_b64 = value[10:]  # 去掉 'ENCRYPTED:'
        encrypted = base64.urlsafe_b64decode(encrypted_b64)
        
        f = Fernet(key)
        decrypted = f.decrypt(encrypted)
        return decrypted.decode('utf-8')
    except Exception:
        # 解密失败，返回原值
        return value


def encrypt_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """递归加密配置中的敏感字段"""
    if not isinstance(config, dict):
        return config
    
    result = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = encrypt_config(value)
        elif _is_value_sensitive(key, value):
            # 加密敏感值
            result[key] = encrypt_value(str(value))
        else:
            result[key] = value
    
    return result


def decrypt_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """递归解密配置中的敏感字段"""
    if not isinstance(config, dict):
        return config
    
    result = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = decrypt_config(value)
        elif isinstance(value, str) and value.startswith('ENCRYPTED:'):
            # 解密敏感值
            result[key] = decrypt_value(value)
        else:
            result[key] = value
    
    return result


def is_encrypted() -> bool:
    """检查是否启用了加密功能"""
    return CRYPTO_AVAILABLE


def has_key_file() -> bool:
    """检查密钥文件是否存在"""
    key_file = _resolve_key_file()
    if key_file.exists():
        return True

    legacy_key_file = _default_key_file()
    if key_file != legacy_key_file and legacy_key_file.exists():
        return True

    return False
