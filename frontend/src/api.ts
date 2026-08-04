/**
 * API 封装模块
 *
 * 认证方式（飞书 SSO 改造后）：
 * - 身份凭据只走浏览器 Cookie（HttpOnly），前端拿不到也不保存任何 token
 * - 所有请求带 credentials: 'same-origin'
 * - 不再发送 X-Admin-Token —— 之所以彻底移除，是因为把凭据放在 localStorage
 *   意味着任何上传到本平台的 HTML 原型都能用 JS 读走它并冒充管理员操作
 * - 收到 401 时统一跳转登录入口，同一页面生命周期内只跳一次
 *
 * API 分类：
 * - 身份：getMe, logout, getDirectoryUsers
 * - 项目：getFiles, uploadFile, updateFile, deleteFile, assignOwner
 * - 版本：getVersions, uploadNewVersion, restoreVersion, deleteVersion
 * - 密码：checkFileSession, checkPassword
 * - 管理员：getAdmins, addAdmin, removeAdmin
 * - 系统：getStatus, getChangelog, getLogs
 */

import type {
  FileInfo, ApiResponse, VersionsResponse, ChangelogEntry, LogEntry,
  CurrentUser, DirectoryUser, AdminEntry,
} from './types';

const API_BASE = '/api';
const LOGIN_PATH = '/auth/login';

/** 遗留的管理员 Token 键 —— 应用加载时清理掉，避免旧凭据残留在浏览器里 */
const LEGACY_TOKEN_KEYS = ['adminToken'];

export function clearLegacyCredentials(): void {
  try {
    LEGACY_TOKEN_KEYS.forEach(k => localStorage.removeItem(k));
  } catch {
    // localStorage 不可用（隐私模式等）时忽略即可
  }
}

/**
 * 401 只跳转一次。
 * 首屏往往并发发出多个请求，若每个 401 都触发跳转，会连续 replace 多次，
 * 把浏览器历史搞乱，也可能打断正在进行的跳转。
 */
let redirecting = false;

export function redirectToLogin(): void {
  if (redirecting) return;
  redirecting = true;
  clearLegacyCredentials();
  const returnTo = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.href = `${LOGIN_PATH}?return_to=${returnTo}`;
}

/** 统一请求入口：带 Cookie、401 自动跳登录、异常收敛成 ApiResponse */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { credentials: 'same-origin', ...init });
  } catch {
    return { success: false, message: '网络请求失败' } as unknown as T;
  }
  if (res.status === 401) {
    redirectToLogin();
    return { success: false, message: '未登录', needLogin: true } as unknown as T;
  }
  try {
    return await res.json() as T;
  } catch {
    return { success: false, message: `请求失败（HTTP ${res.status}）` } as unknown as T;
  }
}

const jsonInit = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

/** 上传进度回调：percent 为已发送字节的百分比 */
export type UploadProgressHandler = (percent: number) => void;

/**
 * 用 XMLHttpRequest 上传以便上报进度（fetch 没有上传进度事件）。
 * withCredentials 让 Cookie 随之发送，与 fetch 的 same-origin 行为一致。
 */
function postFileWithProgress<T>(
  url: string,
  file: File,
  onProgress?: UploadProgressHandler,
): Promise<T> {
  return new Promise((resolve) => {
    const formData = new FormData();
    formData.append('file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.withCredentials = true;

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && e.total > 0) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
      // 字节已全部发出，服务端开始解压/写盘
      xhr.upload.onload = () => onProgress(100);
    }

    xhr.onload = () => {
      if (xhr.status === 401) {
        redirectToLogin();
        resolve({ success: false, message: '未登录' } as unknown as T);
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText) as T);
      } catch {
        const message = xhr.status === 413
          ? '文件过大，超出上传上限'
          : `上传失败（HTTP ${xhr.status}）`;
        resolve({ success: false, message } as unknown as T);
      }
    };
    xhr.onerror = () => resolve({ success: false, message: '网络错误，上传失败' } as unknown as T);
    xhr.onabort = () => resolve({ success: false, message: '上传已取消' } as unknown as T);

    xhr.send(formData);
  });
}

