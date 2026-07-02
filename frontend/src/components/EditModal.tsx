/**
 * 编辑文件信息弹窗组件
 *
 * 功能：
 * - 编辑文件标题、描述、产品线
 * - 根据标题/描述自动检测产品线（实时更新下拉选项）
 *
 * 使用方式：
 * <EditModal visible={visible} file={file} onClose={onClose} onSubmit={onSubmit} />
 */

import { Modal, Form, Input, Button, Space, Select } from 'antd';
import type { FileInfo } from '../types';
import { PRODUCT_LINE_OPTIONS } from '../types';

// Props 接口
interface EditModalProps {
  visible: boolean;
  file: FileInfo | null;
  onClose: () => void;
  onSubmit: (values: { title: string; description: string; productLine: string }) => void;
}

// 根据标题/描述自动检测产品线
function detectProductLine(title: string, description: string): string {
  const text = `${title} ${description}`.toLowerCase();

  // 关键词映射到产品线
  const keywords: Record<string, string> = {
    'ai医生': '康老板AI医生',
    'ai健康': '康老板健康',
    'ai商城': '康老板商城',
    '康店': '康店代理商',
    '康管家': '康管家',
    '旅途管家': '旅途管家',
    '老板云': '老板云',
    '老板帮': '老板帮',
    '幸福绩效': '幸福绩效',
    '飞联天下': '飞联天下',
    '创业天使': '创业天使',
    '会议系统': '会议系统',
    '加速中心': '加速中心',
    '数智化': '数智化',
    '自搭云': '自搭云',
    '企座': '企座',
  };

  for (const [keyword, productLine] of Object.entries(keywords)) {
    if (text.includes(keyword)) {
      return productLine;
    }
  }

  // 检查 title 是否包含产品线信息（因为 title 通常是文件名）
  for (const pl of PRODUCT_LINE_OPTIONS) {
    if (title.toLowerCase().includes(pl)) {
      return pl;
    }
  }

  return '';
}

export default function EditModal({ visible, file, onClose, onSubmit }: EditModalProps) {
  const [form] = Form.useForm();

  const handleValuesChange = (changedValues: { title?: string; description?: string }) => {
    if (changedValues.title !== undefined || changedValues.description !== undefined) {
      const title = changedValues.title ?? form.getFieldValue('title') ?? '';
      const description = changedValues.description ?? form.getFieldValue('description') ?? '';
      const detected = detectProductLine(title, description);
      if (detected) {
        form.setFieldValue('productLine', detected);
      }
    }
  };

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      onSubmit(values);
    });
  };

  // 重置表单当 file 变化时
  const handleAfterOpenChange = (open: boolean) => {
    if (open && file) {
      form.setFieldsValue({
        title: file.title,
        description: file.description || '',
        productLine: file.productLine || '',
      });
    } else if (!open) {
      form.resetFields();
    }
  };

  return (
    <Modal
      title="编辑文件信息"
      open={visible}
      onCancel={onClose}
      afterOpenChange={handleAfterOpenChange}
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>保存</Button>
        </Space>
      }
    >
      <Form
        form={form}
        layout="vertical"
        onValuesChange={handleValuesChange}
        style={{ marginTop: 16 }}
      >
        <Form.Item
          name="title"
          label="标题"
          rules={[{ required: true, message: '请输入标题' }]}
        >
          <Input placeholder="给文件起个名字" />
        </Form.Item>
        <Form.Item
          name="description"
          label="描述"
        >
          <Input.TextArea placeholder="可选，简要说明" rows={3} />
        </Form.Item>
        <Form.Item
          name="productLine"
          label="产品线"
          tooltip="根据标题和描述自动识别，也可手动选择"
        >
          <Select
            placeholder="选择或自动识别产品线"
            allowClear
            options={PRODUCT_LINE_OPTIONS.map(pl => ({ label: pl, value: pl }))}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
