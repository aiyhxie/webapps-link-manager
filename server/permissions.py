"""
权限判定。

canManage 取代原来的 can_delete：判定依据从「请求来源 IP」换成「飞书身份」，
IP 不再参与任何权限计算 —— uploader_ip 在这个模块里根本不出现，从结构上
保证它不可能被误用。

判定式（Property 2）：
    can_manage(p, a) == a.is_admin or (p.owner_id != "" and p.owner_id == a.user_id)

推论：owner_id 为空的项目对任意非管理员恒为假。这与改造前「uploader_ip 为空
则任何人可编辑」的旧语义**相反**，是有意的收紧 —— 41 个存量项目在超管指定
负责人之前，普通员工不能编辑它们。
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional

SOURCE_FEISHU = "feishu"
SOURCE_EMERGENCY = "emergency"


@dataclass(frozen=True)
class Actor:
    """当前操作者。frozen 是刻意的：请求处理过程中身份不应被改写。"""
    user_id: str
    name: str
    is_admin: bool = False
    is_super: bool = False
    source: str = SOURCE_FEISHU

    @property
    def display(self) -> str:
        return self.name or self.user_id

    def to_public(self) -> Dict[str, Any]:
        """给前端的表示，不含任何内部字段。"""
        return {
            "userId": self.user_id,
            "name": self.display,
            "isAdmin": self.is_admin,
            "isSuperAdmin": self.is_super,
            "source": self.source,
        }


def owner_of(project_meta: Optional[Dict[str, Any]]) -> str:
    """取项目负责人标识；缺失或空字符串统一视为「无负责人」。"""
    if not isinstance(project_meta, dict):
        return ""
    value = project_meta.get("owner_id")
    return value.strip() if isinstance(value, str) else ""


def can_manage(project_meta: Optional[Dict[str, Any]],
               actor: Optional[Actor]) -> bool:
    """
    是否可管理该项目（编辑信息、设密码、上传新版本、恢复版本、删版本、删项目）。

    未认证一律为假；管理员（超管与普通管理员一视同仁）恒为真；
    其余情况要求项目有负责人且负责人就是当前操作者。
    """
    if actor is None or not actor.user_id:
        return False
    if actor.is_admin:
        return True
    owner_id = owner_of(project_meta)
    if not owner_id:
        return False
    return owner_id == actor.user_id


def can_assign_owner(actor: Optional[Actor]) -> bool:
    """指定项目负责人：仅超级管理员。"""
    return bool(actor and actor.is_super)


def can_manage_admins(actor: Optional[Actor]) -> bool:
    """维护管理员名单：仅超级管理员。"""
    return bool(actor and actor.is_super)
