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
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

# Add server directory to path for imports
_server_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(_server_dir))

from config import METADATA_FILE

ADMIN_KEY = "_system_admins_"


def load_metadata() -> Dict[str, Any]:
    """Load metadata from JSON file."""
    if not METADATA_FILE.exists():
        return {}
    try:
        return json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {}


def save_metadata(data: Dict[str, Any]) -> None:
    """Save metadata to JSON file."""
    METADATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_file_meta(key: str) -> Optional[Dict[str, Any]]:
    """Get metadata for a specific file key."""
    meta = load_metadata()
    return meta.get(key)


def update_file_meta(key: str, title: str = None, description: str = None, product_line: str = None, password: str = None) -> None:
    """Update title, description, product_line, and/or password for a file."""
    meta = load_metadata()
    if key not in meta:
        meta[key] = {}
    if title is not None:
        meta[key]["title"] = title
    if description is not None:
        meta[key]["description"] = description
    if product_line is not None:
        meta[key]["product_line"] = product_line
    if password is not None:
        meta[key]["password"] = password
    save_metadata(meta)


# ── Version Management ────────────────────────────────────────────────────────

def init_versions(key: str, uploader_ip: str) -> str:
    """
    Initialize the versions dict for a file when first uploaded.
    Returns the first version string 'V1'.
    """
    meta = load_metadata()
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
        save_metadata(meta)
    return meta[key]["current_version"]


def add_version(key: str, uploader_ip: str) -> str:
    """
    Add a new version entry for an existing file.
    Returns the new version string (e.g. 'V4').
    """
    meta = load_metadata()
    if key not in meta:
        return ""
    if "versions" not in meta[key]:
        meta[key]["versions"] = {}
    if "current_version" not in meta[key]:
        meta[key]["current_version"] = "V1"
        meta[key]["versions"]["V1"] = {
            "upload_time": datetime.now().isoformat(),
            "uploader_ip": uploader_ip,
        }
        save_metadata(meta)
        return "V1"

    # Increment version number
    current = meta[key]["current_version"]
    # Parse version number from "V3" -> 3
    try:
        current_num = int(current[1:])
    except:
        current_num = 1

    new_version = f"V{current_num + 1}"
    meta[key]["current_version"] = new_version
    meta[key]["versions"][new_version] = {
        "upload_time": datetime.now().isoformat(),
        "uploader_ip": uploader_ip,
    }
    save_metadata(meta)
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
        versions = {"V1": {"upload_time": file_meta.get("upload_time", datetime.now().isoformat()), "uploader_ip": file_meta.get("uploader_ip", "")}}
        current = file_meta.get("current_version", "V1")
        file_meta["versions"] = versions
        file_meta["current_version"] = current or "V1"
        save_metadata(meta)
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
    meta = load_metadata()
    if key not in meta:
        return False, "文件不存在"
    versions = meta[key].get("versions", {})
    if version not in versions:
        return False, f"版本 {version} 不存在"
    meta[key]["current_version"] = version
    save_metadata(meta)
    return True, f"已恢复为 {version}"


def delete_version(key: str, version: str) -> Tuple[bool, str]:
    """
    Delete a historical version (cannot delete current version).
    Returns (success, message).
    """
    meta = load_metadata()
    if key not in meta:
        return False, "文件不存在"
    versions = meta[key].get("versions", {})
    current = meta[key].get("current_version", "V1")
    if version == current:
        return False, "不能删除当前版本"
    if version not in versions:
        return False, f"版本 {version} 不存在"
    del versions[version]
    save_metadata(meta)
    return True, f"已删除 {version}"


