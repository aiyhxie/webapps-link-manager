"""
Metadata management for WebApps Link Manager.

功能说明：
- load_metadata() / save_metadata(): 读写 metadata.json 文件
- get_file_meta() / update_file_meta() / set_file_meta(): 文件元数据管理
- check_file_password(): 验证文件访问密码
- has_password(): 检查文件是否有密码保护

管理员管理：
- get_admins(): 获取管理员列表
- add_admin() / remove_admin(): 添加/删除管理员
- verify_admin_password(): 验证管理员密码
- update_admin_password(): 修改管理员密码
- is_super_admin(): 检查是否为超级管理员（第一个创建的管理员）

数据结构：
metadata.json 格式：
{
  "file:<key>": {
    "title": "标题",
    "description": "描述",
    "uploader_ip": "上传者IP",
    "upload_time": "ISO时间",
    "original_name": "原始文件名",
    "product_line": "产品线",
    "password": "访问密码"
  },
  "_system_admins_": {
    "users": [
      {"username": "用户名", "password_hash": "SHA256哈希", "created_at": "时间"}
    ]
  }
}
"""
import json
import sys
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
import bcrypt

# Add server directory to path for imports
_server_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(_server_dir))

from config import METADATA_FILE
from atomic_store import AtomicJSONStore

ADMIN_KEY = "_system_admins_"

# Single shared store instance: atomic writes, auto-backup, corruption
# recovery, and cross-process file locking for read-modify-write cycles.
_store = AtomicJSONStore(METADATA_FILE, empty_default={})

# bcrypt salt rounds (cost factor 12 = ~250ms per hash on modern hardware)
BCRYPT_ROUNDS = 12


