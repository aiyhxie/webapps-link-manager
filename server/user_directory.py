"""
用户档案与管理员名单。

两者都存在 metadata.json 里（新增顶层键），而不是单独文件：项目列表接口本来
就要加载 metadata，同一次 load() 就能拿到负责人姓名，省掉一次文件读取。
会话数据则**不能**放这里 —— 它写得太频繁，会把项目元数据卷进无谓的备份轮转。

顶层键：
- _system_users_      用户档案：{open_id: {name, first_login_at, last_login_at}}
                      「指定负责人」「添加管理员」的候选来源。因为走的是最小权限
                      路线（没申请通讯录读取），员工必须先登录过一次才会进档案。
- _system_admin_list_ 管理员名单：{open_id: {name, level, created_at}}
                      level 取 super / normal，两级对项目权限一致，
                      区别只在于 super 可维护名单与指定负责人。
- _system_admins_     既有的用户名+bcrypt 密码条目，用途收窄为应急管理员通道，
                      不参与飞书登录用户的管理员判定。
"""
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_server_dir = Path(__file__).parent.resolve()
if str(_server_dir) not in sys.path:
    sys.path.insert(0, str(_server_dir))

import metadata

USERS_KEY = "_system_users_"
ADMIN_LIST_KEY = "_system_admin_list_"

LEVEL_SUPER = "super"
LEVEL_NORMAL = "normal"
VALID_LEVELS = (LEVEL_SUPER, LEVEL_NORMAL)

NAME_MAX = 64
ADMIN_LIST_MAX = 100


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _bucket(meta: Dict[str, Any], key: str) -> Dict[str, Any]:
    """取顶层容器，缺失时就地补上（兼容迁移前的旧文件）。"""
    if not isinstance(meta.get(key), dict):
        meta[key] = {}
    return meta[key]


# ── 用户档案 ─────────────────────────────────────────────────────────────────

def upsert_user(user_id: str, name: str) -> Dict[str, Any]:
    """
    登录成功后写入或更新用户档案。

    首次写入时记录 first_login_at 且此后不再改动；姓名每次登录都以飞书返回的
    为准（改名后本系统跟着更新），截断到 64 字符。
    """
    if not user_id:
        raise ValueError("user_id 不能为空")
    clean_name = (name or "").strip()[:NAME_MAX] or user_id
    now = _now_iso()
    with metadata._store.transaction() as meta:
        users = _bucket(meta, USERS_KEY)
        record = users.get(user_id)
        if not isinstance(record, dict):
            record = {"first_login_at": now}
        record["name"] = clean_name
        record["last_login_at"] = now
        record.setdefault("first_login_at", now)
        users[user_id] = record
        return dict(record)


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    record = _bucket(metadata.load_metadata(), USERS_KEY).get(user_id)
    return dict(record) if isinstance(record, dict) else None


def user_exists(user_id: str) -> bool:
    return get_user(user_id) is not None


def get_display_name(user_id: str, fallback: str = "") -> str:
    """
    取展示用姓名：优先用户档案里的最新姓名，查不到则用调用方给的快照。

    这里没有网络调用，所以「查询超时降级」在本实现下不会发生；降级路径仍然存在，
    用于 owner_id 查不到档案的真实情况（员工离职后被清理，或超管把项目指给了
    尚未登录过的人）。
    """
    record = get_user(user_id)
    if record and record.get("name"):
        return record["name"]
    return fallback or user_id


def list_users() -> List[Dict[str, Any]]:
    """按姓名排序返回全部已登录用户，供「指定负责人」「添加管理员」选人。"""
    users = _bucket(metadata.load_metadata(), USERS_KEY)
    out = []
    for user_id, record in users.items():
        if not isinstance(record, dict):
            continue
        out.append({
            "userId": user_id,
            "name": record.get("name") or user_id,
            "firstLoginAt": record.get("first_login_at", ""),
            "lastLoginAt": record.get("last_login_at", ""),
        })
    return sorted(out, key=lambda x: (x["name"], x["userId"]))


# ── 管理员名单 ───────────────────────────────────────────────────────────────

def get_admin(user_id: str) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    record = _bucket(metadata.load_metadata(), ADMIN_LIST_KEY).get(user_id)
    return dict(record) if isinstance(record, dict) else None


