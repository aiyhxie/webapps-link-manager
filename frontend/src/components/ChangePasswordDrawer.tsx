/**
 * 修改管理员密码右侧抽屉组件
 *
 * 使用方式：
 * <ChangePasswordDrawer visible={visible} onClose={onClose} />
 */
import { Drawer, Form, Input, Button, Space, message } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import { api } from '../api';

interface ChangePasswordDrawerProps {
  visible: boolean;
  onClose: () => void;
}

export default function ChangePasswordDrawer({ visible, onClose }: ChangePasswordDrawerProps) {
  const [form] = Form.useForm();

  const handleSubmit = () => {
    form.validateFields().then(async (values) => {
      const result = await api.changeAdminPassword(values.oldPassword, values.newPassword);
      if (result.success) {
        message.success('密码已修改');
        form.resetFields();
        onClose();
      } else {
        message.error(result.message || '修改失败');
      }
    });
  };

  const handleAfterOpenChange = (open: boolean) => {
    if (!open) {
      form.resetFields();
    }
  };

  return (
    <Drawer
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <LockOutlined />
          修改密码
        </span>
      }
      open={visible}
      onClose={onClose}
      afterOpenChange={handleAfterOpenChange}
      width={420}
      footer={
        <Space style={{ display: 'flex', justifyContent: 'flex-end', width: '100%' }}>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>保存</Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item
          name="oldPassword"
          label="旧密码"
          rules={[{ required: true, message: '请输入旧密码' }]}
        >
          <Input.Password placeholder="请输入旧密码" />
        </Form.Item>
        <Form.Item
          name="newPassword"
          label="新密码"
          rules={[{ required: true, message: '请输入新密码' }, { min: 6, message: '新密码至少6字符' }]}
        >
          <Input.Password placeholder="请输入新密码（至少6字符）" />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