def _hash_password_bcrypt(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("utf-8")


def _verify_password_bcrypt(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _is_bcrypt_hash(password_hash: str) -> bool:
    """Check if a password hash is a bcrypt hash (starts with $2)."""
    return password_hash.startswith("$2")


def _verify_password_legacy(password: str, password_hash: str) -> bool:
    """Verify a password against a legacy SHA256 hash."""
    return hashlib.sha256(password.encode()).hexdigest() == password_hash


def verify_admin_password(username: str, password: str) -> bool:
    """Verify admin username and password. Supports both bcrypt and legacy SHA256."""
    # Fast path: pure read, no lock needed.
    meta = load_metadata()
    if ADMIN_KEY not in meta:
        return False

    for user in meta[ADMIN_KEY]["users"]:
        if user["username"] != username:
            continue
        stored_hash = user.get("password_hash", "")
        if not stored_hash:
            continue

        if _is_bcrypt_hash(stored_hash):
            if _verify_password_bcrypt(password, stored_hash):
                return True
        else:
            # Legacy SHA256 hash — verify, then upgrade to bcrypt under lock.
            if _verify_password_legacy(password, stored_hash):
                new_hash = _hash_password_bcrypt(password)
                with _store.transaction() as tx_meta:
                    if ADMIN_KEY in tx_meta:
                        for tx_user in tx_meta[ADMIN_KEY]["users"]:
                            if tx_user["username"] == username:
                                tx_user["password_hash"] = new_hash
                                break
                return True
    return False


def hash_admin_password(password: str) -> str:
    """Hash an admin password using bcrypt. Use this instead of raw SHA256."""
    return _hash_password_bcrypt(password)


def load_metadata() -> Dict[str, Any]:
    """Load metadata from JSON file (atomic, self-healing on corruption)."""
    return _store.load()


def save_metadata(data: Dict[str, Any]) -> None:
    """Save metadata to JSON file (atomic write with automatic backup)."""
    _store.save(data)


def get_file_meta(key: str) -> Optional[Dict[str, Any]]:
    """Get metadata for a specific file key."""
    meta = load_metadata()
    return meta.get(key)


def update_file_meta(key: str, title: str = None, description: str = None, product_line: str = None, password: str = None) -> None:
    """Update title, description, product_line, and/or password for a file.
    Password is stored as bcrypt hash, not plain text.
    """
    with _store.transaction() as meta:
        if key not in meta:
            meta[key] = {}
        if title is not None:
            meta[key]["title"] = title
        if description is not None:
            meta[key]["description"] = description
        if product_line is not None:
            meta[key]["product_line"] = product_line
        if password is not None:
            if password:
                meta[key]["password"] = _hash_password_bcrypt(password)
            else:
                meta[key]["password"] = None


# ── Version Management ────────────────────────────────────────────────────────

def init_versions(key: str, uploader_ip: str) -> str:
    """
    Initialize the versions dict for a file when first uploaded.
    Returns the first version string 'V1'.
    """
    with _store.transaction() as meta:
        if key not in meta:
            meta[key] = {}
        if "versions" not in meta[key]:
            meta[key]["versions"] = {}
        if "current_version" not in meta[key]:
            meta[key]["current_version"] = "V1"
            meta[key]["versions"]["V1"] = {
                "upload_time": meta[key].get("upload_time", datetime.now().isoformat()),
                "uploader_ip": uploader_ip or meta[key].get("uploader_ip", ""),
            }
        return meta[key]["current_version"]


def add_version(key: str, uploader_ip: str,
                owner_id: str = "", owner_name: str = "") -> str:
    """
    Add a new version entry for an existing file.
    Returns the new version string (e.g. 'V4').

    版本记录同时写入操作者的飞书身份（owner_id / owner_name），但**不改动**
    项目级的 owner_id —— 上传新版本不等于项目易主（需求 5.3）。
    uploader_ip 继续写入，仅供审计展示。
    """
    with _store.transaction() as meta:
        if key not in meta:
            return ""
        if "versions" not in meta[key]:
            meta[key]["versions"] = {}
        version_record = {
            "upload_time": datetime.now().isoformat(),
            "uploader_ip": uploader_ip,
            "owner_id": owner_id or "",
            "owner_name": owner_name or "",
        }
        if "current_version" not in meta[key]:
            meta[key]["current_version"] = "V1"
            meta[key]["versions"]["V1"] = version_record
            return "V1"

        # Increment version number
        current = meta[key]["current_version"]
        try:
            current_num = int(current[1:])
        except (ValueError, IndexError):
            current_num = 1

        new_version = f"V{current_num + 1}"
        meta[key]["current_version"] = new_version
        meta[key]["versions"][new_version] = version_record
        return new_version


def get_versions(key: str) -> Dict[str, Any]:
    """Get all versions for a file, including current version info."""
    meta = load_metadata()
    if key not in meta:
        return {}
    file_meta = meta[key]
    versions = file_meta.get("versions", {})
    # Backward compatibility: if versions is empty but file exists, initialize
    if not versions and file_meta.get("upload_time"):
        with _store.transaction() as tx_meta:
            if key in tx_meta:
                tx_file_meta = tx_meta[key]
                versions = {"V1": {"upload_time": tx_file_meta.get("upload_time", datetime.now().isoformat()), "uploader_ip": tx_file_meta.get("uploader_ip", "")}}
                current = tx_file_meta.get("current_version", "V1")
                tx_file_meta["versions"] = versions
                tx_file_meta["current_version"] = current or "V1"
    return {
        "current_version": file_meta.get("current_version", "V1"),
        "versions": versions,
    }


def get_version_info(key: str, version: str) -> Optional[Dict[str, Any]]:
    """Get info for a specific version."""
    meta = load_metadata()
    if key not in meta:
        return None
    versions = meta[key].get("versions", {})
    return versions.get(version)


def restore_version(key: str, version: str) -> Tuple[bool, str]:
    """
    Restore a historical version as the current version.
    Returns (success, message).
    """
    with _store.transaction() as meta:
        if key not in meta:
            return False, "文件不存在"
        versions = meta[key].get("versions", {})
        if version not in versions:
            return False, f"版本 {version} 不存在"
        meta[key]["current_version"] = version
        return True, f"已恢复为 {version}"


def delete_version(key: str, version: str) -> Tuple[bool, str]:
    """
    Delete a historical version (cannot delete current version).
    Returns (success, message).
    """
    with _store.transaction() as meta:
        if key not in meta:
            return False, "文件不存在"
        versions = meta[key].get("versions", {})
        current = meta[key].get("current_version", "V1")
        if version == current:
            return False, "不能删除当前版本"
        if version not in versions:
            return False, f"版本 {version} 不存在"
        del versions[version]
        return True, f"已删除 {version}"


def set_file_meta(
    key: str,
    title: str,
    uploader_ip: str,
    description: str = "",
    original_name: str = "",
    parent_key: str = None,
    product_line: str = "",
    password: str = None,
    owner_id: str = "",
    owner_name: str = ""
) -> None:
    """
    Set complete metadata for a file (used on upload).

    owner_id / owner_name 是所有权的真相来源（飞书 UserID + 姓名快照）；
    uploader_ip 保留但降级为纯审计信息，不参与任何权限判定。
    """
    now = datetime.now().isoformat()
    with _store.transaction() as meta:
        meta[key] = {
            "title": title,
            "description": description,
            "owner_id": (owner_id or "")[:64],
            "owner_name": (owner_name or "")[:64],
            "uploader_ip": uploader_ip,
            "upload_time": now,
            "original_name": original_name,
        }
        if parent_key:
            meta[key]["parent_key"] = parent_key
        if product_line:
            meta[key]["product_line"] = product_line
        if password is not None:
            meta[key]["password"] = _hash_password_bcrypt(password) if password else None
        # init_upload_time is set only on first upload, never changed
        if "init_upload_time" not in meta[key]:
            meta[key]["init_upload_time"] = now
        # Initialize version tracking
        meta[key]["current_version"] = "V1"
        meta[key]["versions"] = {
            "V1": {
                "upload_time": now,
                "uploader_ip": uploader_ip,
                "owner_id": (owner_id or "")[:64],
                "owner_name": (owner_name or "")[:64],
            }
        }


def set_owner(key: str, owner_id: str, owner_name: str) -> bool:
    """
    指定项目负责人。返回 (旧负责人标识, 是否成功) 中的成功位；
    调用方若需要旧值请用 get_file_meta 先读。
    """
    with _store.transaction() as meta:
        if key not in meta:
            return False
        meta[key]["owner_id"] = (owner_id or "")[:64]
        meta[key]["owner_name"] = (owner_name or "")[:64]
        return True


def set_owners_bulk(keys, owner_id: str, owner_name: str):
    """
    批量指定负责人，全有或全无：任一 key 不存在则整批不改动。

    返回 (是否成功, 缺失的 key 列表, {key: 旧负责人标识})。
    在单个事务里完成，避免部分成功留下一半改过一半没改的状态。
    """
    missing = []
    previous = {}
    with _store.transaction() as meta:
        for key in keys:
            if key not in meta:
                missing.append(key)
        if missing:
            return False, missing, {}
        for key in keys:
            previous[key] = meta[key].get("owner_id", "") or ""
            meta[key]["owner_id"] = (owner_id or "")[:64]
            meta[key]["owner_name"] = (owner_name or "")[:64]
    return True, [], previous


def touch_file_meta(key: str, **fields) -> bool:
    """
    Atomically update arbitrary fields on an existing file's metadata entry
    under a single locked transaction (avoids the load/mutate/save races
    that direct load_metadata()/save_metadata() call pairs used to have).
    Returns True if the key existed and was updated, False otherwise.
    """
    with _store.transaction() as meta:
        if key not in meta:
            return False
        meta[key].update(fields)
        return True


def remove_file_meta(key: str) -> bool:
    """Remove metadata for a file. Returns True if existed."""
    with _store.transaction() as meta:
        if key in meta:
            del meta[key]
            return True
        return False


def file_exists(key: str) -> bool:
    """Check if a file key exists in metadata."""
    return key in load_metadata()


def check_file_password(key: str, password: str) -> bool:
    """Check if the provided password matches the file's stored bcrypt hash."""
    meta = load_metadata()
    if key not in meta:
        return False
    stored_hash = meta[key].get("password")
    if not stored_hash:
        return True  # No password set, allow access
    # Backward compatibility: if stored value is not a bcrypt hash, treat as legacy plain-text
    if not _is_bcrypt_hash(stored_hash):
        # Legacy plain-text password — upgrade to bcrypt on successful match
        if stored_hash == password:
            new_hash = _hash_password_bcrypt(password)
            with _store.transaction() as tx_meta:
                if key in tx_meta:
                    tx_meta[key]["password"] = new_hash
            return True
        return False
    return _verify_password_bcrypt(password, stored_hash)


def has_password(key: str) -> bool:
    """Check if a file has a password set."""
    meta = load_metadata()
    if key not in meta:
        return False
    return bool(meta[key].get("password"))


def set_file_password(key: str, password: str) -> None:
    """Set or update a file's password (stores bcrypt hash, not plain text)."""
    with _store.transaction() as meta:
        if key not in meta:
            meta[key] = {}
        if password:
            meta[key]["password"] = _hash_password_bcrypt(password)
        else:
            meta[key]["password"] = None


def migrate_file_passwords() -> Dict[str, Any]:
    """
    Migrate all plain-text file passwords to bcrypt.
    Returns a report of migrations performed.
    """
    with _store.transaction() as meta:
        migrated = []
        for key, data in meta.items():
            if key.startswith(ADMIN_KEY):
                continue
            pw = data.get("password")
            if pw and not _is_bcrypt_hash(pw):
                data["password"] = _hash_password_bcrypt(pw)
                migrated.append(key)
        return {"migrated": migrated, "count": len(migrated)}


# ── Admin Management ──────────────────────────────────────────────────────────

def get_admins() -> List[Dict[str, str]]:
    """Get list of admin users (without passwords)."""
    meta = load_metadata()
    admins = meta.get(ADMIN_KEY, {}).get("users", [])
    # Return without password hashes
    return [{"username": a["username"], "created_at": a.get("created_at", "")} for a in admins]


def add_admin(username: str, password_hash: str, force_password_change: bool = False) -> bool:
    """Add a new admin user. Returns True if added, False if already exists.
    password_hash should already be bcrypt-hashed via hash_admin_password().
    If force_password_change is True, the admin must change their password on next login.
    """
    with _store.transaction() as meta:
        if ADMIN_KEY not in meta:
            meta[ADMIN_KEY] = {"users": []}

        for user in meta[ADMIN_KEY]["users"]:
            if user["username"] == username:
                return False

        meta[ADMIN_KEY]["users"].append({
            "username": username,
            "password_hash": password_hash,
            "created_at": datetime.now().isoformat(),
            "force_password_change": force_password_change,
        })
        return True


def remove_admin(username: str) -> bool:
    """Remove an admin user. Returns True if removed, False if not found."""
    with _store.transaction() as meta:
        if ADMIN_KEY not in meta:
            return False

        original_len = len(meta[ADMIN_KEY]["users"])
        meta[ADMIN_KEY]["users"] = [
            u for u in meta[ADMIN_KEY]["users"] if u["username"] != username
        ]
        return len(meta[ADMIN_KEY]["users"]) < original_len


def update_admin_password(username: str, new_password_hash: str) -> bool:
    """Update admin password. Returns True if updated. new_password_hash should be bcrypt-hashed."""
    with _store.transaction() as meta:
        if ADMIN_KEY not in meta:
            return False

        for user in meta[ADMIN_KEY]["users"]:
            if user["username"] == username:
                user["password_hash"] = new_password_hash
                return True
        return False


def is_super_admin(username: str) -> bool:
    """Check if user is the first (super) admin."""
    meta = load_metadata()
    if ADMIN_KEY not in meta or not meta[ADMIN_KEY].get("users"):
        return False
    return meta[ADMIN_KEY]["users"][0]["username"] == username


def must_change_password(username: str) -> bool:
    """Check if an admin must change their password on next login."""
    meta = load_metadata()
    if ADMIN_KEY not in meta:
        return False
    for user in meta[ADMIN_KEY]["users"]:
        if user["username"] == username:
            return bool(user.get("force_password_change", False))
    return False


def clear_force_password_change(username: str) -> bool:
    """Clear the force_password_change flag for an admin."""
    with _store.transaction() as meta:
        if ADMIN_KEY not in meta:
            return False
        for user in meta[ADMIN_KEY]["users"]:
            if user["username"] == username:
                user["force_password_change"] = False
                return True
        return False