export const api = {
  // ── 身份 ──────────────────────────────────────────────────────────────────
  getMe(): Promise<ApiResponse<CurrentUser>> {
    return request(`${API_BASE}/me`);
  },

  logout(): Promise<ApiResponse> {
    return request('/auth/logout', jsonInit('POST'));
  },

  getDirectoryUsers(): Promise<ApiResponse<DirectoryUser[]>> {
    return request(`${API_BASE}/users`);
  },

  // ── 项目 ──────────────────────────────────────────────────────────────────
  getFiles(): Promise<ApiResponse<FileInfo[]>> {
    return request(`${API_BASE}/files`);
  },

  uploadFile(file: File, onProgress?: UploadProgressHandler): Promise<ApiResponse<{ key?: string; keys?: string[] }>> {
    return postFileWithProgress(`${API_BASE}/files/upload`, file, onProgress);
  },

  updateFile(key: string, data: { title?: string; description?: string; productLine?: string; password?: string }): Promise<ApiResponse> {
    return request(`${API_BASE}/files/${encodeURIComponent(key)}`, jsonInit('PUT', data));
  },

  deleteFile(key: string): Promise<ApiResponse> {
    return request(`${API_BASE}/files/${encodeURIComponent(key)}`, { method: 'DELETE' });
  },

  /** 批量指定负责人（超管）。全有或全无：任一项目不存在则整批不改动 */
  assignOwner(keys: string[], ownerId: string): Promise<ApiResponse & { ownerName?: string }> {
    return request(`${API_BASE}/projects/owner`, jsonInit('POST', { keys, ownerId }));
  },

  // ── 密码 ──────────────────────────────────────────────────────────────────
  checkFileSession(key: string): Promise<ApiResponse & { hasAccess?: boolean; hasPassword?: boolean }> {
    return request(`${API_BASE}/files/${encodeURIComponent(key)}/session`);
  },

  checkPassword(key: string, password: string): Promise<ApiResponse> {
    return request(`${API_BASE}/files/${encodeURIComponent(key)}/password`,
      jsonInit('POST', { password }));
  },

  // ── 版本 ──────────────────────────────────────────────────────────────────
  getVersions(key: string): Promise<ApiResponse & { data?: VersionsResponse }> {
    return request(`${API_BASE}/files/${encodeURIComponent(key)}/versions`);
  },

  uploadNewVersion(key: string, file: File, onProgress?: UploadProgressHandler): Promise<ApiResponse & { version?: string }> {
    return postFileWithProgress(`${API_BASE}/files/${encodeURIComponent(key)}/versions`, file, onProgress);
  },

  restoreVersion(key: string, version: string): Promise<ApiResponse> {
    return request(`${API_BASE}/files/${encodeURIComponent(key)}/versions/${version}/restore`,
      { method: 'PUT' });
  },

  deleteVersion(key: string, version: string): Promise<ApiResponse> {
    return request(`${API_BASE}/files/${encodeURIComponent(key)}/versions/${version}`,
      { method: 'DELETE' });
  },

  // ── 管理员名单 ────────────────────────────────────────────────────────────
  getAdmins(): Promise<ApiResponse<AdminEntry[]>> {
    return request(`${API_BASE}/admins`);
  },

  addAdmin(userId: string): Promise<ApiResponse> {
    return request(`${API_BASE}/admins`, jsonInit('POST', { userId }));
  },

  removeAdmin(userId: string): Promise<ApiResponse> {
    return request(`${API_BASE}/admins/${encodeURIComponent(userId)}`,
      { method: 'DELETE' });
  },

  // ── 系统 ──────────────────────────────────────────────────────────────────
  getStatus(): Promise<ApiResponse & { version?: string; authMode?: string }> {
    return request(`${API_BASE}/status`);
  },

  getChangelog(): Promise<ApiResponse & { data?: ChangelogEntry[]; current_version?: string }> {
    return request(`${API_BASE}/changelog`);
  },

  getLogs(params: {
    q?: string; actor?: string; actorId?: string; ip?: string;
    category?: string; actionType?: string; page?: number; pageSize?: number;
  }): Promise<ApiResponse & { logs?: LogEntry[]; total?: number; page?: number; pageSize?: number }> {
    const qs = new URLSearchParams();
    if (params.q) qs.set('q', params.q);
    if (params.actor) qs.set('actor', params.actor);
    if (params.actorId) qs.set('actor_id', params.actorId);
    if (params.ip) qs.set('ip', params.ip);
    if (params.category) qs.set('category', params.category);
    if (params.actionType) qs.set('action_type', params.actionType);
    qs.set('page', String(params.page || 1));
    qs.set('pageSize', String(params.pageSize || 100));
    return request(`${API_BASE}/logs?${qs.toString()}`);
  },
};
