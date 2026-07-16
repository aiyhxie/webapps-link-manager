/**
 * 系统日志右侧抽屉组件
 *
 * 功能：
 * - 展示结构化审计日志（项目增删改 / 管理员动作 / 访问记录）
 * - 支持按操作者、IP、事件类型（新增/修改/删除/登录访问）筛选，以及关键字搜索
 * - 分页展示，每页 100 条
 * - 所有已登录管理员（超级管理员/普通管理员）权限一致，均可查看全部日志
 *
 * 使用方式：
 * <LogsDrawer visible={visible} onClose={onClose} />
 */
import { useState, useEffect, useCallback } from 'react';
import { Drawer, Input, Select, Table, Tag, Pagination, Empty } from 'antd';
import type { LogEntry } from '../types';
import { api } from '../api';

interface LogsDrawerProps {
  visible: boolean;
  onClose: () => void;
}

const CATEGORY_LABELS: Record<string, { text: string; color: string }> = {
  project: { text: '项目', color: 'green' },
  admin: { text: '管理员', color: 'blue' },
  access: { text: '访问', color: 'orange' },
};

const ACTION_TYPE_OPTIONS = [
  { label: '全部事件', value: '' },
  { label: '新增', value: 'create' },
  { label: '修改', value: 'update' },
  { label: '删除', value: 'delete' },
  { label: '登录/访问', value: 'access' },
];

const PAGE_SIZE = 100;

export default function LogsDrawer({ visible, onClose }: LogsDrawerProps) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  const [q, setQ] = useState('');
  const [actor, setActor] = useState('');
  const [ip, setIp] = useState('');
  const [actionType, setActionType] = useState('');

  const loadLogs = useCallback(async (targetPage: number) => {
    setLoading(true);
    try {
      const result = await api.getLogs({
        q, actor, ip, actionType,
        page: targetPage,
        pageSize: PAGE_SIZE,
      });
      if (result.success) {
        setLogs(result.logs || []);
        setTotal(result.total || 0);
        setPage(result.page || targetPage);
      }
    } finally {
      setLoading(false);
    }
  }, [q, actor, ip, actionType]);

  // Reload from page 1 whenever filters change (while the drawer is open)
  useEffect(() => {
    if (visible) {
      loadLogs(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, q, actor, ip, actionType]);

  const columns = [
    { title: '时间', dataIndex: 'time', key: 'time', width: 150, render: (t: string) => t?.replace('T', ' ') },
    {
      title: '类别', dataIndex: 'category', key: 'category', width: 80,
      render: (cat: string) => {
        const info = CATEGORY_LABELS[cat] || { text: cat, color: 'default' };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    { title: '操作者', dataIndex: 'actor', key: 'actor', width: 120 },
    { title: '来源IP', dataIndex: 'ip', key: 'ip', width: 130 },
    {
      title: '操作', dataIndex: 'action', key: 'action', width: 110,
      render: (action: string) => (
        <span style={{ color: /删除|失败/.test(action) ? '#f5222d' : undefined }}>{action}</span>
      ),
    },
    { title: '项目/对象', dataIndex: 'target', key: 'target' },
    { title: '备注', dataIndex: 'detail', key: 'detail', ellipsis: true },
  ];

  return (
    <Drawer
      title="📋 系统日志"
      open={visible}
      onClose={onClose}
      width={860}
    >
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <Input
          placeholder="按关键字搜索…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          allowClear
          style={{ width: 200 }}
        />
        <Input
          placeholder="按操作者筛选"
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          allowClear
          style={{ width: 160 }}
        />
        <Input
          placeholder="按IP筛选"
          value={ip}
          onChange={(e) => setIp(e.target.value)}
          allowClear
          style={{ width: 160 }}
        />
        <Select
          value={actionType}
          onChange={setActionType}
          options={ACTION_TYPE_OPTIONS}
          style={{ width: 140 }}
        />
      </div>

      <Table
        rowKey={(r) => `${r.time}-${r.actor}-${r.action}-${r.target}`}
        columns={columns}
        dataSource={logs}
        loading={loading}
        pagination={false}
        size="small"
        scroll={{ x: 760 }}
        locale={{ emptyText: <Empty description="暂无匹配的日志记录" /> }}
      />

      <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
        <Pagination
          current={page}
          pageSize={PAGE_SIZE}
          total={total}
          showSizeChanger={false}
          showTotal={(t) => `共 ${t} 条`}
          onChange={(p) => loadLogs(p)}
        />
      </div>
    </Drawer>
  );
}
