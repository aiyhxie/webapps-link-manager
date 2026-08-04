"""
一次性迁移脚本：为 metadata.json 补齐所有权字段。

用法：
    python3 server/migrate_identity.py            # 执行迁移
    python3 server/migrate_identity.py --dry-run  # 只看会改什么，不写盘

做三件事：
1. 每个项目条目补 owner_id / owner_name（缺失则写空字符串）
2. 每条版本记录补同样两个字段
3. 建立 _system_users_ 与 _system_admin_list_ 两个空容器

三条保证：
- **幂等**：重复执行结果逐字段一致，且绝不覆盖已存在的非空 owner_id/owner_name
- **备份先行**：先留一份带时间戳的副本，再在单个事务里原子提交；
  中途失败则 metadata.json 保持原内容
- **字段保全**：除新增的两个字段外，不动任何既有字段（uploader_ip 一个不少）

存量项目的 owner_id 会是空字符串，也就是「无负责人」。这些项目在超管指定
负责人之前，普通员工不能编辑 —— 这是有意的收紧，脚本结束时会打印待指定的数量。
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

_server_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(_server_dir))

import config
import metadata
import user_directory

OWNER_FIELDS = ("owner_id", "owner_name")


def _backup_metadata() -> Path:
    """显式留一份带时间戳的副本（AtomicJSONStore 自身也会备份，这里是双保险）。"""
    src: Path = config.METADATA_FILE
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    dest = src.parent / f"metadata.pre-identity-{stamp}.json"
    if src.exists():
        shutil.copyfile(src, dest)
    return dest


def _needs_owner_fields(entry: Dict[str, Any]) -> bool:
    return any(field not in entry for field in OWNER_FIELDS)


def plan(meta: Dict[str, Any]) -> Dict[str, Any]:
    """统计将要发生的改动，不修改输入。"""
    projects = 0
    projects_to_patch = 0
    versions = 0
    versions_to_patch = 0
    ownerless = 0
    for key, entry in meta.items():
        if not key.startswith("file:") or not isinstance(entry, dict):
            continue
        projects += 1
        if _needs_owner_fields(entry):
            projects_to_patch += 1
        if not (entry.get("owner_id") or "").strip():
            ownerless += 1
        for _v, record in (entry.get("versions") or {}).items():
            if not isinstance(record, dict):
                continue
            versions += 1
            if _needs_owner_fields(record):
                versions_to_patch += 1
    return {
        "projects": projects,
        "projects_to_patch": projects_to_patch,
        "versions": versions,
        "versions_to_patch": versions_to_patch,
        "ownerless": ownerless,
        "has_users_bucket": isinstance(meta.get(user_directory.USERS_KEY), dict),
        "has_admin_bucket": isinstance(meta.get(user_directory.ADMIN_LIST_KEY), dict),
    }


def migrate(dry_run: bool = False) -> Dict[str, Any]:
    before = plan(metadata.load_metadata())
    if dry_run:
        return {"dry_run": True, "before": before, "backup": None}

    backup = _backup_metadata()
    changed = {"projects": 0, "versions": 0, "buckets": 0}

    with metadata._store.transaction() as meta:
        for key, entry in meta.items():
            if not key.startswith("file:") or not isinstance(entry, dict):
                continue
            touched = False
            for field in OWNER_FIELDS:
                if field not in entry:
                    entry[field] = ""          # 只补缺失，绝不覆盖已有非空值
                    touched = True
            if touched:
                changed["projects"] += 1
            for _v, record in (entry.get("versions") or {}).items():
                if not isinstance(record, dict):
                    continue
                vtouched = False
                for field in OWNER_FIELDS:
                    if field not in record:
                        record[field] = ""
                        vtouched = True
                if vtouched:
                    changed["versions"] += 1

        for bucket in (user_directory.USERS_KEY, user_directory.ADMIN_LIST_KEY):
            if not isinstance(meta.get(bucket), dict):
                meta[bucket] = {}
                changed["buckets"] += 1

    after = plan(metadata.load_metadata())
    return {"dry_run": False, "before": before, "after": after,
            "changed": changed, "backup": str(backup)}


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    print("=" * 60)
    print("metadata.json 所有权字段迁移" + ("（试运行，不写盘）" if dry_run else ""))
    print("=" * 60)
    print(f"目标文件：{config.METADATA_FILE}")

    result = migrate(dry_run=dry_run)
    before = result["before"]
    print(f"\n迁移前：")
    print(f"  项目条目            {before['projects']}")
    print(f"  待补字段的项目      {before['projects_to_patch']}")
    print(f"  版本记录            {before['versions']}")
    print(f"  待补字段的版本记录  {before['versions_to_patch']}")
    print(f"  用户档案容器已存在  {before['has_users_bucket']}")
    print(f"  管理员名单已存在    {before['has_admin_bucket']}")

    if dry_run:
        print("\n试运行结束，未写入任何内容。")
        return 0

    changed = result["changed"]
    after = result["after"]
    print(f"\n本次改动：")
    print(f"  补齐字段的项目      {changed['projects']}")
    print(f"  补齐字段的版本记录  {changed['versions']}")
    print(f"  新建容器            {changed['buckets']}")
    print(f"  备份文件            {result['backup']}")
    print(f"\n迁移后：")
    print(f"  项目条目            {after['projects']}")
    print(f"  仍待补字段          {after['projects_to_patch']}（应为 0）")
    print(f"  **待超管指定负责人  {after['ownerless']}**")
    if after["ownerless"]:
        print("\n提示：这些项目当前无负责人，普通员工不能编辑它们。")
        print("      请超级管理员登录后在「未指定负责人」筛选里批量指定。")
    print("=" * 60)
    return 0 if after["projects_to_patch"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
