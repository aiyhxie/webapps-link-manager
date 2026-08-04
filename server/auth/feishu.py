"""
飞书开放平台客户端。

只用标准库 urllib，不引入 requests —— 项目运行依赖保持 flask + bcrypt 两项。

端点已在本机对真实环境逐个探测确认（2026-08）：
- 授权页      GET  /open-apis/authen/v1/authorize          ?app_id&redirect_uri&state
- 换用户令牌  POST /open-apis/authen/v2/oauth/token        标准 OAuth2 形态
- 用户信息    GET  /open-apis/authen/v1/user_info          Bearer user_access_token
- 管理员校验  GET  /open-apis/application/v3/is_user_admin ?open_id，用 tenant token
- 租户令牌    POST /open-apis/auth/v3/tenant_access_token/internal

为什么用 v2 而不是 v1 换令牌：v2 要求把 redirect_uri 一起提交，飞书会校验它与
授权时一致，等于多一道防护；v1 只交 code。三代端点当前都可用，v1 保留为兜底。

身份主键用 open_id：它对「本应用 + 该用户」稳定唯一，且不需要额外申请
user_id 相关权限；形如 ou_xxx，天然满足身份头对字符集与长度的限制。
"""
import json
import logging
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

_server_dir = Path(__file__).parent.parent.resolve()
if str(_server_dir) not in sys.path:
    sys.path.insert(0, str(_server_dir))

import config

logger = logging.getLogger("webapps.auth.feishu")

BASE = "https://open.feishu.cn"
AUTHORIZE_URL = f"{BASE}/open-apis/authen/v1/authorize"
TOKEN_URL_V2 = f"{BASE}/open-apis/authen/v2/oauth/token"
TOKEN_URL_V1 = f"{BASE}/open-apis/authen/v1/access_token"
USER_INFO_URL = f"{BASE}/open-apis/authen/v1/user_info"
IS_USER_ADMIN_URL = f"{BASE}/open-apis/application/v3/is_user_admin"
TENANT_TOKEN_URL = f"{BASE}/open-apis/auth/v3/tenant_access_token/internal"
APP_TOKEN_URL = f"{BASE}/open-apis/auth/v3/app_access_token/internal"

TIMEOUT = 5              # 需求：单次调用 5 秒超时，且同一授权流程内不重试
_ssl_ctx = ssl.create_default_context()      # 默认即校验服务端证书

# tenant_access_token 缓存（飞书侧有效期约 2 小时，提前 120 秒失效重取）
_tenant_lock = threading.Lock()
_tenant_token: Optional[str] = None
_tenant_expire_at: int = 0


class FeishuError(Exception):
    """
    飞书接口错误。

    只携带飞书返回的 code 与 msg —— 绝不放 App Secret、access_token 或授权码，
    因为这个异常会被写进审计日志和错误页。
    """

    def __init__(self, code: Any, msg: str, stage: str = ""):
        self.code = code
        self.msg = msg or ""
        self.stage = stage
        super().__init__(f"[{stage or 'feishu'}] code={code} msg={self.msg}")


class FeishuUnavailable(FeishuError):
    """网络层面不可用：超时、连接失败、TLS 失败。"""


def _request(method: str, url: str, *,
             body: Optional[Dict[str, Any]] = None,
             query: Optional[Dict[str, str]] = None,
             bearer: Optional[str] = None,
             stage: str = "") -> Dict[str, Any]:
    """
    发一次请求并返回解析后的 JSON。

    飞书的错误有两种表达：HTTP 4xx/5xx 带 JSON 体，或 HTTP 200 但 code != 0。
    两者统一收敛成 FeishuError，调用方不必分别处理。
    """
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    data = json.dumps(body).encode("utf-8") if body is not None else None

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_ctx) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8")
        except Exception:
            pass
        payload = {}
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            pass
        raise FeishuError(
            payload.get("code") or payload.get("error") or e.code,
            payload.get("msg") or payload.get("error_description") or f"HTTP {e.code}",
            stage,
        )
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
        # 超时、DNS、连接重置、证书问题都归到「不可用」，调用方据此走降级路径
        raise FeishuUnavailable("network", type(e).__name__, stage)

    try:
        payload = json.loads(raw)
    except ValueError:
        raise FeishuError("bad_json", "响应不是合法 JSON", stage)
    if not isinstance(payload, dict):
        raise FeishuError("bad_json", "响应结构异常", stage)

    code = payload.get("code")
    if code not in (None, 0):
        raise FeishuError(code, payload.get("msg") or "", stage)
    return payload


# ── 授权页 ───────────────────────────────────────────────────────────────────

