"""
Changelog management for WebApps Link Manager.

功能说明：
- 维护 changelog.json，作为系统版本号的唯一真相源
- add_entry(summary): 自动将版本号 patch 位 +1，追加一条更新记录并同步 PRD
- 支持 PRD.md 版本历史同步
- 版本号无需手动维护，config.VERSION 从本文件自动读取最新版本

数据结构：
changelog.json 格式：
{
  "last_recorded_version": "1.0.4",
  "entries": [
    {
      "version": "1.0.5",
      "date": "2026-07-03T10:00:00",
      "changelog": "1. Admin 密码迁移到 bcrypt；2. 文件密码使用 bcrypt 存储；3. 强制首次管理员修改默认密码",
      "type": "security"
    }
  ]
}
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add server directory to path for imports
_server_dir = Path(__file__).parent.resolve()
import sys
sys.path.insert(0, str(_server_dir))

from config import BASE_DIR, CHANGELOG_FILE, DEFAULT_VERSION
from atomic_store import AtomicJSONStore

_EMPTY_CHANGELOG = {"last_recorded_version": "", "entries": []}
_store = AtomicJSONStore(CHANGELOG_FILE, empty_default=_EMPTY_CHANGELOG)

# Change type classification based on keywords in changelog notes
CHANGE_TYPE_KEYWORDS = {
    "security": ["密码", "安全", "bcrypt", "token", "认证", "权限", "csrf", "xss"],
    "feature": ["新增", "新功能", "支持", "增加", "特性"],
    "fix": ["修复", "bug", "问题", "错误", "fix"],
}


def _classify_change(changelog: str) -> str:
    """Classify change type based on keywords in changelog notes."""
    text = changelog.lower()
    for change_type, keywords in CHANGE_TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return change_type
    return "other"


def load_changelog() -> Dict[str, Any]:
    """Load changelog from JSON file (atomic, self-healing on corruption)."""
    return _store.load()


def save_changelog(data: Dict[str, Any]) -> None:
    """Save changelog to JSON file (atomic write with automatic backup)."""
    _store.save(data)


def get_changelog_entries() -> List[Dict[str, Any]]:
    """Get all changelog entries, newest first."""
    data = load_changelog()
    entries = data.get("entries", [])
    # Sort by version descending
    def version_key(e):
        # Parse "1.0.5" -> (1, 0, 5) for proper sorting
        parts = re.findall(r'\d+', e.get("version", ""))
        return tuple(int(p) for p in parts) if parts else (0,)
    return sorted(entries, key=version_key, reverse=True)


def get_latest_version() -> str:
    """Return the latest recorded version, or DEFAULT_VERSION if none."""
    data = load_changelog()
    recorded = data.get("last_recorded_version", "")
    if recorded:
        return recorded
    entries = data.get("entries", [])
    if entries:
        return entries[0].get("version", DEFAULT_VERSION)
    return DEFAULT_VERSION


def _bump_patch(version: str) -> str:
    """
    Increment the patch (last) component of a dotted version string.
    e.g. "1.0.6" -> "1.0.7". Falls back gracefully on malformed input.
    """
    parts = re.findall(r'\d+', version)
    if not parts:
        return DEFAULT_VERSION
    nums = [int(p) for p in parts]
    # Ensure at least major.minor.patch
    while len(nums) < 3:
        nums.append(0)
    nums[-1] += 1
    return ".".join(str(n) for n in nums)


def record_version(version: str, changelog_notes: str, change_type: str = None) -> bool:
    """
    Record a specific version in changelog.json.
    Returns True if a new entry was added, False if version already recorded.
    """
    with _store.transaction() as data:
        data.setdefault("entries", [])
        if data.get("last_recorded_version") == version:
            return False

        entry = {
            "version": version,
            "date": datetime.now().isoformat(),
            "changelog": changelog_notes,
            "type": change_type or _classify_change(changelog_notes),
        }

        data["entries"].insert(0, entry)  # Prepend (newest first)
        data["last_recorded_version"] = version
        return True


def add_entry(summary: str, change_type: str = None) -> Optional[str]:
    """
    Append a new changelog entry with an auto-incremented version number.

    This is the primary entry point to call whenever a change request is
    completed: it computes the next version (patch +1 from the latest
    recorded version), records the summary, syncs PRD.md, and returns the
    new version string.

    The version bump + record happens inside a single locked transaction so
    two concurrent calls can't compute the same "next version" and collide.

    Returns the new version string, or None if summary is empty.
    """
    summary = (summary or "").strip()
    if not summary:
        return None

    entry_type = change_type or _classify_change(summary)
    with _store.transaction() as data:
        data.setdefault("entries", [])
        current = data.get("last_recorded_version") or (
            data["entries"][0]["version"] if data["entries"] else DEFAULT_VERSION
        )
        new_version = _bump_patch(current)

        entry = {
            "version": new_version,
            "date": datetime.now().isoformat(),
            "changelog": summary,
            "type": entry_type,
        }
        data["entries"].insert(0, entry)
        data["last_recorded_version"] = new_version

    sync_prd_changelog()
    return new_version


def sync_prd_changelog() -> bool:
    """
    Sync changelog entries to PRD.md under ## 6. 版本信息 chapter.
    Returns True if PRD was updated.
    """
    prd_path = BASE_DIR / "PRD.md"
    if not prd_path.exists():
        return False

    entries = get_changelog_entries()
    if not entries:
        return False

    # Build the new section content
    lines = [
        "### 6.1 版本更新记录\n",
        "| 版本 | 日期 | 类型 | 变更说明 |",
        "|------|------|------|---------|",
    ]
    for e in entries:
        version = e.get("version", "")
        date = e.get("date", "")[:10]  # YYYY-MM-DD
        change_type = e.get("type", "other")
        changelog_text = e.get("changelog", "")
        # Escape pipes in changelog text
        changelog_text = changelog_text.replace("|", "\\|")
        lines.append(f"| {version} | {date} | {change_type} | {changelog_text} |")

    new_section = "\n".join(lines) + "\n"

    try:
        content = prd_path.read_text(encoding="utf-8")

        # Check if section already exists
        section_start_pattern = r'### 6\.1 版本更新记录'
        if re.search(section_start_pattern, content):
            # Replace existing section - find the next ## (not ###) heading
            start_match = re.search(section_start_pattern, content)
            rest = content[start_match.end():]
            # Only match top-level ## headings, not ### sub-headings
            next_section_match = re.search(r'\n## [A-Za-z一-鿿]', rest)
            if next_section_match:
                end_pos = start_match.end() + next_section_match.start()
            else:
                end_pos = len(content)
            new_content = content[:start_match.start()] + new_section + content[end_pos:]
        else:
            # Insert new section before ## 7. 附录 (or at end of doc)
            sec7_match = re.search(r'\n## 7\.', content)
            if sec7_match:
                new_content = content[:sec7_match.start()] + "\n" + new_section + content[sec7_match.start():]
            else:
                new_content = content.rstrip() + "\n\n" + new_section

        prd_path.write_text(new_content, encoding="utf-8")
        return True
    except Exception as e:
        print(f"Warning: Failed to sync PRD.md: {e}")
        return False


def main():
    """
    CLI: record a new version entry from the command line.

    Usage:
        python3 changelog.py "1. 修复xxx；2. 新增yyy" [change_type]

    change_type is optional (security|feature|fix|other); auto-classified if omitted.
    """
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("用法: python3 changelog.py \"变更摘要\" [类型]")
        print("  类型可选: security | feature | fix | other（省略则自动判断）")
        sys.exit(1)
    summary = sys.argv[1]
    change_type = sys.argv[2] if len(sys.argv) > 2 else None
    new_version = add_entry(summary, change_type)
    if new_version:
        print(f"已记录新版本 {new_version}: {summary}")
    else:
        print("未记录（摘要为空）")
        sys.exit(1)


if __name__ == "__main__":
    main()
