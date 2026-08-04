"""
会话存储：会话记录、OAuth state、跨域跳转凭证 jti、应急通道失败计数。

设计要点：
- 复用项目现有的 AtomicJSONStore（原子写入 + 自动备份 + 跨进程文件锁），
  不引入 SQLite。多 worker 部署下 flock 仍然正确。
- 时间统一为 UTC 秒级整数，避免时区与字符串比较带来的歧义。
- 过期判定一律用**严格大于**：空闲时长等于 604800 秒仍然有效，
  当前时间等于绝对过期时间仍然有效。这条边界口径在需求里是明确的。
- 活跃时间 5 分钟节流：300 秒内的重复请求不落盘，避免每个请求都全量重写文件。
  按几十人规模，正常使用下每人每 5 分钟最多一次写入。用户数到数百人时
  应换成 SQLite，这是本实现有意接受的容量上界。

容器结构（auth_sessions.json）：
{
  "sessions":  { "<sid>": {user_id, name, domain, kind, created_at,
                           last_seen_at, expires_at} },
  "states":    { "<state>": {return_to, redirect_uri, expires_at, used} },
  "handoffs":  { "<jti>": {user_id, expires_at, used} },
  "emergency_failures": { "<account>": {count, first_at, blocked_until} }
}
"""
import json
import logging
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_server_dir = Path(__file__).parent.parent.resolve()
if str(_server_dir) not in sys.path:
    sys.path.insert(0, str(_server_dir))

import config
import audit
from atomic_store import AtomicJSONStore

logger = logging.getLogger("webapps.auth.session_store")

DOMAIN_ADMIN = "admin"
DOMAIN_PREVIEW = "preview"
VALID_DOMAINS = (DOMAIN_ADMIN, DOMAIN_PREVIEW)

KIND_FEISHU = "feishu"
KIND_EMERGENCY = "emergency"

_EMPTY = {
    "sessions": {},
    "states": {},
    "handoffs": {},
    "emergency_failures": {},
}

_store = AtomicJSONStore(config.AUTH_SESSIONS_FILE, empty_default=_EMPTY)


def _now() -> int:
    return int(time.time())


def _container(data: Dict[str, Any], name: str) -> Dict[str, Any]:
    """取容器，缺失时就地补上——兼容早期写入的不完整文件。"""
    if not isinstance(data.get(name), dict):
        data[name] = {}
    return data[name]


# ── 会话 ─────────────────────────────────────────────────────────────────────

def _is_expired(record: Dict[str, Any], now: Optional[int] = None) -> bool:
    """
    过期判定。两个条件任一命中即过期：
    - 空闲时长严格大于 SESSION_IDLE_MAX
    - 当前时间严格大于绝对过期时间
    """
    current = _now() if now is None else now
    last_seen = record.get("last_seen_at")
    expires_at = record.get("expires_at")
    if not isinstance(last_seen, int) or not isinstance(expires_at, int):
        return True                      # 字段缺失或类型不对，按过期处理
    if current - last_seen > config.SESSION_IDLE_MAX:
        return True
    if current > expires_at:
        return True
    return False


def create_session(user_id: str, name: str, domain: str,
                   kind: str = KIND_FEISHU,
                   ttl: Optional[int] = None) -> str:
    """
    创建会话并返回会话标识（256 位熵）。

    last_seen_at 与 created_at 一并设为当前时间，保证新建会话立刻能通过
    过期检查（否则 last_seen_at 缺省为 0 会被当成早已过期）。

    ttl 为 None 时用默认的绝对上限；应急通道传入固定的 60 分钟，
    且该有效期不会被 touch() 续期。
    """
    if domain not in VALID_DOMAINS:
        raise ValueError(f"domain 必须是 {VALID_DOMAINS} 之一")
    session_id = secrets.token_urlsafe(32)          # 32 字节 = 256 位熵
    now = _now()
    lifetime = config.SESSION_ABSOLUTE_MAX if ttl is None else ttl
    with _store.transaction() as data:
        _container(data, "sessions")[session_id] = {
            "user_id": user_id,
            "name": name,
            "domain": domain,
            "kind": kind,
            "created_at": now,
            "last_seen_at": now,
            "expires_at": now + lifetime,
        }
    return session_id