def is_admin(user_id: str) -> bool:
    return get_admin(user_id) is not None


def is_super_admin(user_id: str) -> bool:
    record = get_admin(user_id)
    return bool(record and record.get("level") == LEVEL_SUPER)


def admin_count() -> int:
    return len(_bucket(metadata.load_metadata(), ADMIN_LIST_KEY))


def super_admin_count() -> int:
    admins = _bucket(metadata.load_metadata(), ADMIN_LIST_KEY)
    return sum(1 for r in admins.values()
               if isinstance(r, dict) and r.get("level") == LEVEL_SUPER)


def list_admins() -> List[Dict[str, Any]]:
    admins = _bucket(metadata.load_metadata(), ADMIN_LIST_KEY)
    out = []
    for user_id, record in admins.items():
        if not isinstance(record, dict):
            continue
        out.append({
            "userId": user_id,
            "name": record.get("name") or get_display_name(user_id),
            "level": record.get("level", LEVEL_NORMAL),
            "createdAt": record.get("created_at", ""),
        })
    # 超管排在前面，其次按姓名
    return sorted(out, key=lambda x: (x["level"] != LEVEL_SUPER, x["name"]))


def bootstrap_super_admin(user_id: str, name: str) -> bool:
    """
    名单为空时把该用户写成首个超级管理员。

    整个「判空 + 写入」在同一个事务里完成，因此并发的多次首登最终只会产生一个
    超管条目：第二个请求进来时名单已非空，直接返回 False。

    返回 True 表示本次确实授予了超管。
    """
    if not user_id:
        return False
    clean_name = (name or "").strip()[:NAME_MAX] or user_id
    with metadata._store.transaction() as meta:
        admins = _bucket(meta, ADMIN_LIST_KEY)
        if admins:
            return False
        admins[user_id] = {
            "name": clean_name,
            "level": LEVEL_SUPER,
            "created_at": _now_iso(),
        }
        return True


def add_admin(user_id: str, name: str = "",
              level: str = LEVEL_NORMAL) -> Tuple[bool, str]:
    """
    添加管理员。返回 (是否成功, 提示信息)。

    候选必须已存在于用户档案 —— 走的是最小权限路线，没有通讯录读取权限，
    所以只能从登录过的人里选。
    """
    if level not in VALID_LEVELS:
        return False, "管理员级别非法"
    if not user_id:
        return False, "缺少用户标识"
    with metadata._store.transaction() as meta:
        users = _bucket(meta, USERS_KEY)
        if user_id not in users:
            return False, "该员工尚未登录过本系统，请让他先用飞书登录一次"
        admins = _bucket(meta, ADMIN_LIST_KEY)
        if user_id in admins:
            return False, "该用户已在管理员名单中"
        if len(admins) >= ADMIN_LIST_MAX:
            return False, f"管理员数量已达上限 {ADMIN_LIST_MAX}"
        resolved = (name or users[user_id].get("name") or user_id)
        admins[user_id] = {
            "name": str(resolved).strip()[:NAME_MAX],
            "level": level,
            "created_at": _now_iso(),
        }
        return True, "已添加管理员"


def remove_admin(user_id: str, operator_id: str) -> Tuple[bool, str, int]:
    """
    移除管理员。返回 (是否成功, 提示信息, 建议的 HTTP 状态码)。

    三条守卫：不能移除自己、不能把超管清零、目标必须在名单里。
    状态码由本函数给出，避免路由层重复判断而与这里的规则走偏。
    """
    if not user_id:
        return False, "缺少用户标识", 400
    if user_id == operator_id:
        return False, "不能移除自己", 400
    with metadata._store.transaction() as meta:
        admins = _bucket(meta, ADMIN_LIST_KEY)
        record = admins.get(user_id)
        if not isinstance(record, dict):
            return False, "该用户不在管理员名单中", 404
        if record.get("level") == LEVEL_SUPER:
            supers = sum(1 for r in admins.values()
                         if isinstance(r, dict) and r.get("level") == LEVEL_SUPER)
            if supers <= 1:
                return False, "必须保留至少一名超级管理员", 400
        del admins[user_id]
        return True, "已移除管理员", 200
