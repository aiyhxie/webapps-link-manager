/**
 * 版本更新日志右侧抽屉组件
 *
 * 功能：
 * - 显示系统版本更新历史记录
 * - 按时间倒序展示所有版本
 * - 点击版本号可复制版本信息
 *
 * 使用方式：
 * <ChangelogModal visible={visible} onClose={onClose} />
 */

import { Drawer, Tag, Empty, message } from 'antd';
import type { ChangelogEntry } from '../types';

interface ChangelogModalProps {
  visible: boolean;
  entries: ChangelogEntry[];
  currentVersion: string;
  onClose: () => void;
}

const TYPE_COLORS: Record<string, string> = {
  security: 'red',
  feature: 'blue',
  fix: 'orange',
  other: 'default',
};

const TYPE_LABELS: Record<string, string> = {
  security: '安全修复',
  feature: '新功能',
  fix: '问题修复',
  other: '其他',
};

export default function ChangelogModal({ visible, entries, currentVersion, onClose }: ChangelogModalProps) {
  const handleCopyVersion = (entry: ChangelogEntry) => {
    const text = `[${entry.version}] ${entry.date.slice(0, 10)}\n${entry.changelog}`;
    navigator.clipboard.writeText(text).then(() => {
      message.success(`已复制 ${entry.version} 更新说明`);
    });
  };

  return (
    <Drawer
      title="📋 版本更新日志"
      open={visible}
      onClose={onClose}
      width={520}
    >
      {entries.length === 0 ? (
        <Empty description="暂无版本更新记录" style={{ margin: '40px 0' }} />
      ) : (
        <div style={{ marginTop: 8 }}>
          {entries.map((entry, index) => {
            const isLatest = entry.version === currentVersion;
            return (
              <div
                key={entry.version}
                style={{
                  padding: '16px 0',
                  borderBottom: index < entries.length - 1 ? '1px solid #f0f0f0' : 'none',
                }}
              >
                {/* 版本号 + 日期 + 类型标签 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span
                    onClick={() => handleCopyVersion(entry)}
                    style={{
                      fontWeight: 600,
                      fontSize: 15,
                      color: isLatest ? '#1677ff' : '#333',
                      cursor: 'pointer',
                      textDecoration: isLatest ? 'underline' : 'none',
                    }}
                    title="点击复制"
                  >
                    v{entry.version}
                  </span>
                  {isLatest && <Tag color="blue" style={{ margin: 0 }}>最新</Tag>}
                  <Tag color={TYPE_COLORS[entry.type] || 'default'} style={{ margin: 0 }}>
                    {TYPE_LABELS[entry.type] || entry.type}
                  </Tag>
                  <span style={{ fontSize: 12, color: '#999', marginLeft: 'auto' }}>
                    {entry.date.slice(0, 10)}
                  </span>
                </div>
                {/* 变更说明 */}
                <div
                  style={{
                    fontSize: 13,
                    color: '#555',
                    lineHeight: 1.8,
                    whiteSpace: 'pre-wrap',
                    marginLeft: 4,
                  }}
                >
                  {entry.changelog}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Drawer>
  );
}
