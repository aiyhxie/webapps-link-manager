/**
 * WebApps Link Manager - React Frontend
 *
 * 功能说明：
 * - 文件列表展示：自动扫描 webapps 目录下所有 HTML 文件
 * - 文件上传：支持 HTML 和 ZIP 文件上传（拖拽或点击）
 * - 文件编辑：编辑标题、描述、产品线
 * - 文件删除：基于飞书身份的权限控制（项目负责人或管理员）
 * - 密码保护：可为文件设置访问密码
 * - 身份认证：飞书扫码登录，凭据只走 HttpOnly Cookie，前端不保存 token
 * - 管理员系统：超级管理员可维护管理员名单、指定项目负责人、查看日志
 * - 主题切换：支持浅色、深色、自动跟随系统三种模式
 * - 产品线筛选：支持按产品线和负责人筛选文件
 *
 * 组件结构：
 * - App.tsx: 主组件，包含所有业务逻辑（已整合所有功能）
 * - components/EditModal.tsx: 编辑文件信息弹窗
 * - components/PasswordModal.tsx: 设置/修改密码弹窗
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { ConfigProvider, Layout, Typography, message, Input, Button, Space, Card, Empty, Tooltip, Popconfirm, Drawer, Badge, Dropdown, MenuProps, Progress, Select, theme as antdTheme } from 'antd';
import { SearchOutlined, CopyOutlined, EditOutlined, DeleteOutlined, DesktopOutlined, GlobalOutlined, MenuOutlined, AppstoreOutlined, SunOutlined, MoonOutlined, MoreOutlined, PlusOutlined, CheckOutlined, LockOutlined, UnlockOutlined, InboxOutlined, UserOutlined, LogoutOutlined, TeamOutlined, KeyOutlined, FileTextOutlined, DownOutlined } from '@ant-design/icons';
import EditModal from './components/EditModal';
import PasswordModal from './components/PasswordModal';
import ChangelogModal from './components/ChangelogModal';
import LogsDrawer from './components/LogsDrawer';
import OwnerAssignDrawer from './components/OwnerAssignDrawer';
import type { FileInfo, ChangelogEntry, CurrentUser, AdminEntry, DirectoryUser, VersionInfo } from './types';
import { PRODUCT_LINES } from './types';
import { api, clearLegacyCredentials } from './api';

type SortMode = 'init_desc' | 'init_asc' | 'update_desc' | 'update_asc' | 'product_line' | 'ip';

/** In-flight upload state used to drive the progress UI. */
type UploadState = { name: string; percent: number; processing: boolean };

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

type ThemeMode = 'light' | 'dark' | 'auto';

/**
 * antd 主题配置。
 *
 * 必须带上 algorithm：antd v5 的大量颜色是从 seed token 经 algorithm 派生的
 * （colorTextPlaceholder / colorTextDescription / colorIcon / colorSplit 等）。
 * 只覆盖 colorText、colorBgContainer 这类 token 而不切换 algorithm 时，派生色
 * 仍是浅色主题的值（如 placeholder 为 rgba(0,0,0,0.25)），画在深色底上几乎看
 * 不见 —— 这正是深色模式下输入框提示文字、抽屉关闭图标、分割线发暗的原因。
 *
 * token 里继续钉住项目原有的 Google 风格底色，保证卡片/抽屉底色与改动前一致，
 * 只让文字、图标、边框这些派生色走正确的算法。
 */
const lightTheme = {
  algorithm: antdTheme.defaultAlgorithm,
  token: {
    colorPrimary: '#4285f4',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBorder: '#dadce0',
    colorText: '#202124',
    colorTextSecondary: '#5f6368',
    colorBgLayout: '#f1f3f4',
  },
};

const darkTheme = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: '#8ab4f8',
    colorBgContainer: '#292a2d',
    colorBgElevated: '#3c4043',
    colorBorder: '#5f6368',
    colorText: '#e8eaed',
    colorTextSecondary: '#9aa0a6',
    colorBgLayout: '#202124',
    // 暗色算法默认的这几个值在本项目底色上仍偏暗，统一提一档保证可读性
    colorTextPlaceholder: 'rgba(255,255,255,0.45)',
    colorTextDescription: 'rgba(255,255,255,0.6)',
    colorIcon: 'rgba(255,255,255,0.65)',
    colorIconHover: '#ffffff',
    colorSplit: 'rgba(255,255,255,0.16)',
  },
};