def get_valid_session(session_id: str, domain: str) -> Optional[Dict[str, Any]]:
    """
    取一条有效会话。以下情况返回 None：
    - 标识为空或不存在
    - 已过期（同时把过期记录删掉）
    - 会话所属域与请求域不一致（两域会话互不通用，且不刷新活跃时间）
    """
    if not session_id:
        return None
    data = _store.load()
    record = _container(data, "sessions").get(session_id)
    if not record:
        return None
    if record.get("domain") != domain:
        return None
    if _is_expired(record):
        delete_session(session_id)
        return None
    return dict(record)


def touch(session_id: str) -> None:
    """
    刷新活跃时间，5 分钟节流。

    应急通道会话（kind=emergency）有固定有效期，不做续期——这里只更新
    last_seen_at，不动 expires_at，所以对它天然安全。
    """
    now = _now()
    data = _store.load()
    record = _container(data, "sessions").get(session_id)
    if not record:
        return
    last_seen = record.get("last_seen_at", 0)
    if isinstance(last_seen, int) and now - last_seen <= config.SESSION_TOUCH_INTERVAL:
        return                                       # 节流窗口内，不落盘
    with _store.transaction() as tx:
        tx_record = _container(tx, "sessions").get(session_id)
        if tx_record is not None:
            tx_record["last_seen_at"] = now


def delete_session(session_id: str) -> bool:
    """
    删除会话，幂等：记录不存在时同样返回成功语义（False 仅表示原本不存在）。
    只删指定标识这一条，不影响同一用户在另一个域的会话。
    """
    if not session_id:
        return False
    with _store.transaction() as data:
        sessions = _container(data, "sessions")
        return sessions.pop(session_id, None) is not None


def count_sessions() -> int:
    return len(_container(_store.load(), "sessions"))


# ── OAuth state ──────────────────────────────────────────────────────────────

def create_state(return_to: str, redirect_uri: str) -> str:
    """创建 OAuth state（128 位熵），记录回跳路径与本次使用的回调地址。"""
    state = secrets.token_urlsafe(16)               # 16 字节 = 128 位熵
    with _store.transaction() as data:
        _container(data, "states")[state] = {
            "return_to": return_to,
            "redirect_uri": redirect_uri,
            "expires_at": _now() + config.OAUTH_STATE_TTL,
            "used": False,
        }
    return state


def consume_state(state: str) -> Optional[Dict[str, Any]]:
    """
    一次性消费 state：存在、未过期、未使用才返回记录，并在同一个事务里
    标记为已使用。先标记再让调用方去换令牌，避免并发重放。

    四种失败（缺失 / 无记录 / 已过期 / 已使用）统一返回 None，
    调用方一律按 400 处理，不区分原因。
    """
    if not state:
        return None
    with _store.transaction() as data:
        record = _container(data, "states").get(state)
        if not record or record.get("used"):
            return None
        expires_at = record.get("expires_at")
        if not isinstance(expires_at, int) or _now() > expires_at:
            return None
        record["used"] = True
        return dict(record)


# ── 跨域跳转凭证 jti ─────────────────────────────────────────────────────────

def register_handoff(user_id: str) -> str:
    """登记一个跳转凭证 jti，返回该 jti。签名部分由 signing 模块负责。"""
    jti = secrets.token_urlsafe(16)
    with _store.transaction() as data:
        _container(data, "handoffs")[jti] = {
            "user_id": user_id,
            "expires_at": _now() + config.HANDOFF_TTL,
            "used": False,
        }
    return jti


def consume_handoff(jti: str, user_id: str) -> bool:
    """
    一次性消费跳转凭证。要求存在、未过期、未使用，且 user_id 与登记时一致
    （凭证 payload 可被读取但不可伪造，这里再比一次防止张冠李戴）。
    """
    if not jti:
        return False
    with _store.transaction() as data:
        record = _container(data, "handoffs").get(jti)
        if not record or record.get("used"):
            return False
        expires_at = record.get("expires_at")
        if not isinstance(expires_at, int) or _now() > expires_at:
            return False
        if record.get("user_id") != user_id:
            return False
        record["used"] = True
        return True


