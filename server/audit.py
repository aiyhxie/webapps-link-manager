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


def query(q: str = "", actor: str = "", category: str = "",
          limit: int = 1000) -> List[Dict[str, Any]]:
    """Return matching entries, newest first, capped at `limit`.

    - q: case-insensitive substring match across action/target/detail/actor/ip
    - actor: case-insensitive substring match against actor OR ip
    - category: exact match against one of VALID_CATEGORIES
    """
    entries = _load_all()
    q = (q or "").strip().lower()
    actor = (actor or "").strip().lower()
    category = (category or "").strip()

    def matches(e: Dict[str, Any]) -> bool:
        if category and e.get("category") != category:
            return False
        if actor:
            hay = f"{e.get('actor','')} {e.get('ip','')}".lower()
            if actor not in hay:
                return False
        if q:
            hay = " ".join(str(e.get(k, "")) for k in
                           ("action", "target", "detail", "actor", "ip", "category")).lower()
            if q not in hay:
                return False
        return True

    filtered = [e for e in entries if matches(e)]
    filtered.reverse()  # newest first
    return filtered[:limit]
