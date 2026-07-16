"""
Structured audit log for WebApps Link Manager.

功能说明：
- 以 JSON Lines 格式（logs/audit.jsonl，一行一条）记录三类审计事件：
    project : 项目卡片的增删改（新建/删除/编辑/密码/版本操作）
    admin   : 管理员动作（登录/退出/增删管理员/改密码）
    access  : IP 的项目级访问（只记项目入口，不记静态资源/子页面）
- 支持按关键字(q)、操作者(actor: IP 或管理员姓名)、类别(category) 查询
- 追加写入使用线程锁保护；文件过大时自动滚动，仅保留最近 MAX_ENTRIES 条

每条记录结构：
{
  "time":     "2026-07-04T15:03:52",   # 本地时间 ISO
  "category": "project|admin|access",
  "action":   "删除项目",               # 中文动作名
  "actor":    "谢勇华" | "192.168.1.10", # 管理员操作填姓名，匿名操作填 IP
  "ip":       "192.168.1.10",           # 始终记录来源 IP
  "target":   "项目标题或对象",          # 涉及的项目/管理员
  "detail":   ""                        # 补充信息（可空）
}
"""
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
AUDIT_FILE = _LOG_DIR / "audit.jsonl"

# Keep at most this many entries; trim oldest when the file grows beyond it.
MAX_ENTRIES = 5000
# Only pay the trim cost once the file exceeds this size (bytes).
_TRIM_TRIGGER_BYTES = 2 * 1024 * 1024  # ~2MB

_lock = threading.Lock()

VALID_CATEGORIES = ("project", "admin", "access")


def log(category: str, action: str, actor: str = "", ip: str = "",
        target: str = "", detail: str = "") -> None:
    """Append a structured audit entry (thread-safe)."""
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "category": category,
        "action": action,
        "actor": actor or ip or "",
        "ip": ip or "",
        "target": target or "",
        "detail": detail or "",
    }
    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        try:
            with AUDIT_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            _maybe_trim_locked()
        except OSError:
            pass  # never let logging break the request


def _maybe_trim_locked() -> None:
    """Trim the file to the most recent MAX_ENTRIES if it grew too large.
    Caller must hold _lock."""
    try:
        if not AUDIT_FILE.exists() or AUDIT_FILE.stat().st_size <= _TRIM_TRIGGER_BYTES:
            return
        lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_ENTRIES:
            keep = lines[-MAX_ENTRIES:]
            AUDIT_FILE.write_text("\n".join(keep) + "\n", encoding="utf-8")
    except OSError:
        pass


def _load_all() -> List[Dict[str, Any]]:
    """Load all entries (oldest first). Tolerates malformed lines."""
    if not AUDIT_FILE.exists():
        return []
    out = []
    try:
        for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


# Event-type classification (增/删/改/登录访问), derived from the `action`
# field for filtering purposes. Distinct from `category` (project/admin/access)
# which groups records by subject matter, not by the kind of operation.
_ACTION_TYPE_KEYWORDS = [
    ("delete", ["删除"]),
    ("create", ["新建", "创建", "添加", "上传"]),
    ("update", ["编辑", "设置密码", "清除密码", "恢复版本", "修改密码", "更新"]),
    ("access", ["登录", "退出", "查看项目"]),
]

ACTION_TYPES = ("create", "delete", "update", "access")


def classify_action_type(action: str) -> str:
    """Classify an action string into create/delete/update/access."""
    for action_type, keywords in _ACTION_TYPE_KEYWORDS:
        if any(kw in action for kw in keywords):
            return action_type
    return "other"


def query(q: str = "", actor: str = "", ip: str = "", category: str = "",
          action_type: str = "", page: int = 1, page_size: int = 100
          ) -> Dict[str, Any]:
    """Return matching entries, newest first, paginated.

    - q: case-insensitive substring match across action/target/detail/actor/ip
    - actor: case-insensitive substring match against the actor field only
    - ip: case-insensitive substring match against the ip field only
    - category: exact match against one of VALID_CATEGORIES
    - action_type: exact match against one of ACTION_TYPES (see classify_action_type)
    - page/page_size: 1-indexed pagination

    Returns {"logs": [...], "total": N, "page": P, "pageSize": S}
    """
    entries = _load_all()
    q = (q or "").strip().lower()
    actor = (actor or "").strip().lower()
    ip = (ip or "").strip().lower()
    category = (category or "").strip()
    action_type = (action_type or "").strip()

    def matches(e: Dict[str, Any]) -> bool:
        if category and e.get("category") != category:
            return False
        if action_type and classify_action_type(e.get("action", "")) != action_type:
            return False
        if actor and actor not in str(e.get("actor", "")).lower():
            return False
        if ip and ip not in str(e.get("ip", "")).lower():
            return False
        if q:
            hay = " ".join(str(e.get(k, "")) for k in
                           ("action", "target", "detail", "actor", "ip", "category")).lower()
            if q not in hay:
                return False
        return True

    filtered = [e for e in entries if matches(e)]
    filtered.reverse()  # newest first

    total = len(filtered)
    page = max(1, page)
    page_size = max(1, min(page_size, 500))
    start = (page - 1) * page_size
    page_items = filtered[start:start + page_size]

    return {"logs": page_items, "total": total, "page": page, "pageSize": page_size}
