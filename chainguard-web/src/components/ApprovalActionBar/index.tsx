import { AuditOutlined, CheckOutlined, CloseOutlined, RetweetOutlined, RollbackOutlined, SendOutlined, SwapOutlined } from '@ant-design/icons';
import { Button, Checkbox, Form, Input, Modal, Select, Space, message } from 'antd';
import { useState } from 'react';

export type ApprovalActionCapabilities = {
  approve?: boolean;
  submit?: boolean;
  withdraw?: boolean;
  countersign?: boolean;
  reviewActions?: boolean;
  // 会签人只有拒签权：显示驳回但不显示重算/转交（后端对会签人越权动作返回 403）
  rejectOnly?: boolean;
  ratify?: boolean;
  // 存在执行确认点时，批准前必须勾选"已逐项核对"（评审修复：确认点不能只是展示）
  requireConfirmPoints?: boolean;
};

export default function ApprovalActionBar({
  capabilities,
  onDone
}: {
  capabilities: ApprovalActionCapabilities;
  onDone?: (action: string, values?: any) => void | Promise<void>;
}) {
  const [action, setAction] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();
  // P0-1/P2-13 修复：所有审批动作的接口错误必须在当前上下文以 message 呈现，
  // 禁止让 Promise 拒绝冒泡成整页 Unhandled Rejection。
  const run = async (act: string, values?: any): Promise<boolean> => {
    setSubmitting(true);
    try {
      await onDone?.(act, values);
      return true;
    } catch (reason) {
      message.error(reason instanceof Error && reason.message ? reason.message : '审批操作失败，请稍后重试');
      return false;
    } finally {
      setSubmitting(false);
    }
  };
  const submit = async () => {
    let values: any;
    try {
      values = await form.validateFields();
    } catch {
      return; // 校验失败保持弹窗，antd 已在表单项内联提示
    }
    const ok = await run(action || 'approve', values);
    if (ok) {
      setAction(undefined);
      form.resetFields();
    }
  };

  return (
    <>
      <Space wrap>
        {capabilities.approve && <Button type="primary" icon={<CheckOutlined />} onClick={() => setAction('approve')}>批准</Button>}
        {capabilities.submit && <Button type="primary" icon={<SendOutlined />} onClick={() => Modal.confirm({ title: '提交老板终批？', content: '提交后将进入高风险终批与并行会签。', okText: '确认提交', cancelText: '取消', onOk: () => run('submit') })}>提交</Button>}
        {capabilities.withdraw && <Button icon={<RollbackOutlined />} onClick={() => Modal.confirm({ title: '撤回高风险审批单？', okText: '确认撤回', cancelText: '取消', onOk: () => run('withdraw') })}>撤回</Button>}
        {capabilities.countersign && <Button type="primary" icon={<AuditOutlined />} onClick={() => Modal.confirm({ title: '确认财务会签通过？', content: '会签意见将进入审批链并写入审计记录。', okText: '会签通过', cancelText: '取消', onOk: () => run('countersign') })}>会签</Button>}
        {capabilities.ratify && <Button type="primary" icon={<AuditOutlined />} onClick={() => Modal.confirm({ title: '追认通过？', content: '超时放行不会回滚任务，本操作将留痕并通知相关人员。', onOk: () => run('ratify_approve') })}>追认通过</Button>}
        {capabilities.ratify && <Button danger onClick={() => setAction('ratify_object')}>追认异议</Button>}
        {(capabilities.reviewActions || capabilities.rejectOnly) && <Button danger icon={<CloseOutlined />} onClick={() => setAction('reject')}>驳回</Button>}
        {capabilities.reviewActions && <Button icon={<RetweetOutlined />} onClick={() => setAction('recalc')}>要求重算</Button>}
        {capabilities.reviewActions && <Button icon={<SwapOutlined />} onClick={() => setAction('transfer')}>转交</Button>}
      </Space>
      <Modal
        title={action === 'approve' ? '确认批准方案' : action === 'reject' ? '填写驳回理由' : action === 'recalc' ? '填写重算方向' : action === 'ratify_object' ? '填写追认异议理由' : '选择转交人'}
        open={!!action}
        onCancel={() => setAction(undefined)}
        onOk={submit}
        confirmLoading={submitting}
      >
        <Form form={form} layout="vertical">
          {action === 'transfer' && <Form.Item name="assignee" label="转交给" rules={[{ required: true, message: '请选择转交人' }]}><Select options={[{ label: '李娜', value: 'u-scm' }, { label: '王总', value: 'u-boss' }]} /></Form.Item>}
          <Form.Item name="reason" label="说明" rules={action === 'approve' ? [] : [{ required: true, message: '请填写说明' }]}><Input.TextArea rows={4} /></Form.Item>
          {action === 'approve' && capabilities.requireConfirmPoints && <Form.Item name="confirmationChecked" valuePropName="checked" initialValue={false} rules={[{ validator: (_, value) => (value ? Promise.resolve() : Promise.reject(new Error('请先逐项核对执行确认点'))) }]}><Checkbox>我已逐项核对上方"执行确认点"清单</Checkbox></Form.Item>}
          {(action === 'approve' || action === 'reject') && <Form.Item name="saveExperience" valuePropName="checked" initialValue={false}><Checkbox>存为经验</Checkbox></Form.Item>}
        </Form>
      </Modal>
    </>
  );
}