function App() {
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [baseUrl, setBaseUrl] = useState('');
  const [version, setVersion] = useState('');
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [selectedOwner, setSelectedOwner] = useState<string | null>(null);
  const [selectedProductLine, setSelectedProductLine] = useState<string | null>(null);
  const [editVisible, setEditVisible] = useState(false);
  const [editingFile, setEditingFile] = useState<FileInfo | null>(null);
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [passwordModalVisible, setPasswordModalVisible] = useState(false);
  const [passwordFile, setPasswordFile] = useState<FileInfo | null>(null);
  const [versionModalVisible, setVersionModalVisible] = useState(false);
  const [versionFile, setVersionFile] = useState<FileInfo | null>(null);
  const [versionList, setVersionList] = useState<Record<string, VersionInfo>>({});
  const [currentVersion, setCurrentVersion] = useState('');

  // Changelog state
  const [changelogVisible, setChangelogVisible] = useState(false);
  const [changelogEntries, setChangelogEntries] = useState<ChangelogEntry[]>([]);

  // Card-level success tip state
  const [successTip, setSuccessTip] = useState<{ key: string; message: string } | null>(null);

  // Upload progress state.
  // `processing` = all bytes sent, server is still unzipping/writing, so the
  // bar sits at 100% with a "处理中" label instead of looking stuck.
  const [newUpload, setNewUpload] = useState<UploadState | null>(null);
  const [versionUploads, setVersionUploads] = useState<Record<string, UploadState>>({});
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem('themeMode');
    return (saved as ThemeMode) || 'auto';
  });

  const [sortMode, setSortMode] = useState<SortMode>(() => {
    const saved = localStorage.getItem('sortMode');
    return (saved as SortMode) || 'init_desc';
  });

  const [isDragging, setIsDragging] = useState(false);
  const [draggingOverKey, setDraggingOverKey] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const versionInputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  // 当前登录者（飞书身份）。null 表示尚未拉到 /api/me 结果
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [adminManageVisible, setAdminManageVisible] = useState(false);
  const [ownerAssignVisible, setOwnerAssignVisible] = useState(false);
  const [logsVisible, setLogsVisible] = useState(false);
  const [directoryUsers, setDirectoryUsers] = useState<DirectoryUser[]>([]);

  const isAdmin = !!me?.isAdmin;
  const isSuperAdmin = !!me?.isSuperAdmin;

  const getCurrentTheme = () => {
    if (themeMode === 'auto') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return themeMode;
  };

  const currentTheme = getCurrentTheme();
  const theme = currentTheme === 'dark' ? darkTheme : lightTheme;

  const bgColor = currentTheme === 'dark' ? '#202124' : '#f1f3f4';
  const headerBg = currentTheme === 'dark' ? '#292a2d' : '#ffffff';
  const siderBg = currentTheme === 'dark' ? '#292a2d' : '#ffffff';
  const cardBg = currentTheme === 'dark' ? '#292a2d' : '#ffffff';
  const borderColor = currentTheme === 'dark' ? '#5f6368' : '#dadce0';
  const textColor = currentTheme === 'dark' ? '#e8eaed' : '#202124';
  const textSecondary = currentTheme === 'dark' ? '#9aa0a6' : '#5f6368';
  const logoUrl = currentTheme === 'dark' ? '/files/tojoy-logo-w.png' : '/files/tojoy-logo-b.png';

  const loadFiles = useCallback(async () => {
    try {
      const data = await api.getFiles();
      if (data.success && data.data) {
        setFiles(data.data);
        if (data.baseUrl) setBaseUrl(data.baseUrl);
      }
      // Also load status for version
      const status = await api.getStatus();
      if (status.success && status.version) {
        setVersion(status.version);
      }
    } catch {
      message.error('加载文件列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadChangelog = useCallback(async () => {
    try {
      const data = await api.getChangelog();
      if (data.success && data.data) {
        setChangelogEntries(data.data);
      }
    } catch {
      // silently fail - changelog is not critical
    }
  }, []);

  const handleShowChangelog = useCallback(() => {
    loadChangelog().then(() => setChangelogVisible(true));
  }, [loadChangelog]);

  useEffect(() => {
    loadFiles();
    loadChangelog();
  }, [loadFiles, loadChangelog]);

  // 拉取当前登录者。到得了这个页面就意味着已通过认证 ——
  // 未登录的请求会被后端 302 到 /auth/login，根本不会渲染到这里。
  // 同时清理浏览器里遗留的旧管理员 token（改造前存在 localStorage）。
  useEffect(() => {
    clearLegacyCredentials();
    api.getMe().then(res => {
      if (res.success && res.data) setMe(res.data);
    });
  }, []);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => {
      if (themeMode === 'auto') {
        setThemeMode(prev => prev === 'auto' ? 'light' : 'auto');
        setTimeout(() => setThemeMode('auto'), 0);
      }
    };
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, [themeMode]);

  /**
   * 负责人分组。key 用 ownerId（稳定），展示用姓名。
   * ownerId 为空的项目归入「未指定负责人」，并排在最后一位 ——
   * 存量项目在超管指定负责人之前都会落在这一组。
   */
  const OWNERLESS = '__ownerless__';
  const uniqueOwners = useMemo(() => {
    const map = new Map<string, { id: string; name: string; count: number }>();
    files.forEach(f => {
      const id = f.ownerId || OWNERLESS;
      const name = f.ownerId ? (f.ownerName || f.ownerId) : '未指定负责人';
      const hit = map.get(id);
      if (hit) hit.count += 1;
      else map.set(id, { id, name, count: 1 });
    });
    const list = Array.from(map.values());
    return list.sort((a, b) => {
      if (a.id === OWNERLESS) return 1;
      if (b.id === OWNERLESS) return -1;
      return a.name.localeCompare(b.name);
    });
  }, [files]);

  const uniqueProductLines = useMemo(() => {
    const pls = new Set<string>();
    files.forEach(f => {
      if (f.productLine) pls.add(f.productLine);
    });
    return Array.from(pls).sort();
  }, [files]);

  const filteredFiles = useMemo(() => {
    let result = files.filter(f => {
      const matchSearch = !searchText ||
        f.title.toLowerCase().includes(searchText.toLowerCase()) ||
        f.path.toLowerCase().includes(searchText.toLowerCase()) ||
        (f.description || '').toLowerCase().includes(searchText.toLowerCase());
      const matchOwner = !selectedOwner
        || (selectedOwner === OWNERLESS ? !f.ownerId : f.ownerId === selectedOwner);
      const matchPl = !selectedProductLine || f.productLine === selectedProductLine;
      return matchSearch && matchOwner && matchPl;
    });

    // Sort files
    result.sort((a, b) => {
      switch (sortMode) {
        case 'init_desc':
          return (b.init_upload_time || '').localeCompare(a.init_upload_time || '');
        case 'init_asc':
          return (a.init_upload_time || '').localeCompare(b.init_upload_time || '');
        case 'update_desc':
          return (b.upload_time || '').localeCompare(a.upload_time || '');
        case 'update_asc':
          return (a.upload_time || '').localeCompare(b.upload_time || '');
        case 'product_line': {
          const plA = a.productLine || '';
          const plB = b.productLine || '';
          if (plA !== plB) {
            return plA.localeCompare(plB);
          }
          return (b.init_upload_time || '').localeCompare(a.init_upload_time || '');
        }
        case 'ip': {
          const ipA = a.ownerName || '';
          const ipB = b.ownerName || '';
          if (ipA !== ipB) {
            return ipA.localeCompare(ipB);
          }
          return (b.init_upload_time || '').localeCompare(a.init_upload_time || '');
        }
        default:
          return 0;
      }
    });

    return result;
  }, [files, searchText, selectedOwner, selectedProductLine, sortMode]);

  const handleUpload = async (file: File) => {
    if (newUpload) {
      message.warning('有文件正在上传，请稍候');
      return false;
    }
    setNewUpload({ name: file.name, percent: 0, processing: false });
    const result = await api.uploadFile(file, (percent) => {
      setNewUpload(prev => (prev ? { ...prev, percent, processing: percent >= 100 } : prev));
    });
    setNewUpload(null);
    if (result.success) {
      message.success(result.message || '上传成功');
      loadFiles();
      // Show card-level success tip
      if (result.data?.key) {
        setSuccessTip({ key: result.data.key, message: '项目添加成功' });
        setTimeout(() => setSuccessTip(null), 3000);
      }
    } else {
      message.error(result.message || '上传失败');
    }
    return false;
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleUpload(files[0]);
    }
    // Reset input so same file can be selected again
    e.target.value = '';
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      const file = files[0];
      const name = file.name.toLowerCase();
      if (name.endsWith('.html') || name.endsWith('.zip')) {
        handleUpload(file);
      } else {
        message.error('只支持 HTML 或 ZIP 文件');
      }
    }
  };

  const handleEdit = (file: FileInfo) => {
    setEditingFile(file);
    setEditVisible(true);
  };

  const handleEditSubmit = async (values: { title: string; description: string; productLine: string }) => {
    if (!editingFile) return;
    const result = await api.updateFile(editingFile.key, values);
    if (result.success) {
      message.success('已更新');
      setEditVisible(false);
      loadFiles();
    } else {
      message.error(result.message || '更新失败');
    }
  };

  const handleDelete = async (file: FileInfo) => {
    const result = await api.deleteFile(file.key);
    if (result.success) {
      message.success(result.message || '已删除');
      loadFiles();
    } else {
      message.error(result.message || '删除失败');
    }
  };

  const handleSetPassword = (file: FileInfo) => {
    setPasswordFile(file);
    setPasswordModalVisible(true);
  };

  const formatUploadTime = (uploadTime: string) => {
    if (!uploadTime) return '';
    const now = new Date();
    const upload = new Date(uploadTime);
    const diffMs = now.getTime() - upload.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffDays = Math.floor(diffMs / 86400000);

    // Within 10 minutes
    if (diffMins < 10) return '刚刚上传';
    // Within 1 hour
    if (diffMins < 60) return `${diffMins}分钟前上传`;
    // Within today
    if (diffDays === 0) {
      const hours = upload.getHours().toString().padStart(2, '0');
      const mins = upload.getMinutes().toString().padStart(2, '0');
      return `今天 ${hours}:${mins}上传`;
    }
    // Within this year
    const month = upload.getMonth() + 1;
    const day = upload.getDate();
    const hours = upload.getHours().toString().padStart(2, '0');
    const mins = upload.getMinutes().toString().padStart(2, '0');
    if (upload.getFullYear() === now.getFullYear()) {
      return `${month}月${day}日 ${hours}:${mins}上传`;
    }
    // Different year
    return `${upload.getFullYear()}年${month}月${day}日 ${hours}:${mins}上传`;
  };

  const handleLogout = async () => {
    await api.logout();
    // 后端已清掉会话 Cookie，跳到登录入口重新走飞书授权
    window.location.href = '/auth/login';
  };

  // 管理员名单（以飞书 UserID 为主键）
  const [adminUsers, setAdminUsers] = useState<AdminEntry[]>([]);

  const loadAdminUsers = useCallback(async () => {
    const result = await api.getAdmins();
    if (result.success && result.data) setAdminUsers(result.data);
  }, []);

  // 候选人只能来自已登录过本系统的用户 —— 走的是最小权限路线，
  // 没有申请飞书通讯录读取权限，所以同事必须先登录一次才能被选中。
  const loadDirectoryUsers = useCallback(async () => {
    const result = await api.getDirectoryUsers();
    if (result.success && result.data) setDirectoryUsers(result.data);
  }, []);

  useEffect(() => {
    if (adminManageVisible) {
      loadAdminUsers();
      loadDirectoryUsers();
    }
  }, [adminManageVisible, loadAdminUsers, loadDirectoryUsers]);

  useEffect(() => {
    if (ownerAssignVisible) loadDirectoryUsers();
  }, [ownerAssignVisible, loadDirectoryUsers]);

  const handleDeleteAdmin = async (userId: string) => {
    const result = await api.removeAdmin(userId);
    if (result.success) {
      message.success(result.message || '管理员已删除');
      loadAdminUsers();
      loadFiles();
    } else {
      message.error(result.message || '删除失败');
    }
  };

  const handleAddAdmin = async (userId: string) => {
    const result = await api.addAdmin(userId);
    if (result.success) {
      message.success(result.message || '已添加管理员');
      loadAdminUsers();
      loadFiles();
    } else {
      message.error(result.message || '添加失败');
    }
  };

  const handleAssignOwner = async (keys: string[], ownerId: string) => {
    const result = await api.assignOwner(keys, ownerId);
    if (result.success) {
      message.success(result.message || '已指定负责人');
      setOwnerAssignVisible(false);
      loadFiles();
    } else {
      message.error(result.message || '指定失败');
    }
  };

  const handlePasswordSubmit = async (password: string) => {
    if (!passwordFile) return;
    const result = await api.updateFile(passwordFile.key, { password });
    if (result.success) {
      message.success(password ? '密码已设置' : '密码已清除');
      setPasswordModalVisible(false);
      loadFiles();
    } else {
      message.error(result.message || '操作失败');
    }
  };

  const handleClearPassword = async () => {
    if (!passwordFile) return;
    const result = await api.updateFile(passwordFile.key, { password: '' });
    if (result.success) {
      message.success('密码已清除');
      setPasswordModalVisible(false);
      loadFiles();
    } else {
      message.error(result.message || '操作失败');
    }
  };

  // Version management
  const handleShowVersions = async (file: FileInfo) => {
    setVersionFile(file);
    const result = await api.getVersions(file.key);
    if (result.success && result.data) {
      setVersionList(result.data.versions || {});
      setCurrentVersion(result.data.current_version || 'V1');
    }
    setVersionModalVisible(true);
  };

  const handleUploadNewVersion = async (targetFile: FileInfo, file: File) => {
    if (versionUploads[targetFile.key]) {
      message.warning('该项目正在上传新版本，请稍候');
      return;
    }
    const setProgress = (state: UploadState | null) => {
      setVersionUploads(prev => {
        const next = { ...prev };
        if (state) next[targetFile.key] = state;
        else delete next[targetFile.key];
        return next;
      });
    };
    setProgress({ name: file.name, percent: 0, processing: false });
    const result = await api.uploadNewVersion(targetFile.key, file, (percent) => {
      setProgress({ name: file.name, percent, processing: percent >= 100 });
    });
    setProgress(null);
    if (result.success) {
      message.success(`${targetFile.title} ${result.version} 版本更新成功`);
      loadFiles();
      // Show card-level success tip
      setSuccessTip({ key: targetFile.key, message: `已更新为 ${result.version} 版本` });
      setTimeout(() => setSuccessTip(null), 3000);
      // Refresh version list only if the version history modal is open for this file
      if (versionFile?.key === targetFile.key) {
        const vr = await api.getVersions(targetFile.key);
        if (vr.success && vr.data) {
          setVersionList(vr.data.versions || {});
          setCurrentVersion(vr.data.current_version || 'V1');
        }
      }
    } else {
      message.error(result.message || '版本更新失败');
    }
  };

  const handleRestoreVersion = async (version: string) => {
    if (!versionFile) return;
    const result = await api.restoreVersion(versionFile.key, version);
    if (result.success) {
      message.success(`${versionFile.title} 已恢复为 ${version} 版本`);
      loadFiles();
      // Refresh version list
      const vr = await api.getVersions(versionFile.key);
      if (vr.success && vr.data) {
        setVersionList(vr.data.versions || {});
        setCurrentVersion(vr.data.current_version || 'V1');
      }
    } else {
      message.error(result.message || '恢复失败');
    }
  };

  const handleDeleteVersion = async (version: string) => {
    if (!versionFile) return;
    const result = await api.deleteVersion(versionFile.key, version);
    if (result.success) {
      message.success(`已删除 ${version} 版本`);
      loadFiles();
      // Refresh version list
      const vr = await api.getVersions(versionFile.key);
      if (vr.success && vr.data) {
        setVersionList(vr.data.versions || {});
        setCurrentVersion(vr.data.current_version || 'V1');
      }
    } else {
      message.error(result.message || '删除失败');
    }
  };


  const handleCardClick = (file: FileInfo) => {
    // Always open directly - password check happens on the file page itself
    window.open(file.url, '_blank');
  };

  const copyToClipboard = (text: string) => {
    // Try modern API first
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(() => {
        message.success('复制成功');
      }).catch(() => {
        // Fallback to textarea method
        tryClipboardCopy(text);
      });
    } else {
      // Fallback to textarea method
      tryClipboardCopy(text);
    }
  };

  const tryClipboardCopy = (text: string) => {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.cssText = 'position:fixed;left:-9999px;top:-9999px;';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    try {
      const success = document.execCommand('copy');
      if (success) {
        message.success('复制成功');
      } else {
        message.error('复制失败');
      }
    } catch {
      message.error('复制失败');
    } finally {
      document.body.removeChild(textarea);
    }
  };

  const themeIcon = {
    light: <SunOutlined />,
    dark: <MoonOutlined />,
    auto: <DesktopOutlined />,
  }[themeMode];

  // 勾选图标跟随主题主色，深色模式下 #4285f4 在深底上对比度不足
  const accentColor = currentTheme === 'dark' ? '#8ab4f8' : '#4285f4';
  const themeItems: MenuProps['items'] = [
    { key: 'auto', label: <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>跟随系统 {themeMode === 'auto' && <CheckOutlined style={{ color: accentColor }} />}</span> },
    { key: 'light', label: <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>浅色模式 {themeMode === 'light' && <CheckOutlined style={{ color: accentColor }} />}</span> },
    { key: 'dark', label: <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>深色模式 {themeMode === 'dark' && <CheckOutlined style={{ color: accentColor }} />}</span> },
  ];

  const productItems: MenuProps['items'] = [
    {
      key: 'interaction',
      label: <a href="https://doc.weixin.qq.com/smartsheet/s3_AAQAPQYZAFICN3xLtVsT0ToqNJWfN?scode=AHwAKgetAAYDz0n0GJAAQAPQYZAFI&tab=OvVR5n" target="_blank" rel="noopener noreferrer" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        交互设计工单表 ↗
      </a>,
    },
    {
      key: 'design',
      label: <a href="https://doc.weixin.qq.com/smartsheet/s3_AAQAPQYZAFICNxqYsCuA7Snq7P5Fa?scode=AHwAKgetAAYH7WR5jXAAQAPQYZAFI&tab=N6Vo1K" target="_blank" rel="noopener noreferrer" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        平面设计工单表 ↗
      </a>,
    },
  ];

  const onThemeClick: MenuProps['onClick'] = ({ key }) => {
    const newMode = key as ThemeMode;
    localStorage.setItem('themeMode', newMode);
    setThemeMode(newMode);
  };

  const getSortBase = (mode: SortMode) => mode.replace('_desc', '').replace('_asc', '');
  const isSortDesc = (mode: SortMode) => mode.endsWith('_desc');

  const onSortChange = (value: SortMode) => {
    const currentBase = getSortBase(sortMode);
    const newBase = getSortBase(value);
    // "默认" (init_desc) does not toggle
    if (currentBase === 'init' && newBase === 'init') {
      return;
    }
    let newMode: SortMode;
    if (currentBase === newBase) {
      newMode = isSortDesc(sortMode) ? (newBase + '_asc') as SortMode : (newBase + '_desc') as SortMode;
    } else {
      newMode = value;
    }
    localStorage.setItem('sortMode', newMode);
    setSortMode(newMode);
  };

  const SidebarContent = () => (
    <div style={{ padding: '16px 0' }}>
      {/* Product Line Filter */}
      <div style={{ padding: '0 16px', marginBottom: 8 }}>
        <Text style={{ color: textSecondary, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 500 }}>
          产品线
        </Text>
      </div>

      <div
        onClick={() => { setSelectedProductLine(null); setDrawerVisible(false); }}
        style={{
          padding: '8px 16px',
          cursor: 'pointer',
          background: !selectedProductLine ? (currentTheme === 'dark' ? 'rgba(138,180,248,0.15)' : '#e8f0fe') : 'transparent',
          color: !selectedProductLine ? (currentTheme === 'dark' ? '#8ab4f8' : '#4285f4') : textColor,
          borderRadius: !selectedProductLine ? '0 8px 8px 0' : 0,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 13,
          fontWeight: !selectedProductLine ? 500 : 400,
          marginLeft: -16,
          paddingLeft: 24,
        }}
      >
        <span style={{ flex: 1 }}>全部产品</span>
        <Badge count={files.length} style={{ backgroundColor: currentTheme === 'dark' ? '#5f6368' : '#dadce0', color: textSecondary, fontSize: 10 }} />
      </div>

      {uniqueProductLines.map(pl => {
        const count = files.filter(f => f.productLine === pl).length;
        const plColors = (PRODUCT_LINES as Record<string, { color: string; bg: string }>)[pl];
        return (
          <div
            key={pl}
            onClick={() => { setSelectedProductLine(pl); setDrawerVisible(false); }}
            style={{
              padding: '8px 16px',
              cursor: 'pointer',
              background: selectedProductLine === pl ? (currentTheme === 'dark' ? 'rgba(138,180,248,0.15)' : '#e8f0fe') : 'transparent',
              color: selectedProductLine === pl ? (currentTheme === 'dark' ? '#8ab4f8' : '#4285f4') : textColor,
              borderRadius: selectedProductLine === pl ? '0 8px 8px 0' : 0,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontSize: 13,
              fontWeight: selectedProductLine === pl ? 500 : 400,
              marginLeft: -16,
              paddingLeft: 24,
            }}
          >
            {plColors && (
              <span style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                backgroundColor: plColors.color,
                flexShrink: 0,
              }} />
            )}
            <span style={{ flex: 1 }}>{pl}</span>
            <Badge count={count} style={{ backgroundColor: currentTheme === 'dark' ? '#5f6368' : '#dadce0', color: textSecondary, fontSize: 10 }} />
          </div>
        );
      })}

      {/* 负责人筛选 */}
      <div style={{ padding: '16px 16px 8px', marginTop: 8, borderTop: `1px solid ${borderColor}` }}>
        <Text style={{ color: textSecondary, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 500 }}>
          负责人
        </Text>
      </div>

      <div
        onClick={() => { setSelectedOwner(null); setDrawerVisible(false); }}
        style={{
          padding: '8px 16px',
          cursor: 'pointer',
          background: !selectedOwner ? (currentTheme === 'dark' ? 'rgba(138,180,248,0.15)' : '#e8f0fe') : 'transparent',
          color: !selectedOwner ? (currentTheme === 'dark' ? '#8ab4f8' : '#4285f4') : textColor,
          borderRadius: !selectedOwner ? '0 8px 8px 0' : 0,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 13,
          fontWeight: !selectedOwner ? 500 : 400,
          marginLeft: -16,
          paddingLeft: 24,
        }}
      >
        <GlobalOutlined />
        <span style={{ flex: 1 }}>全部</span>
        <Badge count={files.length} style={{ backgroundColor: currentTheme === 'dark' ? '#5f6368' : '#dadce0', color: textSecondary, fontSize: 10 }} />
      </div>

      {uniqueOwners.map(owner => {
        const active = selectedOwner === owner.id;
        const ownerless = owner.id === OWNERLESS;
        return (
          <div
            key={owner.id}
            /* 再次点击同一分组取消筛选 */
            onClick={() => { setSelectedOwner(active ? null : owner.id); setDrawerVisible(false); }}
            style={{
              padding: '8px 16px',
              cursor: 'pointer',
              background: active ? (currentTheme === 'dark' ? 'rgba(138,180,248,0.15)' : '#e8f0fe') : 'transparent',
              color: active ? (currentTheme === 'dark' ? '#8ab4f8' : '#4285f4') : (ownerless ? textSecondary : textColor),
              borderRadius: active ? '0 8px 8px 0' : 0,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontSize: 13,
              fontWeight: active ? 500 : 400,
              marginLeft: -16,
              paddingLeft: 24,
            }}
          >
            {ownerless ? <InboxOutlined /> : <UserOutlined />}
            <Tooltip title={owner.name.length > 20 ? owner.name : ''}>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {owner.name.length > 20 ? owner.name.slice(0, 20) + '…' : owner.name}
              </span>
            </Tooltip>
            <Badge count={owner.count} style={{ backgroundColor: currentTheme === 'dark' ? '#5f6368' : '#dadce0', color: textSecondary, fontSize: 10 }} />
          </div>
        );
      })}
    </div>
  );

  return (
    <ConfigProvider theme={theme}>
      <Layout style={{ minHeight: '100vh', background: bgColor }}>
        {/* Fixed Header */}
        <Header style={{
          background: headerBg,
          borderBottom: `1px solid ${borderColor}`,
          padding: '0 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 100,
          height: 56,
          boxShadow: currentTheme === 'dark' ? 'none' : '0 1px 3px rgba(0,0,0,0.1)',
        }}>
          {/* Mobile Menu Button */}
          <Button
            type="text"
            icon={<MenuOutlined />}
            onClick={() => setDrawerVisible(true)}
            className="mobile-menu-btn"
            style={{ color: textColor, display: 'none' }}
          />

          {/* Left: Logo & Title (fixed width to span the sidebar area) */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, width: 200, flexShrink: 0 }}>
            <img src={logoUrl} alt="logo" style={{ height: 28, width: 'auto' }} />
            <span className="header-title" style={{ fontSize: 18, fontWeight: 600, color: textColor, whiteSpace: 'nowrap' }}>
              原型极速分享平台
            </span>
          </div>

          {/* Center: Search — left edge aligned with project cards (sider 220 + padding 28) */}
          <div style={{ flex: 1, maxWidth: 400, marginLeft: 28, marginRight: 24 }} className="header-search">
            <Input
              prefix={<SearchOutlined style={{ color: textSecondary }} />}
              placeholder="搜索文件名..."
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              style={{ background: currentTheme === 'dark' ? '#3c4043' : '#f1f3f4', border: 'none', borderRadius: 20 }}
              allowClear
            />
          </div>

          {/* Right: Menu */}
          <Space size={12}>
            {isSuperAdmin && (
              <>
                <Button
                  type="text"
                  style={{ color: textColor, height: 36, padding: '0 12px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 6 }}
                  onClick={() => setOwnerAssignVisible(true)}
                >
                  <TeamOutlined />
                  指定负责人
                </Button>
                <Button
                  type="text"
                  style={{ color: textColor, height: 36, padding: '0 12px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 6 }}
                  onClick={() => setAdminManageVisible(true)}
                >
                  <KeyOutlined />
                  管理员
                </Button>
              </>
            )}
            {isAdmin && (
              <Button
                type="text"
                style={{ color: textColor, height: 36, padding: '0 12px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 6 }}
                onClick={() => setLogsVisible(true)}
              >
                <FileTextOutlined />
                系统日志
              </Button>
            )}
            {me && (
              <Dropdown
                menu={{
                  items: [{ key: 'logout', label: '退出登录', icon: <LogoutOutlined /> }],
                  onClick: ({ key }) => { if (key === 'logout') handleLogout(); },
                }}
                trigger={['click']}
              >
                <Button
                  type="text"
                  style={{ color: textSecondary, height: 36, padding: '0 12px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  <UserOutlined />
                  {me.name}
                  {me.source === 'emergency' && (
                    <Badge count="应急" style={{ backgroundColor: '#f5a623', fontSize: 10 }} />
                  )}
                  {isSuperAdmin && me.source !== 'emergency' && (
                    <Badge count="超管" style={{ backgroundColor: '#52c41a', fontSize: 10 }} />
                  )}
                  <DownOutlined style={{ fontSize: 10 }} />
                </Button>
              </Dropdown>
            )}

            <Dropdown menu={{ items: productItems }} trigger={['click']}>
              <Button type="text" style={{ color: textColor, height: 36, padding: '0 12px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                <AppstoreOutlined />
                设计工单
                <MoreOutlined style={{ fontSize: 10 }} />
              </Button>
            </Dropdown>

            <Dropdown menu={{ items: themeItems, onClick: onThemeClick }} trigger={['click']}>
              <Button type="text" style={{ color: textColor, height: 36, padding: '0 12px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                {themeIcon}
              </Button>
            </Dropdown>
          </Space>
        </Header>

        {/* Main Layout */}
        <div style={{ display: 'flex', marginTop: 56 }}>
          {/* Left Sidebar */}
          <Sider
            width={220}
            style={{
              background: siderBg,
              borderRight: `1px solid ${borderColor}`,
              position: 'fixed',
              left: 0,
              top: 56,
              bottom: 0,
              overflow: 'auto',
              display: 'flex',
              flexDirection: 'column',
            }}
            className="desktop-sider"
          >
            <div style={{ flex: 1, overflow: 'auto' }}>
              <SidebarContent />
            </div>
          </Sider>

          {/* Mobile Filter Drawer */}
          <Drawer
            title="筛选上传者"
            placement="left"
            onClose={() => setDrawerVisible(false)}
            open={drawerVisible}
            styles={{ body: { padding: 0, background: siderBg } }}
            width={280}
          >
            <SidebarContent />
          </Drawer>

          {/* Right Content */}
          <Content style={{ marginLeft: 220, flex: 1, minHeight: 'calc(100vh - 56px)' }} className="main-content">
            {/* Mobile Search */}
            <div className="mobile-search" style={{ padding: '16px', background: headerBg, borderBottom: `1px solid ${borderColor}` }}>
              <Input
                prefix={<SearchOutlined style={{ color: textSecondary }} />}
                placeholder="搜索文件名..."
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                style={{ background: currentTheme === 'dark' ? '#3c4043' : '#f1f3f4', border: 'none' }}
                allowClear
              />
            </div>

            {/* Content Area */}
            <div style={{ padding: '24px 28px' }}>
              {/* Intro Card */}
              <Card
                style={{
                  background: currentTheme === 'dark' ? 'rgba(138,180,248,0.08)' : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                  border: 'none',
                  borderRadius: 12,
                  marginBottom: 24,
                  color: '#fff',
                }}
                bodyStyle={{ padding: '20px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
              >
                <div>
                  <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>欢迎使用天九共享·原型极速分享平台</div>
                  <div style={{ fontSize: 14, opacity: 0.9 }}>
                    上传AI生成的HTML原型文件，一键生成内网可访问链接，让团队成员即时预览、高效反馈，告别文件反复传输。
                  </div>
                </div>
                {/* Sort Options */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, marginLeft: 24 }}>
                  {[
                    { key: 'init_desc' as SortMode, label: '默认排序' },
                    { key: 'update_desc' as SortMode, label: '更新时间' },
                    { key: 'product_line' as SortMode, label: '产品线' },
                    { key: 'ip' as SortMode, label: '上传者' },
                  ].map(opt => {
                    const isActive = getSortBase(sortMode) === getSortBase(opt.key);
                    // "默认" does not show direction arrow
                    const arrow = (opt.key === 'init_desc') ? '' : (isSortDesc(sortMode) && isActive ? ' ↓' : (!isSortDesc(sortMode) && isActive ? ' ↑' : ''));
                    return (
                      <Button
                        key={opt.key}
                        size="small"
                        type={isActive ? 'primary' : 'text'}
                        onClick={() => onSortChange(opt.key)}
                        style={{
                          borderRadius: 16,
                          padding: '2px 12px',
                          height: 28,
                          fontSize: 12,
                          ...(isActive ? {} : { color: 'rgba(255,255,255,0.85)', borderColor: 'rgba(255,255,255,0.3)' }),
                        }}
                      >
                        {opt.label}{arrow}
                      </Button>
                    );
                  })}
                </div>
              </Card>

              {/* File Grid */}
              {loading ? (
                <div style={{ textAlign: 'center', padding: 60, color: textSecondary }}>加载中...</div>
              ) : (
                <div style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 16,
                  width: '100%',
                }} className="file-grid">
                  {/* Upload Card (First) - Direct drag & click upload */}
                  <div
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    onClick={() => { if (!newUpload) fileInputRef.current?.click(); }}
                    className="file-card upload-card"
                    style={{
                      background: isDragging && !newUpload
                        ? (currentTheme === 'dark' ? 'rgba(138,180,248,0.85)' : 'rgba(66,133,244,0.75)')
                        : cardBg,
                      border: `2px dashed ${isDragging && !newUpload ? (currentTheme === 'dark' ? '#8ab4f8' : '#4285f4') : borderColor}`,
                      borderRadius: 12,
                      minHeight: 120,
                      cursor: newUpload ? 'progress' : 'pointer',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'all 0.2s ease',
                    }}
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".html,.zip,.HTML,.ZIP"
                      onChange={handleFileInputChange}
                      style={{ display: 'none' }}
                    />
                    {newUpload ? (
                      <div style={{ width: '80%', textAlign: 'center' }}>
                        <div style={{
                          color: textColor,
                          fontSize: 12,
                          marginBottom: 6,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}>
                          {newUpload.name}
                        </div>
                        <Progress
                          percent={newUpload.percent}
                          status="active"
                          size="small"
                          showInfo={!newUpload.processing}
                        />
                        <div style={{ color: textSecondary, fontSize: 11, marginTop: 2 }}>
                          {newUpload.processing ? '上传完成，正在处理…' : `上传中 ${newUpload.percent}%`}
                        </div>
                      </div>
                    ) : isDragging ? (
                      <>
                        <InboxOutlined style={{ fontSize: 28, color: '#ffffff', marginBottom: 8 }} />
                        <div style={{ color: '#ffffff', fontSize: 13 }}>释放以上传</div>
                      </>
                    ) : (
                      <>
                        <PlusOutlined style={{ fontSize: 28, color: textSecondary, marginBottom: 8 }} />
                        <div style={{ color: textSecondary, fontSize: 13 }}>上传新项目</div>
                        <div style={{ color: textSecondary, fontSize: 11, marginTop: 2 }}>点击或拖拽 HTML 或 ZIP 文件到此区域即可创建新项目</div>
                      </>
                    )}
                  </div>

                  {filteredFiles.map(file => {
                    const fullUrl = `${baseUrl}${file.url}`;
                    const isDragOver = draggingOverKey === file.key;
                    return (
                      <Card
                        key={file.key}
                        hoverable
                        onClick={() => handleCardClick(file)}
                        onDragOver={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setDraggingOverKey(file.key);
                        }}
                        onDragLeave={(e) => {
                          e.stopPropagation();
                          if (draggingOverKey === file.key) setDraggingOverKey(null);
                        }}
                        onDrop={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setDraggingOverKey(null);
                          const files = e.dataTransfer.files;
                          if (files && files.length > 0) {
                            const f = files[0];
                            if (!file.canManage) {
                              message.error(`${file.title}：暂无编辑权限`);
                            } else {
                              handleUploadNewVersion(file, f);
                            }
                          }
                        }}
                        className="file-card"
                        style={{
                          background: cardBg,
                          border: `1px solid ${isDragOver ? (currentTheme === 'dark' ? '#8ab4f8' : '#4285f4') : borderColor}`,
                          borderRadius: 12,
                          cursor: 'pointer',
                          position: 'relative',
                        }}
                        bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column', height: '100%' }}
                      >
                        {/* Version upload progress banner */}
                        {versionUploads[file.key] && (
                          <div
                            onClick={(e) => e.stopPropagation()}
                            style={{
                              background: currentTheme === 'dark' ? 'rgba(138,180,248,0.16)' : 'rgba(66,133,244,0.08)',
                              padding: '5px 12px 2px',
                              borderRadius: '12px 12px 0 0',
                              flexShrink: 0,
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 11, color: textSecondary }}>
                              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {versionUploads[file.key].name}
                              </span>
                              <span style={{ flexShrink: 0 }}>
                                {versionUploads[file.key].processing ? '处理中…' : `上传中 ${versionUploads[file.key].percent}%`}
                              </span>
                            </div>
                            <Progress
                              percent={versionUploads[file.key].percent}
                              status="active"
                              size="small"
                              showInfo={false}
                            />
                          </div>
                        )}

                        {/* Success tip banner */}
                        {successTip?.key === file.key && (
                          <div style={{
                            background: '#52c41a',
                            color: '#fff',
                            fontSize: 12,
                            padding: '4px 12px',
                            textAlign: 'center',
                            borderRadius: '12px 12px 0 0',
                            flexShrink: 0,
                          }}>
                            {successTip.message}
                          </div>
                        )}

                        {/* Card Header */}
                        <div
                          style={{
                            padding: '14px 16px',
                            borderBottom: `1px solid ${borderColor}`,
                            display: 'flex',
                            alignItems: 'center',
                            gap: 10,
                          }}
                        >
                          <span style={{ fontSize: 20 }}>📄</span>
                          <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
                            {file.productLine && (() => {
                              const pl = (file.productLine as keyof typeof PRODUCT_LINES);
                              const colors = PRODUCT_LINES[pl];
                              if (!colors) return null;
                              const isDark = currentTheme === 'dark';
                              return (
                                <span style={{
                                  fontSize: 11,
                                  color: isDark ? '#fff' : colors.color,
                                  background: isDark ? 'rgba(255,255,255,0.15)' : colors.bg,
                                  padding: '2px 8px',
                                  borderRadius: 4,
                                  flexShrink: 0,
                                }}>
                                  {file.productLine}
                                </span>
                              );
                            })()}
                            <Tooltip title={file.title}>
                              <span style={{
                                fontWeight: 500,
                                fontSize: 14,
                                color: currentTheme === 'dark' ? '#8ab4f8' : '#4285f4',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                flex: 1,
                              }}>
                                {file.title}
                              </span>
                            </Tooltip>
                            {file.currentVersion && (
                              <Tooltip title="查看版本历史">
                                <span
                                  onClick={(e) => { e.stopPropagation(); handleShowVersions(file); }}
                                  style={{
                                    fontSize: 11,
                                    color: textSecondary,
                                    background: currentTheme === 'dark' ? 'rgba(255,255,255,0.1)' : '#f1f3f4',
                                    padding: '2px 6px',
                                    borderRadius: 4,
                                    flexShrink: 0,
                                    cursor: 'pointer',
                                  }}>
                                  {file.currentVersion}
                                </span>
                              </Tooltip>
                            )}
                            {/* Hidden per-card input for uploading a new version.
                                onClick stopPropagation prevents the programmatic
                                input.click() event from bubbling to the Card and
                                triggering handleCardClick (opening project detail). */}
                            <input
                              ref={(el) => { versionInputRefs.current[file.key] = el; }}
                              type="file"
                              accept=".html,.HTML,.zip,.ZIP"
                              style={{ display: 'none' }}
                              onClick={(e) => e.stopPropagation()}
                              onChange={(e) => {
                                const f = e.target.files?.[0];
                                if (f) {
                                  if (!file.canManage) {
                                    message.error(`${file.title}：暂无编辑权限`);
                                  } else {
                                    handleUploadNewVersion(file, f);
                                  }
                                }
                                e.target.value = '';
                              }}
                            />
                            {file.canManage && (
                              <Tooltip title="上传新版本">
                                <Button
                                  size="small"
                                  type="text"
                                  icon={<PlusOutlined />}
                                  onClick={(e) => { e.stopPropagation(); versionInputRefs.current[file.key]?.click(); }}
                                  style={{ color: textSecondary, flexShrink: 0 }}
                                />
                              </Tooltip>
                            )}
                            {file.canManage && (
                              <Tooltip title="编辑信息">
                                <Button
                                  size="small"
                                  type="text"
                                  icon={<EditOutlined />}
                                  onClick={(e) => { e.stopPropagation(); handleEdit(file); }}
                                  style={{ color: textSecondary, flexShrink: 0 }}
                                />
                              </Tooltip>
                            )}
                            {file.hasPassword && (
                              <Tooltip title={file.canManage ? '已加密，点击修改' : '已加密'}>
                                <Button
                                  size="small"
                                  type="text"
                                  icon={<LockOutlined />}
                                  onClick={(e) => { e.stopPropagation(); file.canManage && handleSetPassword(file); }}
                                  style={{ color: '#f5a623', flexShrink: 0, cursor: file.canManage ? 'pointer' : 'default' }}
                                />
                              </Tooltip>
                            )}
                            {file.canManage && !file.hasPassword && (
                              <Tooltip title="设置密码">
                                <Button
                                  size="small"
                                  type="text"
                                  icon={<UnlockOutlined />}
                                  onClick={(e) => { e.stopPropagation(); handleSetPassword(file); }}
                                  style={{ color: textSecondary, flexShrink: 0 }}
                                />
                              </Tooltip>
                            )}
                          </div>
                        </div>

                        {/* Drag overlay for version update */}
                        {isDragOver && (
                          <div
                            style={{
                              position: 'absolute',
                              inset: 0,
                              background: currentTheme === 'dark' ? 'rgba(138,180,248,0.85)' : 'rgba(66,133,244,0.75)',
                              borderRadius: 12,
                              display: 'flex',
                              flexDirection: 'column',
                              alignItems: 'center',
                              justifyContent: 'center',
                              zIndex: 10,
                              pointerEvents: 'none',
                            }}
                          >
                            <InboxOutlined style={{ fontSize: 28, color: '#ffffff' }} />
                            <div style={{ color: '#ffffff', fontSize: 13, marginTop: 8 }}>
                              释放以更新版本
                            </div>
                          </div>
                        )}

                        {/* Card Body */}
                        <div style={{ padding: '12px 16px' }}>
                          {file.description && (
                            <div style={{ fontSize: 13, color: textSecondary, marginBottom: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {file.description}
                            </div>
                          )}
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <Tooltip title={fullUrl}>
                              <div
                                style={{
                                  flex: 1,
                                  fontFamily: 'monospace',
                                  fontSize: 11,
                                  color: currentTheme === 'dark' ? '#8ab4f8' : '#4285f4',
                                  background: currentTheme === 'dark' ? 'rgba(138,180,248,0.2)' : '#e8f0fe',
                                  padding: '6px 10px',
                                  borderRadius: 6,
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                }}
                              >
                                {fullUrl}
                              </div>
                            </Tooltip>
                            <Tooltip title="复制链接">
                              <Button
                                size="small"
                                icon={<CopyOutlined />}
                                onClick={(e) => { e.stopPropagation(); copyToClipboard(fullUrl); }}
                                style={{ flexShrink: 0 }}
                              />
                            </Tooltip>
                            {file.canManage && (
                              <Popconfirm
                                title="确认删除"
                                description={`删除「${file.title}」？`}
                                onConfirm={(e) => { e?.stopPropagation(); handleDelete(file); }}
                                onCancel={(e) => { e?.stopPropagation(); }}
                                okText="删除"
                                cancelText="取消"
                                okButtonProps={{ danger: true }}
                              >
                                <Button
                                  size="small"
                                  icon={<DeleteOutlined style={{ color: '#ff4d4f' }} />}
                                  onClick={(e) => e.stopPropagation()}
                                  style={{ flexShrink: 0 }}
                                />
                              </Popconfirm>
                            )}
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
                            <div style={{
                              fontSize: 11,
                              color: file.ownerId ? textSecondary : '#f5a623',
                              display: 'flex', alignItems: 'center', gap: 4,
                              minWidth: 0,
                            }}>
                              <UserOutlined style={{ fontSize: 10 }} />
                              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {file.ownerId ? (file.ownerName || file.ownerId) : '未指定负责人'}
                              </span>
                            </div>
                            {file.upload_time && (
                              <div style={{ fontSize: 11, color: textSecondary }}>
                                {formatUploadTime(file.upload_time)}
                              </div>
                            )}
                          </div>
                        </div>
                      </Card>
                    );
                  })}

                  {!loading && filteredFiles.length === 0 && !searchText && (
                    <Card
                      style={{
                        background: cardBg,
                        border: `1px solid ${borderColor}`,
                        borderRadius: 12,
                        gridColumn: '1 / -1',
                      }}
                      bodyStyle={{ padding: '60px 20px', textAlign: 'center' }}
                    >
                      <Empty description="还没有上传任何文件，点击上方卡片开始上传" style={{ color: textSecondary }} />
                    </Card>
                  )}
                </div>
              )}
            </div>
          </Content>
        </div>
      </Layout>

      {/* Responsive Styles */}
      <style>{`
        html, body, #root {
          height: 100%;
          margin: 0;
          padding: 0;
          background: ${bgColor} !important;
        }
        .ant-layout {
          min-height: 100vh !important;
          background: ${bgColor} !important;
        }
        .ant-layout-content {
          background: ${bgColor} !important;
        }
        @media (max-width: 768px) {
          .desktop-sider { display: none !important; }
          .main-content { margin-left: 0 !important; }
          .header-search { display: none !important; }
          .mobile-search { display: block !important; }
          .mobile-menu-btn { display: flex !important; }
          .file-card { width: 100% !important; min-width: 0 !important; }
        }
        @media (min-width: 769px) and (max-width: 1024px) {
          .file-card { width: calc(50% - 8px) !important; min-width: 0 !important; }
        }
        @media (min-width: 1025px) {
          .file-card { width: calc(33.333% - 11px) !important; min-width: 0 !important; }
        }
        @media (min-width: 769px) {
          .mobile-search { display: none !important; }
        }
        .file-card { display: flex !important; flex-direction: column !important; }
        .file-grid { display: flex !important; flex-wrap: wrap !important; }
      `}</style>

      <EditModal
        visible={editVisible}
        file={editingFile}
        onClose={() => setEditVisible(false)}
        onSubmit={handleEditSubmit}
        key={editingFile?.key}
      />

      <PasswordModal
        visible={passwordModalVisible}
        currentPassword={passwordFile?.hasPassword ? '******' : null}
        onClose={() => setPasswordModalVisible(false)}
        onSubmit={handlePasswordSubmit}
        onClearPassword={handleClearPassword}
      />

      {/* Changelog Modal */}
      <ChangelogModal
        visible={changelogVisible}
        entries={changelogEntries}
        currentVersion={version}
        onClose={() => setChangelogVisible(false)}
      />

      {/* 管理员名单（超管）—— 候选来自已登录过本系统的用户 */}
      <Drawer
        title="管理员管理"
        open={adminManageVisible}
        onClose={() => setAdminManageVisible(false)}
        width={480}
      >
        <div style={{ marginTop: 8 }}>
          <div style={{ marginBottom: 20 }}>
            <Text style={{ color: textSecondary, fontSize: 12, display: 'block', marginBottom: 8 }}>
              添加普通管理员
            </Text>
            <Select
              showSearch
              placeholder="搜索并选择同事"
              style={{ width: '100%' }}
              optionFilterProp="label"
              value={null}
              onChange={(value: string) => handleAddAdmin(value)}
              options={directoryUsers
                .filter(u => !adminUsers.some(a => a.userId === u.userId))
                .map(u => ({ label: u.name, value: u.userId }))}
              notFoundContent="没有可添加的用户"
            />
            <Text style={{ color: textSecondary, fontSize: 11, display: 'block', marginTop: 6 }}>
              只能从登录过本系统的同事里选择。本系统未申请飞书通讯录权限，
              所以对方需要先用飞书登录一次才会出现在这里。
            </Text>
          </div>

          <div>
            <Text style={{ color: textSecondary, fontSize: 12, display: 'block', marginBottom: 8 }}>
              管理员列表
            </Text>
            {adminUsers.map(user => {
              const isSelf = user.userId === me?.userId;
              const isSuper = user.level === 'super';
              return (
                <div key={user.userId} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 0', borderBottom: `1px solid ${borderColor}` }}>
                  <div style={{ minWidth: 0 }}>
                    <UserOutlined style={{ marginRight: 8 }} />
                    <span style={{ color: textColor }}>{user.name}</span>
                    {isSuper && <Badge count="超管" style={{ backgroundColor: '#52c41a', fontSize: 10, marginLeft: 8 }} />}
                    {isSelf && <Badge status="success" text="当前" style={{ marginLeft: 8 }} />}
                    <div style={{ fontSize: 11, color: textSecondary, fontFamily: 'monospace', marginTop: 2 }}>
                      {user.userId}
                    </div>
                  </div>
                  {!isSelf && (
                    <Popconfirm
                      title="移除管理员"
                      description={`将 ${user.name} 从管理员名单中移除？`}
                      okText="移除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleDeleteAdmin(user.userId)}
                    >
                      <Button size="small" danger>移除</Button>
                    </Popconfirm>
                  )}
                </div>
              );
            })}
            {adminUsers.length === 0 && <Text style={{ color: textSecondary }}>暂无管理员</Text>}
          </div>
        </div>
      </Drawer>

      {/* 批量指定项目负责人（超管）*/}
      <OwnerAssignDrawer
        visible={ownerAssignVisible}
        files={files}
        users={directoryUsers}
        onClose={() => setOwnerAssignVisible(false)}
        onSubmit={handleAssignOwner}
      />

      {/* System Logs Drawer — any logged-in admin (super or regular) has equal access */}
      <LogsDrawer visible={logsVisible} onClose={() => setLogsVisible(false)} />

      {/* Version History Drawer */}
      <Drawer
        title={`版本历史 — ${versionFile?.title || ''}`}
        open={versionModalVisible}
        onClose={() => setVersionModalVisible(false)}
        width={520}
      >
        <div style={{ marginTop: 16 }}>
          {/* Version list - exclude current version */}
          <div>
            {Object.entries(versionList)
              .filter(([version]) => version !== currentVersion)
              .sort(([a], [b]) => {
                const numA = parseInt(a.replace('V', '')) || 0;
                const numB = parseInt(b.replace('V', '')) || 0;
                return numB - numA;
              })
              .map(([version, info]) => {
                const uploadDate = new Date(info.upload_time);
                const dateStr = `${uploadDate.getMonth() + 1}月${uploadDate.getDate()}日 ${String(uploadDate.getHours()).padStart(2, '0')}:${String(uploadDate.getMinutes()).padStart(2, '0')}`;
                return (
                  <div
                    key={version}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      padding: '12px 0',
                      borderBottom: `1px solid ${borderColor}`,
                      gap: 8,
                    }}
                  >
                    <span style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      border: `2px solid #d9d9d9`,
                      flexShrink: 0,
                    }} />
                    <span style={{
                      fontWeight: 400,
                      color: textColor,
                      minWidth: 40,
                    }}>
                      {version}
                    </span>
                    <span style={{ flex: 1, fontSize: 12, color: textSecondary }}>
                      {dateStr} {info.owner_name ? `· ${info.owner_name}` : (info.uploader_ip ? `· ${info.uploader_ip}` : '')}
                    </span>
                    <Button size="small" onClick={() => window.open(`/versions/${versionFile?.path}/${version}`, '_blank')}>
                      预览
                    </Button>
                    {/* 恢复入口仅对有编辑权限的用户显示（上传者本人或已登录管理员）；
                        版本列表与预览本身无需权限，任何人可见 */}
                    {versionFile?.canManage && (
                      <Button size="small" onClick={() => handleRestoreVersion(version)}>
                        恢复此版本
                      </Button>
                    )}
                    {versionFile?.canManage && (
                      <Popconfirm
                        title="确认删除"
                        description={`删除 ${version} 版本？`}
                        onConfirm={() => handleDeleteVersion(version)}
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                      >
                        <Button size="small" danger>删除</Button>
                      </Popconfirm>
                    )}
                  </div>
                );
              })}
            {Object.keys(versionList).filter(v => v !== currentVersion).length === 0 && (
              <div style={{ textAlign: 'center', padding: '40px 0', color: textSecondary }}>
                暂无历史版本
              </div>
            )}
          </div>
        </div>
      </Drawer>

      {/* Fixed Version Bar at Bottom */}
      {version && (
        <div style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          width: 220,
          height: 28,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
        }}>
          <div style={{
            background: currentTheme === 'dark' ? 'rgba(41,42,45,0.9)' : 'rgba(255,255,255,0.9)',
            padding: '2px 10px',
            borderRadius: 10,
          }}>
            <Text
              style={{ color: textSecondary, fontSize: 12, cursor: 'pointer' }}
              onClick={handleShowChangelog}
              title="点击查看版本更新日志"
            >
              版本号: v{version}
            </Text>
          </div>
        </div>
      )}
    </ConfigProvider>
  );
}

export default App;