def authorize_url(redirect_uri: str, state: str) -> str:
    """构造飞书授权页地址。用户在这里扫码或确认，随后被重定向回 redirect_uri。"""
    params = {
        "app_id": config.FEISHU_APP_ID,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


# ── 令牌 ─────────────────────────────────────────────────────────────────────

def exchange_user_token(code: str, redirect_uri: str) -> str:
    """
    用授权码换 user_access_token（v2 标准 OAuth2）。

    redirect_uri 必须与授权时提交的一致，飞书会校验；不一致会失败，
    这正好挡住把授权码重放到别的回调地址的做法。
    """
    payload = _request("POST", TOKEN_URL_V2, stage="exchange_token", body={
        "grant_type": "authorization_code",
        "client_id": config.FEISHU_APP_ID,
        "client_secret": config.FEISHU_APP_SECRET,
        "code": code,
        "redirect_uri": redirect_uri,
    })
    # v2 是扁平的 OAuth2 结构；保留对 data 包装的兼容，避免飞书后续调整时直接崩
    token = payload.get("access_token") or (payload.get("data") or {}).get("access_token")
    if not token:
        raise FeishuError("no_token", "响应中没有 access_token", "exchange_token")
    return token


def _get_tenant_token() -> str:
    """取 tenant_access_token，带进程内缓存。"""
    global _tenant_token, _tenant_expire_at
    now = int(time.time())
    with _tenant_lock:
        if _tenant_token and now < _tenant_expire_at:
            return _tenant_token
        payload = _request("POST", TENANT_TOKEN_URL, stage="tenant_token", body={
            "app_id": config.FEISHU_APP_ID,
            "app_secret": config.FEISHU_APP_SECRET,
        })
        token = payload.get("tenant_access_token")
        if not token:
            raise FeishuError("no_token", "响应中没有 tenant_access_token", "tenant_token")
        expire = payload.get("expire")
        ttl = expire if isinstance(expire, int) and expire > 0 else 7200
        _tenant_token = token
        _tenant_expire_at = now + max(ttl - 120, 60)   # 提前 2 分钟过期
        return token


def reset_tenant_token_cache() -> None:
    """清空租户令牌缓存。供测试使用。"""
    global _tenant_token, _tenant_expire_at
    with _tenant_lock:
        _tenant_token, _tenant_expire_at = None, 0


# ── 用户信息 ─────────────────────────────────────────────────────────────────

def get_user_info(user_access_token: str) -> Dict[str, str]:
    """
    取登录用户的身份信息。

    返回 {"user_id", "name", "open_id", "union_id", "avatar"}，其中 user_id
    取 open_id —— 本系统统一以 open_id 作为身份主键。
    姓名截断到 64 字符，与存储与身份头的长度约束对齐。
    """
    payload = _request("GET", USER_INFO_URL, stage="user_info",
                       bearer=user_access_token)
    data = payload.get("data") or payload
    open_id = (data.get("open_id") or "").strip()
    if not open_id:
        raise FeishuError("no_open_id", "响应中没有 open_id", "user_info")
    name = (data.get("name") or data.get("en_name") or "").strip()[:64]
    return {
        "user_id": open_id,
        "open_id": open_id,
        "union_id": (data.get("union_id") or "").strip(),
        "name": name or open_id,
        "avatar": (data.get("avatar_url") or data.get("avatar_thumb") or "").strip(),
    }


# ── 应用管理员校验 ───────────────────────────────────────────────────────────

def is_app_admin(open_id: str) -> bool:
    """
    校验该用户是否为本飞书应用的管理员。

    仅在本系统管理员名单为空时调用一次，用于把首个超级管理员 bootstrap 出来，
    之后完全依据本地名单判定，不再依赖飞书接口可用性。

    任何失败都由调用方按「跳过授予、完成登录、写审计」处理，因此这里让异常
    原样抛出，不在内部吞掉。
    """
    if not open_id:
        return False
    payload = _request("GET", IS_USER_ADMIN_URL, stage="is_user_admin",
                       query={"open_id": open_id},
                       bearer=_get_tenant_token())
    data = payload.get("data") or payload
    return bool(data.get("is_app_admin"))


# ── 连通性自检 ───────────────────────────────────────────────────────────────

def selftest() -> Dict[str, Any]:
    """
    不需要用户交互的连通性自检：验证凭据可用、网络可达、端点形态正确。

    只用 App ID + App Secret 就能跑，适合部署后立刻确认配置是否正确。
    返回结构里不含任何令牌内容。
    """
    result: Dict[str, Any] = {"app_id": config.FEISHU_APP_ID}
    try:
        payload = _request("POST", APP_TOKEN_URL, stage="selftest", body={
            "app_id": config.FEISHU_APP_ID,
            "app_secret": config.FEISHU_APP_SECRET,
        })
        result["credentials"] = "ok"
        result["app_token_expire"] = payload.get("expire")
    except FeishuError as e:
        result["credentials"] = f"failed: code={e.code} msg={e.msg}"
        return result
    try:
        _get_tenant_token()
        result["tenant_token"] = "ok"
    except FeishuError as e:
        result["tenant_token"] = f"failed: code={e.code} msg={e.msg}"
    result["allowed_callbacks"] = list(config.allowed_callback_urls())
    return result
