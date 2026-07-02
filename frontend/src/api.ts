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

import type { FileInfo, ApiResponse } from './types';

// API 基础路径
const API_BASE = '/api';

export const getAdminToken = (): string | null => localStorage.getItem('adminToken');
export const setAdminToken = (token: string) => localStorage.setItem('adminToken', token);
export const clearAdminToken = () => localStorage.removeItem('adminToken');

export const api = {
  async getFiles(): Promise<ApiResponse<FileInfo[]>> {
    const token = getAdminToken();
    const res = await fetch(`${API_BASE}/files`, {
      headers: token ? { 'X-Admin-Token': token } : {},
    });
    return res.json();
  },

  async uploadFile(file: File): Promise<ApiResponse<{ key?: string; keys?: string[] }>> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/files/upload`, {
      method: 'POST',
      body: formData,
    });
    return res.json();
  },

  async updateFile(key: string, data: { title?: string; description?: string; productLine?: string; password?: string }): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE}/files/${encodeURIComponent(key)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  async deleteFile(key: string): Promise<ApiResponse> {
    const res = await fetch(`${API_BASE}/files/${encodeURIComponent(key)}`, {
      method: 'DELETE',
    });
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

  async getStatus(): Promise<ApiResponse & { version?: string }> {
    const res = await fetch(`${API_BASE}/status`);
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
};
