import { AuditOutlined, CheckOutlined, CloseOutlined, RetweetOutlined, RollbackOutlined, SendOutlined, SwapOutlined } from '@ant-design/icons';
import { Button, Checkbox, Form, Input, Modal, Select, Space, message } from 'antd';
import { useState } from 'react';

export type ApprovalActionCapabilities = {
  approve?: boolean;
  submit?: boolean;
  withdraw?: boolean;
  countersign?: boolean;
  reviewActions?: boolean;
};

export default function ApprovalActionBar({
  capabilities,
  onDone
}: {
  capabilities: ApprovalActionCapabilities;
  onDone?: (action: string, values?: any) => void | Promise<void>;
}) {
  const [action, setAction] = useState<string>();
  const [form] = Form.useForm();
  const submit = async () => {
    const values = await form.validateFields();
    await onDone?.(action || 'approve', values);
    message.success('审批动作已记录');
    setAction(undefined);
    form.resetFields();
  };

  return (
    <>
      <Space wrap>
        {capabilities.approve && <Button type="primary" icon={<CheckOutlined />} onClick={() => setAction('approve')}>批准</Button>}
        {capabilities.submit && <Button type="primary" icon={<SendOutlined />} onClick={() => Modal.confirm({ title: '提交老板终批？', content: '提交后将进入高风险终批与并行会签。', okText: '确认提交', cancelText: '取消', onOk: () => onDone?.('submit') })}>提交</Button>}
        {capabilities.withdraw && <Button icon={<RollbackOutlined />} onClick={() => Modal.confirm({ title: '撤回高风险审批单？', okText: '确认撤回', cancelText: '取消', onOk: () => onDone?.('withdraw') })}>撤回</Button>}
        {capabilities.countersign && <Button type="primary" icon={<AuditOutlined />} onClick={() => Modal.confirm({ title: '确认财务会签通过？', content: '会签意见将进入审批链并写入审计记录。', okText: '会签通过', cancelText: '取消', onOk: () => onDone?.('countersign') })}>会签</Button>}
        {capabilities.reviewActions && <Button danger icon={<CloseOutlined />} onClick={() => setAction('reject')}>驳回</Button>}
        {capabilities.reviewActions && <Button icon={<RetweetOutlined />} onClick={() => setAction('recalc')}>要求重算</Button>}
        {capabilities.reviewActions && <Button icon={<SwapOutlined />} onClick={() => setAction('transfer')}>转交</Button>}
      </Space>
      <Modal title={action === 'approve' ? '确认批准方案' : action === 'reject' ? '填写驳回理由' : action === 'recalc' ? '填写重算方向' : '选择转交人'} open={!!action} onCancel={() => setAction(undefined)} onOk={submit}>
        <Form form={form} layout="vertical">
          {action === 'transfer' && <Form.Item name="assignee" label="转交给" rules={[{ required: true, message: '请选择转交人' }]}><Select options={[{ label: '李娜', value: 'u-scm' }, { label: '王总', value: 'u-boss' }]} /></Form.Item>}
          <Form.Item name="reason" label="说明" rules={action === 'approve' ? [] : [{ required: true, message: '请填写说明' }]}><Input.TextArea rows={4} /></Form.Item>
          {(action === 'approve' || action === 'reject') && <Form.Item name="saveExperience" valuePropName="checked" initialValue={false}><Checkbox>存为经验</Checkbox></Form.Item>}
        </Form>
      </Modal>
    </>
  );
}
