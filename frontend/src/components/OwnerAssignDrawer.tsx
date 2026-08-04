/**
 * 批量指定项目负责人（仅超级管理员可见）
 *
 * 为什么需要它：所有权从 IP 迁到飞书身份后，存量项目的 uploader_ip 反查不到人
 * （DHCP 会变、换网段就变），所以这批项目的 owner_id 是空的。在超管指定负责人
 * 之前，普通员工无法编辑它们 —— 这个抽屉就是把归属补上的地方。
 *
 * 默认只列「未指定负责人」的项目，因为那才是待处理的部分；也可以切到全部项目
 * 用于转移归属（比如同事离职）。
 */
import { useEffect, useMemo, useState } from 'react';
import { Drawer, Select, Button, Space, Checkbox, Input, Empty, Typography, message, theme } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import type { FileInfo, DirectoryUser } from '../types';

const { Text } = Typography;

interface OwnerAssignDrawerProps {
  visible: boolean;
  files: FileInfo[];
  users: DirectoryUser[];
  onClose: () => void;
  onSubmit: (keys: string[], ownerId: string) => void;
}

/** 后端单次最多接受 100 个项目标识 */
const MAX_BATCH = 100;

export default function OwnerAssignDrawer({
  visible, files, users, onClose, onSubmit,
}: OwnerAssignDrawerProps) {
  const { token } = theme.useToken();
  const [ownerId, setOwnerId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [onlyOwnerless, setOnlyOwnerless] = useState(true);
  const [keyword, setKeyword] = useState('');

  useEffect(() => {
    if (!visible) {
      setOwnerId(null);
      setSelected([]);
      setKeyword('');
      setOnlyOwnerless(true);
    }
  }, [visible]);

  const ownerlessCount = useMemo(
    () => files.filter(f => !f.ownerId).length, [files]);

  const visibleFiles = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return files.filter(f => {
      if (onlyOwnerless && f.ownerId) return false;
      if (!kw) return true;
      return f.title.toLowerCase().includes(kw) || f.path.toLowerCase().includes(kw);
    });
  }, [files, onlyOwnerless, keyword]);

  const allVisibleSelected = visibleFiles.length > 0
    && visibleFiles.every(f => selected.includes(f.key));

  const toggleAll = () => {
    if (allVisibleSelected) {
      setSelected(prev => prev.filter(k => !visibleFiles.some(f => f.key === k)));
    } else {
      const merged = new Set(selected);
      visibleFiles.forEach(f => merged.add(f.key));
      setSelected(Array.from(merged));
    }
  };

  const handleSubmit = () => {
    if (!ownerId) {
      message.warning('请先选择负责人');
      return;
    }
    if (selected.length === 0) {
      message.warning('请至少选择一个项目');
      return;
    }
    if (selected.length > MAX_BATCH) {
      message.warning(`单次最多指定 ${MAX_BATCH} 个项目，请分批处理`);
      return;
    }
    onSubmit(selected, ownerId);
  };

  return (
    <Drawer
      title="指定项目负责人"
      open={visible}
      onClose={onClose}
      width={560}
      footer={
        <Space style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
          <Text style={{ color: token.colorTextSecondary, fontSize: 12 }}>
            已选 {selected.length} 个项目
          </Text>
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" onClick={handleSubmit}
                    disabled={!ownerId || selected.length === 0}>
              指定负责人
            </Button>
          </Space>
        </Space>
      }
    >
      <div style={{ marginBottom: 16 }}>
        <Text style={{ fontSize: 12, color: token.colorTextSecondary, display: 'block', marginBottom: 6 }}>
          负责人
        </Text>
        <Select
          showSearch
          placeholder="搜索并选择同事"
          style={{ width: '100%' }}
          optionFilterProp="label"
          value={ownerId}
          onChange={setOwnerId}
          options={users.map(u => ({ label: u.name, value: u.userId }))}
          notFoundContent="没有可选用户"
        />
        <Text style={{ fontSize: 11, color: token.colorTextSecondary, display: 'block', marginTop: 6 }}>
          只能从登录过本系统的同事里选择。本系统未申请飞书通讯录权限，
          所以对方需要先用飞书登录一次才会出现在这里。
        </Text>
      </div>

      <div style={{ marginBottom: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
        <Input
          prefix={<SearchOutlined />}
          placeholder="按标题或路径筛选"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          allowClear
        />
      </div>

      <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Checkbox checked={onlyOwnerless} onChange={(e) => setOnlyOwnerless(e.target.checked)}>
          只看未指定负责人（{ownerlessCount}）
        </Checkbox>
        {visibleFiles.length > 0 && (
          <Button size="small" type="link" onClick={toggleAll}>
            {allVisibleSelected ? '取消全选' : '全选当前列表'}
          </Button>
        )}
      </div>

      {visibleFiles.length === 0 ? (
        <Empty description={onlyOwnerless ? '所有项目都已指定负责人' : '没有匹配的项目'}
               style={{ margin: '40px 0' }} />
      ) : (
        <div style={{ maxHeight: 'calc(100vh - 400px)', overflowY: 'auto' }}>
          {visibleFiles.map(f => (
            <label
              key={f.key}
              style={{
                display: 'flex', alignItems: 'flex-start', gap: 10,
                padding: '9px 4px', borderBottom: `1px solid ${token.colorSplit}`,
                cursor: 'pointer',
              }}
            >
              <Checkbox
                checked={selected.includes(f.key)}
                onChange={(e) => setSelected(prev =>
                  e.target.checked ? [...prev, f.key] : prev.filter(k => k !== f.key))}
              />
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 13, color: token.colorText, overflow: 'hidden',
                              textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {f.title}
                </div>
                <div style={{ fontSize: 11, color: token.colorTextTertiary, fontFamily: 'monospace',
                              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {f.path}
                </div>
                <div style={{ fontSize: 11, marginTop: 2,
                              color: f.ownerId ? token.colorTextSecondary : '#f5a623' }}>
                  {f.ownerId ? `当前负责人：${f.ownerName || f.ownerId}` : '未指定负责人'}
                </div>
              </div>
            </label>
          ))}
        </div>
      )}
    </Drawer>
  );
}
