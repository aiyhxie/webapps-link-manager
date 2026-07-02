/**
 * 密码设置弹窗组件
 *
 * 功能：
 * - 为文件设置访问密码
 * - 修改已有密码
 * - 清除密码保护
 *
 * 使用方式：
 * <PasswordModal visible={visible} currentPassword={pwd} onClose={onClose} onSubmit={onSubmit} onClearPassword={onClear} />
 */

import { Modal, Form, Input, Button, Space, message } from 'antd';
import { LockOutlined } from '@ant-design/icons';

// Props 接口
interface PasswordModalProps {
  visible: boolean;
  currentPassword: string | null;
  onClose: () => void;
  onSubmit: (password: string) => void;
  onClearPassword: () => void;
}

export default function PasswordModal({ visible, currentPassword, onClose, onSubmit, onClearPassword }: PasswordModalProps) {
  const [form] = Form.useForm();

  const handleSubmit = () => {
    form.validateFields().then((values) => {
      if (values.password && values.password.length < 4) {
        message.error('密码至少4位');
        return;
      }
      onSubmit(values.password || '');
    });
  };

  const handleAfterOpenChange = (open: boolean) => {
    if (open) {
      form.setFieldsValue({ password: currentPassword || '' });
    } else {
      form.resetFields();
    }
  };

  return (
    <Modal
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <LockOutlined />
          {currentPassword ? '修改密码' : '设置密码'}
        </span>
      }
      open={visible}
      onCancel={onClose}
      afterOpenChange={handleAfterOpenChange}
      footer={
        <Space>
          {currentPassword && (
            <Button danger onClick={onClearPassword}>
              清除密码
            </Button>
          )}
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" onClick={handleSubmit}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item
          name="password"
          label="访问密码"
          tooltip="设置后，访问者需要输入密码才能查看此链接"
        >
          <Input.Password placeholder="请输入密码（至少4位，留空则清除密码）" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