# ── 应急通道失败计数（15 分钟滑动窗口）──────────────────────────────────────

def emergency_is_blocked(account: str) -> Tuple[bool, int]:
    """返回 (是否处于封禁中, 剩余秒数)。"""
    data = _store.load()
    record = _container(data, "emergency_failures").get(account)
    if not record:
        return False, 0
    blocked_until = record.get("blocked_until")
    if isinstance(blocked_until, int):
        remaining = blocked_until - _now()
        if remaining > 0:
            return True, remaining
    return False, 0


def emergency_record_failure(account: str, window: int = 900,
                             threshold: int = 5) -> None:
    """
    记录一次登录失败。滑动窗口内累计达到阈值则封禁同样长度的时间。
    窗口外的旧失败自动作废（不是简单累加，避免一天下来凑满 5 次被误封）。
    """
    now = _now()
    with _store.transaction() as data:
        failures = _container(data, "emergency_failures")
        record = failures.get(account) or {}
        first_at = record.get("first_at")
        count = record.get("count", 0)
        if not isinstance(first_at, int) or now - first_at > window:
            first_at, count = now, 0     # 窗口已过，重新起算
        count += 1
        record.update({"count": count, "first_at": first_at})
        if count >= threshold:
            record["blocked_until"] = now + window
        failures[account] = record


def emergency_clear_failures(account: str) -> None:
    """登录成功后清零该账号的失败计数与封禁状态。"""
    with _store.transaction() as data:
        _container(data, "emergency_failures").pop(account, None)


# ── 启动引导与清理 ───────────────────────────────────────────────────────────

def bootstrap() -> Dict[str, int]:
    """
    进程启动时调用：检测存储文件状态、清理全部过期记录、原子写回。

    文件损坏时的降级路径：AtomicJSONStore.load() 会先尝试从备份恢复，
    无可用备份则退回空集合。两种情况都写一条审计记录，但**不终止启动**——
    会话丢了让大家重新扫码即可，让服务起不来的代价更大。

    返回各容器清理前后的数量，供启动日志输出。
    """
    path: Path = config.AUTH_SESSIONS_FILE
    corrupted = False
    if path.exists():
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            corrupted = True

    now = _now()
    stats = {"sessions_kept": 0, "sessions_dropped": 0,
             "states_dropped": 0, "handoffs_dropped": 0}

    with _store.transaction() as data:
        sessions = _container(data, "sessions")
        for sid in list(sessions.keys()):
            if _is_expired(sessions[sid], now):
                del sessions[sid]
                stats["sessions_dropped"] += 1
        stats["sessions_kept"] = len(sessions)

        states = _container(data, "states")
        for key in list(states.keys()):
            record = states[key]
            expires_at = record.get("expires_at")
            if record.get("used") or not isinstance(expires_at, int) or now > expires_at:
                del states[key]
                stats["states_dropped"] += 1

        handoffs = _container(data, "handoffs")
        for key in list(handoffs.keys()):
            record = handoffs[key]
            expires_at = record.get("expires_at")
            if record.get("used") or not isinstance(expires_at, int) or now > expires_at:
                del handoffs[key]
                stats["handoffs_dropped"] += 1

        failures = _container(data, "emergency_failures")
        for key in list(failures.keys()):
            blocked_until = failures[key].get("blocked_until")
            first_at = failures[key].get("first_at")
            newest = max(
                blocked_until if isinstance(blocked_until, int) else 0,
                first_at if isinstance(first_at, int) else 0,
            )
            if newest and now - newest > 900:
                del failures[key]

    if corrupted:
        recovered = stats["sessions_kept"] > 0
        detail = ("已从备份恢复会话记录" if recovered
                  else "无可用备份，以空会话集合启动，全部用户需重新登录")
        logger.warning(f"会话存储文件损坏：{detail}")
        try:
            audit.log("admin", "会话存储降级", actor="system", ip="",
                      target=path.name, detail=detail)
        except Exception:
            pass                          # 审计写失败不能影响启动

    return stats
