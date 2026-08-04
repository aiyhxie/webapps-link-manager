"""
签名凭证的签发与校验。

用途：两类**无状态或半无状态**的短期凭证
- 跨域跳转凭证（typ="handoff"）：管理域签发、预览域消费，60 秒有效。
  签名保证不可伪造，但「一次性」必须靠服务端记录 jti（见 session_store），
  单靠签名做不到用过即失效。
- 项目访问凭证（typ="access"）：项目访问密码校验通过后签发，8 小时有效，
  完全不落库。密码变更后旧凭证必须失效，做法是把当前 bcrypt 哈希的前缀
  放进 payload 的 pv 字段，密码一改哈希就变、pv 对不上，凭证自然失效。

不引入 PyJWT：格式为 b64u(json(payload)) + "." + b64u(hmac_sha256)，
校验用 hmac.compare_digest() 防时序攻击。
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

_server_dir = Path(__file__).parent.parent.resolve()
if str(_server_dir) not in sys.path:
    sys.path.insert(0, str(_server_dir))

import config

logger = logging.getLogger("webapps.auth.signing")

# 缓存解析好的密钥，避免每次签名都读文件
_secret_cache: Optional[bytes] = None


def _generate_and_persist_secret() -> bytes:
    """
    生成随机密钥并持久化到 config.AUTH_SECRET_FILE。

    仅用于 embedded（本机开发）模式：密钥必须跨重启保持稳定，否则每次重启
    都会让已签发的访问凭证全部失效，用户被迫重新输项目密码。
    文件权限设为 0600，且已在 .gitignore 中排除。
    """
    path: Path = config.AUTH_SECRET_FILE
    value = secrets.token_urlsafe(32)
    try:
        path.write_text(value + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError as e:
        # 写不下去也不能让进程起不来：退化为进程内临时密钥，
        # 代价是重启后已签发凭证失效，功能仍可用。
        logger.warning(
            f"无法持久化签名密钥到 {path.name}（{e}），本次使用进程内临时密钥；"
            f"重启后此前签发的访问凭证将失效"
        )
    return value.encode("utf-8")


def _load_secret() -> bytes:
    """解析签名密钥。环境变量优先；embedded 模式下缺失则自动生成并持久化。"""
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache

    if config.AUTH_SIGNING_SECRET:
        _secret_cache = config.AUTH_SIGNING_SECRET.encode("utf-8")
        return _secret_cache

    if config.AUTH_MODE == "gateway":
        # gateway 模式必须显式提供，config.validate_auth_config() 会在启动阶段
        # 拦住这种情况；这里再挡一次，防止绕过启动校验直接调用本模块。
        raise config.ConfigError("gateway 模式下 AUTH_SIGNING_SECRET 必须显式设置")

    path: Path = config.AUTH_SECRET_FILE
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                _secret_cache = existing.encode("utf-8")
                return _secret_cache
    except OSError as e:
        logger.warning(f"读取 {path.name} 失败（{e}），将重新生成签名密钥")

    _secret_cache = _generate_and_persist_secret()
    return _secret_cache


def reset_secret_cache() -> None:
    """清空密钥缓存。仅供测试在切换配置后调用。"""
    global _secret_cache
    _secret_cache = None


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def sign(payload: Dict[str, Any]) -> str:
    """
    签发一份凭证。payload 必须含 typ 与 exp（UTC 秒级时间戳）。

    payload 里不要放任何敏感值：它只做了 base64 编码，不是加密，任何人都能读。
    """
    if "typ" not in payload or "exp" not in payload:
        raise ValueError("payload 必须包含 typ 与 exp 字段")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")
    encoded = _b64u_encode(body)
    mac = hmac.new(_load_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64u_encode(mac)}"


def verify(token: str, expected_typ: str,
           now: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    校验凭证，通过则返回 payload，否则返回 None。

    依次校验：格式、签名、typ 匹配、未过期。任何一项不通过都返回 None，
    不区分失败原因——避免把「签名错」和「已过期」的差别泄露给调用方。
    过期判定用严格大于，与会话过期的边界口径保持一致。
    """
    if not token or "." not in token:
        return None
    encoded, _, sig = token.partition(".")
    if not encoded or not sig:
        return None

    try:
        expected_mac = hmac.new(_load_secret(), encoded.encode("ascii"),
                                hashlib.sha256).digest()
        actual_mac = _b64u_decode(sig)
    except (ValueError, TypeError, config.ConfigError):
        return None
    if not hmac.compare_digest(expected_mac, actual_mac):
        return None

    try:
        payload = json.loads(_b64u_decode(encoded).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    if payload.get("typ") != expected_typ:
        return None

    exp = payload.get("exp")
    if not isinstance(exp, int):
        return None
    current = int(time.time()) if now is None else now
    if current > exp:          # 严格大于才算过期；等于 exp 视为仍然有效
        return None

    return payload


# ── 具体凭证类型 ──────────────────────────────────────────────────────────────

def password_version(password_hash: Optional[str]) -> str:
    """
    由项目当前的密码哈希推出一个「密码版本」标识。

    取 bcrypt 哈希的前 12 个字符：密码一旦修改或移除，哈希随之改变，此前签发
    的访问凭证中的 pv 便对不上，于是在下一次校验时失效——不需要维护任何撤销
    列表。bcrypt 前缀只含算法标识与 salt 片段，无法反推密码。
    """
    return (password_hash or "")[:12]


def issue_access_credential(user_id: str, project_key: str,
                            password_hash: Optional[str]) -> str:
    """项目访问凭证：绑定用户、项目与密码版本，8 小时有效，不落库。"""
    now = int(time.time())
    return sign({
        "typ": "access",
        "sub": user_id,
        "key": project_key,
        "pv": password_version(password_hash),
        "iat": now,
        "exp": now + config.ACCESS_CREDENTIAL_TTL,
    })


def verify_access_credential(token: str, user_id: str, project_key: str,
                             password_hash: Optional[str]) -> bool:
    """
    校验项目访问凭证的四项条件：签名有效、未过期、用户一致、项目一致，
    外加密码版本一致（密码变更后旧凭证失效）。
    """
    payload = verify(token, "access")
    if payload is None:
        return False
    return (
        payload.get("sub") == user_id
        and payload.get("key") == project_key
        and payload.get("pv") == password_version(password_hash)
    )


def issue_handoff_credential(user_id: str, jti: str) -> str:
    """
    跨域跳转凭证：管理域签发给预览域，60 秒有效。

    jti 由调用方生成并记入会话存储，预览域消费时据此保证一次性——
    签名本身无法表达「用过即失效」。
    """
    now = int(time.time())
    return sign({
        "typ": "handoff",
        "sub": user_id,
        "jti": jti,
        "iat": now,
        "exp": now + config.HANDOFF_TTL,
    })