def set_file_meta(
    key: str,
    title: str,
    uploader_ip: str,
    description: str = "",
    original_name: str = "",
    parent_key: str = None,
    product_line: str = "",
    password: str = None
) -> None:
    """Set complete metadata for a file (used on upload)."""
    meta = load_metadata()
    meta[key] = {
        "title": title,
        "description": description,
        "uploader_ip": uploader_ip,
        "upload_time": datetime.now().isoformat(),
        "original_name": original_name,
    }
    if parent_key:
        meta[key]["parent_key"] = parent_key
    if product_line:
        meta[key]["product_line"] = product_line
    if password is not None:
        meta[key]["password"] = password
    # Initialize version tracking
    meta[key]["current_version"] = "V1"
    meta[key]["versions"] = {
        "V1": {
            "upload_time": datetime.now().isoformat(),
            "uploader_ip": uploader_ip,
        }
    }
    save_metadata(meta)


def remove_file_meta(key: str) -> bool:
    """Remove metadata for a file. Returns True if existed."""
    meta = load_metadata()
    if key in meta:
        del meta[key]
        save_metadata(meta)
        return True
    return False


def file_exists(key: str) -> bool:
    """Check if a file key exists in metadata."""
    return key in load_metadata()


def check_file_password(key: str, password: str) -> bool:
    """Check if the provided password matches the file's password."""
    meta = load_metadata()
    if key not in meta:
        return False
    file_password = meta[key].get("password")
    if not file_password:
        return True  # No password set, allow access
    return file_password == password


def has_password(key: str) -> bool:
    """Check if a file has a password set."""
    meta = load_metadata()
    if key not in meta:
        return False
    return bool(meta[key].get("password"))


# ── Admin Management ──────────────────────────────────────────────────────────

def get_admins() -> List[Dict[str, str]]:
    """Get list of admin users (without passwords)."""
    meta = load_metadata()
    admins = meta.get(ADMIN_KEY, {}).get("users", [])
    # Return without password hashes
    return [{"username": a["username"], "created_at": a.get("created_at", "")} for a in admins]


def add_admin(username: str, password_hash: str) -> bool:
    """Add a new admin user. Returns True if added, False if already exists."""
    meta = load_metadata()
    if ADMIN_KEY not in meta:
        meta[ADMIN_KEY] = {"users": []}

    # Check if username already exists
    for user in meta[ADMIN_KEY]["users"]:
        if user["username"] == username:
            return False

    meta[ADMIN_KEY]["users"].append({
        "username": username,
        "password_hash": password_hash,
        "created_at": datetime.now().isoformat(),
    })
    save_metadata(meta)
    return True


def remove_admin(username: str) -> bool:
    """Remove an admin user. Returns True if removed, False if not found."""
    meta = load_metadata()
    if ADMIN_KEY not in meta:
        return False

    original_len = len(meta[ADMIN_KEY]["users"])
    meta[ADMIN_KEY]["users"] = [
        u for u in meta[ADMIN_KEY]["users"] if u["username"] != username
    ]

    if len(meta[ADMIN_KEY]["users"]) < original_len:
        save_metadata(meta)
        return True
    return False


def verify_admin_password(username: str, password: str) -> bool:
    """Verify admin username and password. Returns True if valid."""
    import hashlib
    meta = load_metadata()
    if ADMIN_KEY not in meta:
        return False

    pwd_hash = hashlib.sha256(password.encode()).hexdigest()

    for user in meta[ADMIN_KEY]["users"]:
        if user["username"] == username and user.get("password_hash") == pwd_hash:
            return True
    return False


def update_admin_password(username: str, new_password_hash: str) -> bool:
    """Update admin password. Returns True if updated."""
    meta = load_metadata()
    if ADMIN_KEY not in meta:
        return False

    for user in meta[ADMIN_KEY]["users"]:
        if user["username"] == username:
            user["password_hash"] = new_password_hash
            save_metadata(meta)
            return True
    return False


def is_super_admin(username: str) -> bool:
    """Check if user is the first (super) admin."""
    meta = load_metadata()
    if ADMIN_KEY not in meta or not meta[ADMIN_KEY].get("users"):
        return False
    return meta[ADMIN_KEY]["users"][0]["username"] == username
