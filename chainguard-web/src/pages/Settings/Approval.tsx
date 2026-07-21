import { PageContainer } from '@ant-design/pro-components';
import { Alert, Button, Card, Col, Form, Row, Select, Space, Spin, Steps, Switch, Tag, message } from 'antd';
import { useEffect, useState } from 'react';
import { ROLE_LABELS } from '@/constants/status';
import { getApprovalChain, saveApprovalChain, type ApprovalChain } from '@/services/settings';

const LEVELS: { key: 'low' | 'medium' | 'high'; label: string }[] = [
  { key: 'low', label: '低风险' },
  { key: 'medium', label: '中风险' },
  { key: 'high', label: '高风险' },
];

const roleOptions = Object.entries(ROLE_LABELS).map(([value, label]) => ({ label, value }));

// 此前本页只弹「审批流已保存」但不落库。现在读写 /settings/approval-chain（TenantConfig 版本化存储）。
export default function ApprovalSettings() {
  const [form] = Form.useForm();
  const [chain, setChain] = useState<ApprovalChain | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    getApprovalChain()
      .then((data) => {
        setChain(data);
        form.setFieldsValue({
          lowApprover: data.levels.low.approver,
          mediumApprover: data.levels.medium.approver,
          highApprover: data.levels.high.approver,
          highCountersign: data.levels.high.countersign,
          financeCountersign: data.financeCountersign,
        });
      })
      .catch((error) => message.error(error?.message || '读取审批流配置失败'))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const onFinish = async (values: any) => {
    setSaving(true);
    try {
      const saved = await saveApprovalChain({
        levels: {
          low: { approver: values.lowApprover, countersign: [] },
          medium: { approver: values.mediumApprover, countersign: [] },
          high: { approver: values.highApprover, countersign: values.highCountersign || [] },
        },
        financeCountersign: !!values.financeCountersign,
      });
      setChain(saved);
      message.success(`审批流已保存（版本 v${saved.version}）`);
    } catch (error: any) {
      message.error(error?.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const describe = (key: 'low' | 'medium' | 'high') => {
    const level = chain?.levels?.[key];
    if (!level) return '未配置';
    const approver = ROLE_LABELS[level.approver] || level.approver;
    const countersign = (level.countersign || []).map((code) => ROLE_LABELS[code] || code);
    return countersign.length ? `${approver} 审批 + ${countersign.join('、')} 会签` : `${approver} 直接批准`;
  };

  return (
    <PageContainer
      title="审批流配置"
      extra={chain?.configured ? <Tag color="blue">当前版本 v{chain.version}</Tag> : <Tag>使用默认配置</Tag>}
    >
      <Alert
        type="info"
        showIcon
        message="按风险等级指定审批人与会签角色；保存后对新提交的审批立即生效。"
        style={{ marginBottom: 16 }}
      />
      <Spin spinning={loading}>
        <Row gutter={16}>
          <Col xs={24} lg={14}>
            <Card title="风险分级审批链">
              <Steps
                direction="vertical"
                items={LEVELS.map((level) => ({ title: level.label, description: describe(level.key) }))}
              />
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card title="规则设置">
              <Form form={form} layout="vertical" onFinish={onFinish}>
                <Form.Item label="低风险审批人" name="lowApprover" rules={[{ required: true }]}>
                  <Select options={roleOptions} />
                </Form.Item>
                <Form.Item label="中风险审批人" name="mediumApprover" rules={[{ required: true }]}>
                  <Select options={roleOptions} />
                </Form.Item>
                <Form.Item label="高风险主审批人" name="highApprover" rules={[{ required: true }]}>
                  <Select options={roleOptions} />
                </Form.Item>
                <Form.Item label="高风险会签角色" name="highCountersign">
                  <Select mode="multiple" allowClear options={roleOptions} placeholder="可多选" />
                </Form.Item>
                <Form.Item label="启用财务会签" name="financeCountersign" valuePropName="checked">
                  <Switch />
                </Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit" loading={saving}>
                    保存
                  </Button>
                  <Button onClick={load} disabled={saving}>
                    重新载入
                  </Button>
                </Space>
              </Form>
            </Card>
          </Col>
        </Row>
      </Spin>
    </PageContainer>
  );
}
