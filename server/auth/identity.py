"""
身份解析中间件。

核心不变式（Property 1）：**客户端传入的 X-Auth-* 请求头永远不影响身份判定。**

两种部署形态用两条独立机制保证：
- embedded：WSGI 层直接从 environ 删掉所有 HTTP_X_AUTH* 键，应用根本看不到它们；
            身份只从会话 Cookie 解析。
- gateway ：先校验 TCP 对端地址是否在 TRUSTED_GATEWAY_IPS 内，不在则 403 且
            不采信任何 X-Auth-*；在才读网关注入的值。

为什么在 WSGI 层删而不是「读的时候忽略」：Flask 的 request.headers 是不可变的，
"忽略" 依赖每个读取点都自觉，漏一处就是漏洞。从 environ 删掉是结构性保证。
注意 WSGI 会把 `X-Auth-User-Id` 与 `X_Auth_User_Id` 都规整成 HTTP_X_AUTH_USER_ID，
所以一个前缀判断同时覆盖了连字符与下划线两种伪造写法。
"""
import logging
import sys
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple

from flask import g, request

_server_dir = Path(__file__).parent.parent.resolve()
if str(_server_dir) not in sys.path:
    sys.path.insert(0, str(_server_dir))

import config
import user_directory
from permissions import Actor, SOURCE_EMERGENCY, SOURCE_FEISHU
from auth import session_store

logger = logging.getLogger("webapps.auth.identity")

# 会话 Cookie 名：两域必须不同，且 Domain 只设完整主机名，不设父域
COOKIE_ADMIN = "wl_sid"
COOKIE_PREVIEW = "wl_psid"

HEADER_USER_ID = "X-Auth-User-Id"
HEADER_USER_NAME = "X-Auth-User-Name"

# X-Auth-User-Id 的合法字符集与长度（需求 2.10）
_ID_MAX = 64


class StripAuthHeaders:
    """
    WSGI 中间件：删除客户端传入的所有 X-Auth-* 头。

    embedded 模式下无条件生效。gateway 模式下不在这里删——那时这些头是网关
    注入的合法输入，由 identity 层的对端地址校验来把关（网关自身也必须清洗
    客户端的同名头，见 deploy/nginx.conf.example）。
    """

    def __init__(self, wsgi_app, enabled: bool = True):
        self.wsgi_app = wsgi_app
        self.enabled = enabled

    def __call__(self, environ, start_response):
        if self.enabled:
            for key in [k for k in environ if k.startswith("HTTP_X_AUTH")]:
                del environ[key]
        return self.wsgi_app(environ, start_response)


def _host_of(origin: str) -> str:
    if not origin:
        return ""
    parsed = urllib.parse.urlsplit(origin if "//" in origin else f"//{origin}")
    return (parsed.netloc or parsed.path).lower()


def current_domain() -> str:
    """
    判定当前请求属于管理域还是预览域。

    embedded 模式下只有一个 origin，一律算管理域 —— 需求 4 的域名隔离在这种
    形态下无法实现，验收延后到 gateway 形态（设计文档已写明这一点）。
    """
    if config.AUTH_MODE != "gateway":
        return session_store.DOMAIN_ADMIN
    preview_host = _host_of(config.PREVIEW_ORIGIN)
    if preview_host and request.host.lower() == preview_host:
        return session_store.DOMAIN_PREVIEW
    return session_store.DOMAIN_ADMIN


def cookie_name_for(domain: str) -> str:
    return COOKIE_PREVIEW if domain == session_store.DOMAIN_PREVIEW else COOKIE_ADMIN


def cookie_domain_for_request() -> Optional[str]:
    """
    会话 Cookie 的 Domain 属性：当前请求的完整主机名，**绝不**设成父域，
    否则管理域与预览域的 Cookie 会互相可见，域隔离就白做了。

    带端口的主机名（本机开发的 localhost:8080）不能作为 Domain 值，
    此时返回 None，让浏览器按 host-only 处理，效果同样是不跨域共享。
    """
    host = request.host or ""
    if ":" in host:
        return None
    return host or None


def _is_valid_user_id(value: str) -> bool:
    if not value or len(value) > _ID_MAX:
        return False
    return all(c.isalnum() or c in "_-" for c in value)


def _peer_trusted() -> bool:
    peer = (request.remote_addr or "").strip()
    return peer in config.TRUSTED_GATEWAY_IPS


