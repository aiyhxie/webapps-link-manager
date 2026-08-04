/**
 * 类型定义模块
 *
 * 主要类型：
 * - FileInfo: 文件信息结构
 * - ApiResponse: API 统一响应格式
 * - StatusResponse: 服务器状态响应格式
 *
 * 产品线配置：
 * - PRODUCT_LINES: 产品线颜色映射（用于 UI 显示）
 * - PRODUCT_LINE_OPTIONS: 产品线选项列表
 */

// 文件信息结构
export interface FileInfo {
  key: string;           // 文件唯一标识，格式为 "file:路径" 或 "manual:URL"
  path: string;          // 文件相对路径
  title: string;         // 显示标题
  description: string;   // 文件描述
  ownerId: string;       // 负责人飞书 UserID，空字符串表示未指定负责人
  ownerName: string;     // 负责人姓名（优先取用户档案最新值，否则用快照）
  uploader_ip: string | null;  // 上传来源 IP —— 仅供审计展示，不参与权限判定
  upload_time: string | null;  // 上传时间（ISO 格式，当前版本的上传时间）
  init_upload_time: string | null;  // 初始上传时间（首次创建的时间）
  isDir: boolean;        // 是否为目录（预留）
  url: string;           // 访问 URL（gateway 形态下为预览域绝对地址）
  canManage: boolean;    // 当前用户是否可管理此项目（负责人本人或管理员）
  productLine?: string;  // 产品线分类
  hasPassword?: boolean; // 是否有密码保护
  currentVersion?: string; // 当前版本号，如 "V3"
}

// 版本信息
export interface VersionInfo {
  upload_time: string;
  uploader_ip: string;
  owner_id?: string;    // 该版本的上传者飞书 UserID
  owner_name?: string;  // 该版本上传者姓名快照
}

// 版本列表响应
export interface VersionsResponse {
  current_version: string;
  versions: Record<string, VersionInfo>;
}

// 系统版本更新记录
export interface ChangelogEntry {
  version: string;
  date: string;
  changelog: string;
  type: string;  // "feature" | "security" | "fix" | "other"
}

// 审计日志条目
export interface LogEntry {
  time: string;
  category: string;     // "project" | "admin" | "access"
  action: string;
  actor_id: string;     // 稳定身份主键：飞书 UserID / emergency:账号 / anonymous
  actor_name: string;   // 展示名
  actor: string;        // 兼容字段，取 actor_name，为空时取 IP
  ip: string;
  target: string;
  detail: string;
}

// 当前登录者
export interface CurrentUser {
  userId: string;
  name: string;
  isAdmin: boolean;
  isSuperAdmin: boolean;
  source: string;       // "feishu" | "emergency"
}

// 用户档案条目（「指定负责人」「添加管理员」的候选来源）
export interface DirectoryUser {
  userId: string;
  name: string;
  firstLoginAt: string;
  lastLoginAt: string;
}

// 管理员名单条目
export interface AdminEntry {
  userId: string;
  name: string;
  level: string;        // "super" | "normal"
  createdAt: string;
}

// API 统一响应格式
export interface ApiResponse<T = unknown> {
  success: boolean;
  message?: string;
  data?: T;
  baseUrl?: string;
  token?: string;
}

// 服务器状态响应格式
export interface StatusResponse {
  success: boolean;
  status: string;
  ip: string;
  port: number;
  webappsDir: string;
  version: string;
}

// 产品线颜色配置
export const PRODUCT_LINES: Record<string, { color: string; bg: string }> = {
  // 康字头 → 健康浅绿
  '康老板AI医生': { color: '#27AE60', bg: '#E8F8EF' },
  '康老板健康': { color: '#27AE60', bg: '#E8F8EF' },
  '康老板商城': { color: '#27AE60', bg: '#E8F8EF' },
  '康店代理商': { color: '#27AE60', bg: '#E8F8EF' },
  '康管家': { color: '#27AE60', bg: '#E8F8EF' },
  // 老板云、老板帮 → 浅蓝
  '老板云': { color: '#5E8AE6', bg: '#EEF3FD' },
  '老板帮': { color: '#5E8AE6', bg: '#EEF3FD' },
  // 旅途管家 → 浅蓝
  '旅途管家': { color: '#5E8AE6', bg: '#EEF3FD' },
  // 幸福绩效 → 蓝色
  '幸福绩效': { color: '#2D5BDA', bg: '#EBF0FC' },
  // 数智化、企座、自搭云、创业天使 → 浅紫
  '数智化': { color: '#9575CD', bg: '#EDE7F6' },
  '企座': { color: '#9575CD', bg: '#EDE7F6' },
  '自搭云': { color: '#9575CD', bg: '#EDE7F6' },
  '创业天使': { color: '#9575CD', bg: '#EDE7F6' },
  // 飞联天下 → 浅红
  '飞联天下': { color: '#E96C78', bg: '#FEF1F2' },
  // 加速中心 → 浅红
  '加速中心': { color: '#E96C78', bg: '#FEF1F2' },
  // 会议系统 → 橙色
  '会议系统': { color: '#DAA557', bg: '#FDF6EC' },
};

export const PRODUCT_LINE_OPTIONS = Object.keys(PRODUCT_LINES);
