/**
 * WebApps Link Manager - React Frontend
 *
 * 功能说明：
 * - 文件列表展示：自动扫描 webapps 目录下所有 HTML 文件
 * - 文件上传：支持 HTML 和 ZIP 文件上传（拖拽或点击）
 * - 文件编辑：编辑标题、描述、产品线
 * - 文件删除：基于 IP 的权限控制（上传者或管理员可删除）
 * - 密码保护：可为文件设置访问密码
 * - 管理员系统：超级管理员可管理其他管理员、查看日志
 * - 主题切换：支持浅色、深色、自动跟随系统三种模式
 * - 产品线筛选：支持按产品线和上传者筛选文件
 *
 * 组件结构：
 * - App.tsx: 主组件，包含所有业务逻辑（已整合所有功能）
 * - components/EditModal.tsx: 编辑文件信息弹窗
 * - components/PasswordModal.tsx: 设置/修改密码弹窗
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { ConfigProvider, Layout, Typography, message, Input, Button, Space, Card, Empty, Tooltip, Popconfirm, Drawer, Badge, Dropdown, MenuProps, Modal, Form } from 'antd';
import { SearchOutlined, ReloadOutlined, CopyOutlined, EditOutlined, DeleteOutlined, DesktopOutlined, GlobalOutlined, MenuOutlined, AppstoreOutlined, SunOutlined, MoonOutlined, MoreOutlined, PlusOutlined, CheckOutlined, LockOutlined, UnlockOutlined, InboxOutlined, UserOutlined, LogoutOutlined, TeamOutlined } from '@ant-design/icons';
import EditModal from './components/EditModal';
import PasswordModal from './components/PasswordModal';
import type { FileInfo } from './types';
import { PRODUCT_LINES } from './types';
import { api, setAdminToken, clearAdminToken, getAdminToken } from './api';

type SortMode = 'time_desc' | 'time_asc' | 'product_line' | 'ip';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

type ThemeMode = 'light' | 'dark' | 'auto';

const lightTheme = {
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
  token: {
    colorPrimary: '#8ab4f8',
    colorBgContainer: '#292a2d',
    colorBgElevated: '#3c4043',
    colorBorder: '#5f6368',
    colorText: '#e8eaed',
    colorTextSecondary: '#9aa0a6',
    colorBgLayout: '#202124',
  },
};

function App() {
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [baseUrl, setBaseUrl] = useState('');
  const [version, setVersion] = useState('');
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [selectedIp, setSelectedIp] = useState<string | null>(null);
  const [selectedProductLine, setSelectedProductLine] = useState<string | null>(null);
  const [editVisible, setEditVisible] = useState(false);
  const [editingFile, setEditingFile] = useState<FileInfo | null>(null);
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [passwordModalVisible, setPasswordModalVisible] = useState(false);
  const [passwordFile, setPasswordFile] = useState<FileInfo | null>(null);
  const [versionModalVisible, setVersionModalVisible] = useState(false);
  const [versionFile, setVersionFile] = useState<FileInfo | null>(null);
  const [versionList, setVersionList] = useState<Record<string, { upload_time: string; uploader_ip: string }>>({});
  const [currentVersion, setCurrentVersion] = useState('');
  const [versionFileInputKey, setVersionFileInputKey] = useState(0);
  const [themeMode, setThemeMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem('themeMode');
    return (saved as ThemeMode) || 'auto';
  });

  const [sortMode, setSortMode] = useState<SortMode>(() => {
    const saved = localStorage.getItem('sortMode');
    return (saved as SortMode) || 'time_desc';
  });

  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Admin state
  const [adminLoggedIn, setAdminLoggedIn] = useState(false);
  const [adminUsername, setAdminUsername] = useState('');
  const [isSuperAdmin, setIsSuperAdmin] = useState(false);
  const [hasAdmins, setHasAdmins] = useState(true);
  const [adminLoginVisible, setAdminLoginVisible] = useState(false);
  const [adminManageVisible, setAdminManageVisible] = useState(false);
  const [adminSetupVisible, setAdminSetupVisible] = useState(false);
  const [adminLoginForm] = Form.useForm();
  const [adminSetupForm] = Form.useForm();

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

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  // Check admin status on load
  useEffect(() => {
    const checkAdminStatus = async () => {
      const result = await api.getAdminStatus();
      if (result.success) {
        setHasAdmins(result.hasAdmins ?? true);
        if (result.isLoggedIn) {
          setAdminLoggedIn(true);
          setAdminUsername(result.username || '');
          setIsSuperAdmin(result.isSuperAdmin || false);
        }
      }
    };
    checkAdminStatus();
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

  const uniqueIps = useMemo(() => {
    const ips = new Set<string>();
    files.forEach(f => {
      if (f.uploader_ip) ips.add(f.uploader_ip);
    });
    return Array.from(ips).sort();
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
      const matchIp = !selectedIp || f.uploader_ip === selectedIp;
      const matchPl = !selectedProductLine || f.productLine === selectedProductLine;
      return matchSearch && matchIp && matchPl;
    });

    // Sort files
    result.sort((a, b) => {
      switch (sortMode) {
        case 'time_desc':
          // Newest first (by upload_time)
          return (b.upload_time || '').localeCompare(a.upload_time || '');
        case 'time_asc':
          // Oldest first
          return (a.upload_time || '').localeCompare(b.upload_time || '');
        case 'product_line': {
          // Product line first, then by time desc
          const plA = a.productLine || '';
          const plB = b.productLine || '';
          if (plA !== plB) {
            return plA.localeCompare(plB);
          }
          return (b.upload_time || '').localeCompare(a.upload_time || '');
        }
        case 'ip': {
          // IP first, then by time desc
          const ipA = a.uploader_ip || '';
          const ipB = b.uploader_ip || '';
          if (ipA !== ipB) {
            return ipA.localeCompare(ipB);
          }
          return (b.upload_time || '').localeCompare(a.upload_time || '');
        }
        default:
          return 0;
      }
    });

    return result;
  }, [files, searchText, selectedIp, selectedProductLine, sortMode]);

  const handleUpload = async (file: File) => {
    const result = await api.uploadFile(file);
    if (result.success) {
      message.success(result.message || '上传成功');
      loadFiles();
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

  const handleAdminLogin = async (values: { username: string; password: string }) => {
    const result = await api.adminLogin(values.username, values.password);
    if (result.success && result.token) {
      setAdminToken(result.token);
      setAdminLoggedIn(true);
      setAdminUsername(result.username || '');
      setIsSuperAdmin(result.isSuperAdmin || false);
      setAdminLoginVisible(false);
      adminLoginForm.resetFields();
      message.success(`欢迎，${result.username}`);
      loadFiles();
    } else {
      message.error(result.message || '登录失败');
    }
  };

  const handleAdminLogout = async () => {
    await api.adminLogout();
    clearAdminToken();
    setAdminLoggedIn(false);
    setAdminUsername('');
    setIsSuperAdmin(false);
    message.success('已退出登录');
    loadFiles();
  };

  const handleAdminSetup = async (values: { username: string; password: string }) => {
    const result = await api.adminSetup(values.username, values.password);
    if (result.success) {
      message.success('管理员创建成功，请登录');
      setAdminSetupVisible(false);
      setHasAdmins(true);
      adminSetupForm.resetFields();
      setAdminLoginVisible(true);
    } else {
      message.error(result.message || '创建失败');
    }
  };

  // Admin user list state for admin management modal
  const [adminUsers, setAdminUsers] = useState<{ username: string; created_at: string }[]>([]);

  const loadAdminUsers = useCallback(async () => {
    const result = await api.getAdminUsers();
    if (result.success && result.data) {
      setAdminUsers(result.data);
    }
  }, []);

  useEffect(() => {
    if (adminManageVisible) {
      loadAdminUsers();
    }
  }, [adminManageVisible, loadAdminUsers]);

  const handleDeleteAdmin = async (username: string) => {
    const result = await api.deleteAdminUser(username);
    if (result.success) {
      message.success('管理员已删除');
      loadAdminUsers();
    } else {
      message.error(result.message || '删除失败');
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

  const handleUploadNewVersion = async (file: File) => {
    if (!versionFile) return;
    const result = await api.uploadNewVersion(versionFile.key, file);
    if (result.success) {
      message.success(`${versionFile.title} ${result.version} 版本更新成功`);
      loadFiles();
      // Refresh version list
      const vr = await api.getVersions(versionFile.key);
      if (vr.success && vr.data) {
        setVersionList(vr.data.versions || {});
        setCurrentVersion(vr.data.current_version || 'V1');
      }
      setVersionFileInputKey(k => k + 1);
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

  const handleVersionFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleUploadNewVersion(files[0]);
    }
    e.target.value = '';
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

  const themeItems: MenuProps['items'] = [
    { key: 'auto', label: <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>跟随系统 {themeMode === 'auto' && <CheckOutlined style={{ color: '#4285f4' }} />}</span> },
    { key: 'light', label: <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>浅色模式 {themeMode === 'light' && <CheckOutlined style={{ color: '#4285f4' }} />}</span> },
    { key: 'dark', label: <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>深色模式 {themeMode === 'dark' && <CheckOutlined style={{ color: '#4285f4' }} />}</span> },
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

  const onSortChange = (value: SortMode) => {
    localStorage.setItem('sortMode', value);
    setSortMode(value);
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

      {/* Uploader Filter */}
      <div style={{ padding: '16px 16px 8px', marginTop: 8, borderTop: `1px solid ${borderColor}` }}>
        <Text style={{ color: textSecondary, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 500 }}>
          上传者
        </Text>
      </div>

      <div
        onClick={() => { setSelectedIp(null); setDrawerVisible(false); }}
        style={{
          padding: '8px 16px',
          cursor: 'pointer',
          background: !selectedIp ? (currentTheme === 'dark' ? 'rgba(138,180,248,0.15)' : '#e8f0fe') : 'transparent',
          color: !selectedIp ? (currentTheme === 'dark' ? '#8ab4f8' : '#4285f4') : textColor,
          borderRadius: !selectedIp ? '0 8px 8px 0' : 0,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 13,
          fontWeight: !selectedIp ? 500 : 400,
          marginLeft: -16,
          paddingLeft: 24,
        }}
      >
        <GlobalOutlined />
        <span style={{ flex: 1 }}>全部</span>
        <Badge count={files.length} style={{ backgroundColor: currentTheme === 'dark' ? '#5f6368' : '#dadce0', color: textSecondary, fontSize: 10 }} />
      </div>

      {uniqueIps.map(ip => {
        const count = files.filter(f => f.uploader_ip === ip).length;
        return (
          <div
            key={ip}
            onClick={() => { setSelectedIp(ip); setDrawerVisible(false); }}
            style={{
              padding: '8px 16px',
              cursor: 'pointer',
              background: selectedIp === ip ? (currentTheme === 'dark' ? 'rgba(138,180,248,0.15)' : '#e8f0fe') : 'transparent',
              color: selectedIp === ip ? (currentTheme === 'dark' ? '#8ab4f8' : '#4285f4') : textColor,
              borderRadius: selectedIp === ip ? '0 8px 8px 0' : 0,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontSize: 13,
              fontWeight: selectedIp === ip ? 500 : 400,
              marginLeft: -16,
              paddingLeft: 24,
            }}
          >
            <DesktopOutlined />
            <span style={{ flex: 1, fontFamily: 'monospace', fontSize: 12 }}>{ip}</span>
            <Badge count={count} style={{ backgroundColor: currentTheme === 'dark' ? '#5f6368' : '#dadce0', color: textSecondary, fontSize: 10 }} />
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

          {/* Left: Logo & Title */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <img src={logoUrl} alt="logo" style={{ height: 28, width: 'auto' }} />
            <span className="header-title" style={{ fontSize: 18, fontWeight: 600, color: textColor, whiteSpace: 'nowrap' }}>
              原型极速分享平台
            </span>
          </div>

          {/* Center: Search */}
          <div style={{ flex: 1, maxWidth: 400, margin: '0 24px' }} className="header-search">
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
            {adminLoggedIn ? (
              <>
                {isSuperAdmin && (
                  <Button
                    type="text"
                    style={{ color: textColor, height: 36, padding: '0 12px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 6 }}
                    onClick={() => setAdminManageVisible(true)}
                  >
                    <TeamOutlined />
                    管理员
                  </Button>
                )}
                <Button
                  type="text"
                  style={{ color: textSecondary, height: 36, padding: '0 12px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 6 }}
                  onClick={handleAdminLogout}
                >
                  <LogoutOutlined />
                  {adminUsername}
                </Button>
              </>
            ) : (
              <Button
                type="text"
                style={{ color: textColor, height: 36, padding: '0 12px', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 6 }}
                onClick={() => {
                  if (hasAdmins) {
                    setAdminLoginVisible(true);
                  } else {
                    setAdminSetupVisible(true);
                  }
                }}
              >
                <UserOutlined />
                {hasAdmins ? '管理员登录' : '设置管理员'}
              </Button>
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
                  <span style={{ fontSize: 13, opacity: 0.8 }}>排序:</span>
                  {[
                    { key: 'time_desc' as SortMode, label: '默认' },
                    { key: 'product_line' as SortMode, label: '产品线' },
                    { key: 'ip' as SortMode, label: '上传者' },
                  ].map(opt => (
                    <Button
                      key={opt.key}
                      size="small"
                      type={sortMode === opt.key ? 'primary' : 'text'}
                      onClick={() => onSortChange(opt.key)}
                      style={{
                        borderRadius: 16,
                        padding: '2px 12px',
                        height: 28,
                        fontSize: 12,
                        ...(sortMode === opt.key ? {} : { color: 'rgba(255,255,255,0.85)', borderColor: 'rgba(255,255,255,0.3)' }),
                      }}
                    >
                      {opt.label}
                    </Button>
                  ))}
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
                    onClick={() => fileInputRef.current?.click()}
                    className="file-card upload-card"
                    style={{
                      background: isDragging
                        ? (currentTheme === 'dark' ? 'rgba(138,180,248,0.2)' : '#e8f0fe')
                        : cardBg,
                      border: `2px dashed ${isDragging ? (currentTheme === 'dark' ? '#8ab4f8' : '#4285f4') : borderColor}`,
                      borderRadius: 12,
                      minHeight: 120,
                      cursor: 'pointer',
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
                    {isDragging ? (
                      <>
                        <InboxOutlined style={{ fontSize: 28, color: currentTheme === 'dark' ? '#8ab4f8' : '#4285f4', marginBottom: 8 }} />
                        <div style={{ color: currentTheme === 'dark' ? '#8ab4f8' : '#4285f4', fontSize: 13 }}>释放以上传</div>
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
                    return (
                      <Card
                        key={file.key}
                        hoverable
                        onClick={() => handleCardClick(file)}
                        className="file-card"
                        style={{
                          background: cardBg,
                          border: `1px solid ${borderColor}`,
                          borderRadius: 12,
                          cursor: 'pointer',
                        }}
                        bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column', height: '100%' }}
                      >
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
                            {file.hasPassword && (
                              <Tooltip title={file.canDelete ? '已加密，点击修改' : '已加密'}>
                                <Button
                                  size="small"
                                  type="text"
                                  icon={<LockOutlined />}
                                  onClick={(e) => { e.stopPropagation(); file.canDelete && handleSetPassword(file); }}
                                  style={{ color: '#f5a623', flexShrink: 0, cursor: file.canDelete ? 'pointer' : 'default' }}
                                />
                              </Tooltip>
                            )}
                            {file.canDelete && !file.hasPassword && (
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
                            {file.canDelete && (
                              <Tooltip title="上传新版本">
                                <Button
                                  size="small"
                                  type="text"
                                  icon={<PlusOutlined />}
                                  onClick={(e) => { e.stopPropagation(); document.getElementById(`version-upload-${file.key.replace(/[^a-zA-Z0-9]/g, '_')}`)?.click(); }}
                                  style={{ color: textSecondary, flexShrink: 0 }}
                                />
                              </Tooltip>
                            )}
                            <input
                              id={`version-upload-${file.key.replace(/[^a-zA-Z0-9]/g, '_')}`}
                              type="file"
                              accept=".html,.HTML"
                              style={{ display: 'none' }}
                              onChange={(e) => {
                                const f = e.target.files?.[0];
                                if (f) {
                                  if (!file.canDelete) {
                                    message.error(`${file.title}：暂无编辑权限`);
                                  } else {
                                    handleUploadNewVersion(f);
                                  }
                                }
                                e.target.value = '';
                              }}
                            />
                            {file.canDelete && (
                              <Button
                                size="small"
                                type="text"
                                icon={<EditOutlined />}
                                onClick={(e) => { e.stopPropagation(); handleEdit(file); }}
                                style={{ color: textSecondary, flexShrink: 0 }}
                              />
                            )}
                          </div>
                        </div>

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
                            {file.canDelete && (
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
                                  danger
                                  icon={<DeleteOutlined />}
                                  onClick={(e) => e.stopPropagation()}
                                  style={{
                                    flexShrink: 0,
                                    borderColor: currentTheme === 'dark' ? '#ff7875' : undefined,
                                  }}
                                />
                              </Popconfirm>
                            )}
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
                            {file.uploader_ip && (
                              <div style={{ fontSize: 11, color: textSecondary, fontFamily: 'monospace' }}>
                                {file.uploader_ip}
                              </div>
                            )}
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

              {/* Refresh Button */}
              <div style={{ textAlign: 'center', marginTop: 24 }}>
                <Button icon={<ReloadOutlined />} onClick={loadFiles} style={{ borderRadius: 20 }}>
                  刷新列表
                </Button>
              </div>
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

      {/* Admin Login Modal */}
      <Modal
        title="管理员登录"
        open={adminLoginVisible}
        onCancel={() => setAdminLoginVisible(false)}
        footer={null}
      >
        <Form form={adminLoginForm} onFinish={handleAdminLogin} style={{ marginTop: 24 }}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input placeholder="用户名" prefix={<UserOutlined />} />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="密码" prefix={<LockOutlined />} />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block>
              登录
            </Button>
          </Form.Item>
        </Form>
      </Modal>

      {/* Admin Setup Modal (when no admins exist) */}
      <Modal
        title="设置管理员"
        open={adminSetupVisible}
        onCancel={() => setAdminSetupVisible(false)}
        footer={null}
      >
        <div style={{ marginBottom: 16, color: textSecondary, fontSize: 13 }}>
          系统尚未设置管理员，请创建第一个管理员账号（将成为超级管理员）。
        </div>
        <Form form={adminSetupForm} onFinish={handleAdminSetup} style={{ marginTop: 16 }}>
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }, { min: 2, message: '用户名至少2字符' }]}>
            <Input placeholder="用户名（至少2字符）" prefix={<UserOutlined />} />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }, { min: 6, message: '密码至少6字符' }]}>
            <Input.Password placeholder="密码（至少6字符）" prefix={<LockOutlined />} />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" block>
              创建并登录
            </Button>
          </Form.Item>
        </Form>
      </Modal>

      {/* Admin Manage Modal */}
      <Modal
        title="管理员管理"
        open={adminManageVisible}
        onCancel={() => setAdminManageVisible(false)}
        footer={null}
        width={400}
      >
        <div style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 16, padding: 12, background: currentTheme === 'dark' ? '#3c4043' : '#f1f3f4', borderRadius: 8 }}>
            <Text style={{ color: textSecondary, fontSize: 12 }}>当前管理员</Text>
            <div style={{ marginTop: 4 }}>{adminUsername} {isSuperAdmin && <Badge status="success" text="超级管理员" />}</div>
          </div>

          {/* Change Password Section */}
          <div style={{ marginBottom: 16 }}>
            <Text style={{ color: textSecondary, fontSize: 12, display: 'block', marginBottom: 8 }}>修改密码</Text>
            <Space.Compact style={{ width: '100%' }}>
              <Input.Password placeholder="旧密码" id="oldAdminPassword" />
              <Input.Password placeholder="新密码" id="newAdminPassword2" />
              <Button type="primary" onClick={async () => {
                const oldPwd = (document.getElementById('oldAdminPassword') as HTMLInputElement).value;
                const newPwd = (document.getElementById('newAdminPassword2') as HTMLInputElement).value;
                if (!oldPwd || !newPwd) {
                  message.warning('请输入旧密码和新密码');
                  return;
                }
                if (newPwd.length < 6) {
                  message.warning('新密码至少6字符');
                  return;
                }
                const result = await api.changeAdminPassword(oldPwd, newPwd);
                if (result.success) {
                  message.success('密码已修改');
                  (document.getElementById('oldAdminPassword') as HTMLInputElement).value = '';
                  (document.getElementById('newAdminPassword2') as HTMLInputElement).value = '';
                } else {
                  message.error(result.message || '修改失败');
                }
              }}>修改</Button>
            </Space.Compact>
          </div>

          {isSuperAdmin && (
            <>
              {/* View Logs Button */}
              <div style={{ marginBottom: 16 }}>
                <Button block onClick={() => window.open('/logs?token=' + encodeURIComponent(getAdminToken() || ''), '_blank')}>
                  📋 查看系统日志
                </Button>
              </div>

              <div style={{ marginBottom: 16 }}>
                <Text style={{ color: textSecondary, fontSize: 12, display: 'block', marginBottom: 8 }}>添加新管理员</Text>
                <Space.Compact style={{ width: '100%' }}>
                  <Input placeholder="用户名" id="newAdminUsername" />
                  <Input.Password placeholder="密码" id="newAdminPassword" />
                  <Button type="primary" onClick={async () => {
                    const username = (document.getElementById('newAdminUsername') as HTMLInputElement).value;
                    const password = (document.getElementById('newAdminPassword') as HTMLInputElement).value;
                    if (!username || !password) {
                      message.warning('请输入用户名和密码');
                      return;
                    }
                    if (username.length < 2) {
                      message.warning('用户名至少2字符');
                      return;
                    }
                    const result = await api.addAdminUser(username, password);
                    if (result.success) {
                      message.success('添加成功');
                      (document.getElementById('newAdminUsername') as HTMLInputElement).value = '';
                      (document.getElementById('newAdminPassword') as HTMLInputElement).value = '';
                      loadAdminUsers();
                    } else {
                      message.error(result.message || '添加失败');
                    }
                  }}>添加</Button>
                </Space.Compact>
              </div>

              <div>
                <Text style={{ color: textSecondary, fontSize: 12, display: 'block', marginBottom: 8 }}>管理员列表</Text>
                {adminUsers.map(user => (
                  <div key={user.username} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${borderColor}` }}>
                    <div>
                      <UserOutlined style={{ marginRight: 8 }} />
                      {user.username}
                      {user.username === adminUsername && <Badge status="success" text="当前" style={{ marginLeft: 8 }} />}
                    </div>
                    {user.username !== adminUsername && (
                      <Button size="small" danger onClick={() => handleDeleteAdmin(user.username)}>
                        删除
                      </Button>
                    )}
                  </div>
                ))}
                {adminUsers.length === 0 && <Text style={{ color: textSecondary }}>暂无其他管理员</Text>}
              </div>
            </>
          )}
        </div>
      </Modal>

      {/* Version History Modal */}
      <Modal
        title={`版本历史 — ${versionFile?.title || ''}`}
        open={versionModalVisible}
        onCancel={() => setVersionModalVisible(false)}
        footer={null}
        width={500}
      >
        <div style={{ marginTop: 16 }}>
          {/* Upload new version */}
          <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => document.getElementById('version-file-input')?.click()}
            >
              上传新版本
            </Button>
            <input
              id="version-file-input"
              key={versionFileInputKey}
              type="file"
              accept=".html,.HTML"
              style={{ display: 'none' }}
              onChange={handleVersionFileInputChange}
            />
            <span style={{ color: textSecondary, fontSize: 12 }}>支持 HTML 文件</span>
          </div>

          {/* Version list */}
          <div>
            {Object.entries(versionList)
              .sort(([a], [b]) => {
                const numA = parseInt(a.replace('V', '')) || 0;
                const numB = parseInt(b.replace('V', '')) || 0;
                return numB - numA;
              })
              .map(([version, info]) => {
                const isCurrent = version === currentVersion;
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
                      background: isCurrent ? '#52c41a' : 'transparent',
                      border: `2px solid ${isCurrent ? '#52c41a' : '#d9d9d9'}`,
                      flexShrink: 0,
                    }} />
                    <span style={{
                      fontWeight: isCurrent ? 600 : 400,
                      color: isCurrent ? '#52c41a' : textColor,
                      minWidth: 40,
                    }}>
                      {version}
                    </span>
                    {isCurrent && (
                      <span style={{ fontSize: 11, color: '#52c41a', background: '#f6ffed', padding: '1px 6px', borderRadius: 4, border: '1px solid #b7eb8f' }}>
                        当前
                      </span>
                    )}
                    <span style={{ flex: 1, fontSize: 12, color: textSecondary }}>
                      {dateStr} {info.uploader_ip && `· ${info.uploader_ip}`}
                    </span>
                    <Button size="small" onClick={() => window.open(`/versions/${versionFile?.path}/${version}`, '_blank')}>
                      预览
                    </Button>
                    {!isCurrent && (
                      <Button size="small" onClick={() => handleRestoreVersion(version)}>
                        恢复此版本
                      </Button>
                    )}
                    {!isCurrent && versionFile?.canDelete && (
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
            {Object.keys(versionList).length === 0 && (
              <div style={{ textAlign: 'center', padding: '40px 0', color: textSecondary }}>
                暂无版本记录
              </div>
            )}
          </div>
        </div>
      </Modal>

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
            <Text style={{ color: textSecondary, fontSize: 12 }}>
              版本号: v{version}
            </Text>
          </div>
        </div>
      )}
    </ConfigProvider>
  );
}

export default App;