def encode_user_name(name: str) -> str:
    """
    把姓名编码成可安全放进 HTTP 头的 ASCII（需求 2.11）。

    先 UTF-8 再百分号编码，编码后不超过 256 字节，且截断必须落在**字符**边界上。

    为什么不在编码后的字符串上按字节裁剪：一个中文字符编码成 `%E8%B0%A2`（9 个
    字符、3 个字节），emoji 更长。在编码串上裁剪即使避开了 `%XX` 三元组，也可能
    把一个多字节 UTF-8 序列切成两半，解码时直接抛 UnicodeDecodeError。所以改为
    从原字符串尾部逐字符回退，编码后长度达标即止 —— 这样得到的一定是完整字符。
    """
    text = name or ""
    encoded = urllib.parse.quote(text.encode("utf-8"), safe="")
    while len(encoded) > 256 and text:
        text = text[:-1]
        encoded = urllib.parse.quote(text.encode("utf-8"), safe="")
    return encoded


def decode_user_name(value: str, fallback: str) -> str:
    """解码失败时回退用 user_id 展示，不阻断请求（需求 2.14）。"""
    if not value:
        return fallback
    try:
        return urllib.parse.unquote(value, errors="strict") or fallback
    except (UnicodeDecodeError, ValueError):
        return fallback


def _actor_from_session(record: dict) -> Actor:
    user_id = record.get("user_id", "")
    kind = record.get("kind", SOURCE_FEISHU)
    if kind == session_store.KIND_EMERGENCY:
        # 应急通道会话在有效期内直接拥有超级管理员权限（需求 9.9）
        return Actor(user_id=user_id, name=record.get("name") or user_id,
                     is_admin=True, is_super=True, source=SOURCE_EMERGENCY)
    return Actor(
        user_id=user_id,
        name=user_directory.get_display_name(user_id, record.get("name", "")),
        is_admin=user_directory.is_admin(user_id),
        is_super=user_directory.is_super_admin(user_id),
        source=SOURCE_FEISHU,
    )


def resolve_actor() -> Tuple[Optional[Actor], Optional[int]]:
    """
    解析当前操作者。

    返回 (actor, error_status)：
    - (Actor, None)  已认证
    - (None, 403)    gateway 模式下对端不是可信网关
    - (None, 401)    未认证 / 会话过期 / 身份头缺失或格式非法
    """
    domain = current_domain()

    if config.AUTH_MODE == "gateway":
        if not _peer_trusted():
            logger.warning("拒绝来自非可信来源的请求，不采信任何 X-Auth-* 头")
            return None, 403
        raw_id = (request.headers.get(HEADER_USER_ID) or "").strip()
        if not _is_valid_user_id(raw_id):
            return None, 401
        raw_name = request.headers.get(HEADER_USER_NAME) or ""
        name = decode_user_name(raw_name, raw_id)
        return Actor(
            user_id=raw_id,
            name=user_directory.get_display_name(raw_id, name),
            is_admin=user_directory.is_admin(raw_id),
            is_super=user_directory.is_super_admin(raw_id),
            source=SOURCE_FEISHU,
        ), None

    # embedded：身份只来自会话 Cookie
    session_id = request.cookies.get(cookie_name_for(domain), "")
    record = session_store.get_valid_session(session_id, domain)
    if not record:
        return None, 401
    session_store.touch(session_id)
    g.session_id = session_id
    return _actor_from_session(record), None


def resolve_session_actor(domain: str) -> Tuple[Optional[Actor], Optional[str]]:
    """
    直接按会话 Cookie 解析身份（不看请求头），返回 (actor, session_id)。

    /auth/verify 校验端点用它 —— 那个端点是网关的上游，必须自己看 Cookie，
    不能反过来依赖网关注入的头，否则就成了循环依赖。
    """
    session_id = request.cookies.get(cookie_name_for(domain), "")
    record = session_store.get_valid_session(session_id, domain)
    if not record:
        return None, None
    session_store.touch(session_id)
    return _actor_from_session(record), session_id


def current_actor() -> Optional[Actor]:
    return getattr(g, "actor", None)


def login_url(return_to: str = "") -> str:
    if return_to:
        return f"/auth/login?return_to={urllib.parse.quote(return_to, safe='')}"
    return "/auth/login"


def wants_html() -> bool:
    return "text/html" in (request.headers.get("Accept") or "")
