/**
 * API 封装模块
 *
 * 功能说明：
 * - 封装所有与后端的 HTTP 通信
 * - 自动携带管理员 Token（X-Admin-Token header）
 * - localStorage 管理 Token 持久化
 *
 * API 分类：
 * - 文件操作：getFiles, uploadFile, updateFile, deleteFile, checkPassword
 * - 管理员操作：getAdminStatus, adminLogin, adminLogout, getAdminUsers, addAdminUser, deleteAdminUser, changeAdminPassword, adminSetup
 * - 系统状态：getStatus
 */

import type { FileInfo, ApiResponse, VersionsResponse, ChangelogEntry, LogEntry } from './types';

// API 基础路径
const API_BASE = '/api';

export const getAdminToken = (): string | null => localStorage.getItem('adminToken');
export const setAdminToken = (token: string) => localStorage.setItem('adminToken', token);
export const clearAdminToken = () => localStorage.removeItem('adminToken');

/**
 * Admin session header for mutating requests.
 *
 * Every write endpoint must carry this: the backend decides "管理员对所有项目
 * 有全部操作权限" from the X-Admin-Token header. `/api/files` sends it, so
 * `canDelete` comes back true for admins and the UI enables every button —
 * if the follow-up write request omits the token the backend can't see the
 * admin session and rejects it with 403, and the audit log attributes the
 * action to a bare IP instead of the admin's name.
 */
const authHeaders = (): Record<string, string> => {
  const token = getAdminToken();
  return token ? { 'X-Admin-Token': token } : {};
};

/** Upload progress callback: percent is 0-100 of bytes sent. */
export type UploadProgressHandler = (percent: number) => void;

/**
 * POST a file via XMLHttpRequest so upload progress can be reported.
 * `fetch` gives no upload progress events, which left large ZIP uploads with
 * no feedback at all — hence the XHR here.
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
    Object.entries(authHeaders()).forEach(([k, v]) => xhr.setRequestHeader(k, v));

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && e.total > 0) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
      // Bytes are all sent — the server is now unzipping/writing to disk.
      xhr.upload.onload = () => onProgress(100);
    }

    xhr.onload = () => {
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
  async getFiles(): Promise<ApiResponse<FileInfo[]>> {
    const token = getAdminToken();
    const res = await fetch(`${API_BASE}/files`, {
      headers: token ? { 'X-Admin-Token': token } : {},
    });
    return res.json();
  },

  uploadFile(file: File, onProgress?: UploadProgressHandler): Promise<ApiResponse<{ key?: string; keys?: string[] }>> {
    return postFileWithProgress(`${API_BASE}/files/upload`, file, onProgress);
  },

  async updateFile(key: string, data: { title?: string; description?: string; productLine?: string; password?: string }): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE}/files/${encodeURIComponent(key)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  async deleteFile(key: string): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE}/files/${encodeURIComponent(key)}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    return res.json();
  },

  async checkFileSession(key: string): Promise<ApiResponse & { hasAccess?: boolean; hasPassword?: boolean }> {
    const res = await fetch(`${API_BASE}/files/${encodeURIComponent(key)}/session`);
    return res.json();
  },

  async checkPassword(key: string, password: string): Promise<ApiResponse<{ token?: string }>> {
    const res = await fetch(`${API_BASE}/files/${encodeURIComponent(key)}/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    return res.json();
  },

  // Version management APIs
  async getVersions(key: string): Promise<ApiResponse & { data?: VersionsResponse }> {
    const res = await fetch(`${API_BASE}/files/${encodeURIComponent(key)}/versions`);
    return res.json();
  },

  uploadNewVersion(key: string, file: File, onProgress?: UploadProgressHandler): Promise<ApiResponse & { version?: string }> {
    return postFileWithProgress(`${API_BASE}/files/${encodeURIComponent(key)}/versions`, file, onProgress);
  },

  async restoreVersion(key: string, version: string): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE}/files/${encodeURIComponent(key)}/versions/${version}/restore`, {
      method: 'PUT',
      headers: authHeaders(),
    });
    return res.json();
  },

  async deleteVersion(key: string, version: string): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE}/files/${encodeURIComponent(key)}/versions/${version}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    return res.json();
  },

  async getStatus(): Promise<ApiResponse & { version?: string }> {
    const res = await fetch(`${API_BASE}/status`);
    return res.json();
  },

  async getChangelog(): Promise<ApiResponse & { data?: ChangelogEntry[]; current_version?: string }> {
    const res = await fetch(`${API_BASE}/changelog`);
    return res.json();
  },

  // Admin APIs
  async getAdminStatus(): Promise<ApiResponse & { isLoggedIn?: boolean; username?: string; isSuperAdmin?: boolean; hasAdmins?: boolean }> {
    const token = getAdminToken();
    const res = await fetch(`${API_BASE}/admin/status`, {
      headers: token ? { 'X-Admin-Token': token } : {},
    });
    return res.json();
  },

  async adminSetup(username: string, password: string): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE}/admin/setup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    return res.json();
  },

  async adminLogin(username: string, password: string): Promise<ApiResponse & { token?: string; username?: string; isSuperAdmin?: boolean }> {
    const res = await fetch(`${API_BASE}/admin/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    return res.json();
  },

  async adminLogout(): Promise<ApiResponse> {
    const token = getAdminToken();
    const res = await fetch(`${API_BASE}/admin/logout`, {
      method: 'POST',
      headers: token ? { 'X-Admin-Token': token } : {},
    });
    return res.json();
  },

  async getAdminUsers(): Promise<ApiResponse & { data?: { username: string; created_at: string }[] }> {
    const token = getAdminToken();
    const res = await fetch(`${API_BASE}/admin/users`, {
      headers: token ? { 'X-Admin-Token': token } : {},
    });
    return res.json();
  },

  async addAdminUser(username: string, password: string): Promise<ApiResponse> {
    const token = getAdminToken();
    const res = await fetch(`${API_BASE}/admin/users`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Token': token || '',
      },
      body: JSON.stringify({ username, password }),
    });
    return res.json();
  },

  async deleteAdminUser(username: string): Promise<ApiResponse> {
    const token = getAdminToken();
    const res = await fetch(`${API_BASE}/admin/users/${encodeURIComponent(username)}`, {
      method: 'DELETE',
      headers: token ? { 'X-Admin-Token': token } : {},
    });
    return res.json();
  },

  async changeAdminPassword(oldPassword: string, newPassword: string): Promise<ApiResponse> {
    const token = getAdminToken();
    const res = await fetch(`${API_BASE}/admin/password`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Token': token || '',
      },
      body: JSON.stringify({ oldPassword, newPassword }),
    });
    return res.json();
  },

  async getLogs(params: { q?: string; actor?: string; ip?: string; category?: string; actionType?: string; page?: number; pageSize?: number }): Promise<ApiResponse & { logs?: LogEntry[]; total?: number; page?: number; pageSize?: number }> {
    const token = getAdminToken();
    const qs = new URLSearchParams();
    if (params.q) qs.set('q', params.q);
    if (params.actor) qs.set('actor', params.actor);
    if (params.ip) qs.set('ip', params.ip);
    if (params.category) qs.set('category', params.category);
    if (params.actionType) qs.set('action_type', params.actionType);
    qs.set('page', String(params.page || 1));
    qs.set('pageSize', String(params.pageSize || 100));
    const res = await fetch(`${API_BASE}/logs?${qs.toString()}`, {
      headers: token ? { 'X-Admin-Token': token } : {},
    });
    return res.json();
  },
};
