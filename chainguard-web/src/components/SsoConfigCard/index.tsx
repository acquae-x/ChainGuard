import { Alert, App, Button, Card, Form, Input, Select, Space, Switch, Tag, Typography } from 'antd';
import { KeyOutlined } from '@ant-design/icons';
import { useEffect, useState } from 'react';
import { ROLE_LABELS } from '@/constants/status';
import { getSsoConfig, saveSsoConfig, type SsoConfig } from '@/services/account';

/** 租户级 OIDC 单点登录配置。客户端密钥只写不读——接口从不回显，本组件也不尝试展示。 */
export default function SsoConfigCard() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [config, setConfig] = useState<SsoConfig>();
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const saved = await getSsoConfig();
      setConfig(saved);
      form.setFieldsValue({
        enabled: saved.enabled, issuer: saved.issuer, clientId: saved.clientId,
        authorizationEndpoint: saved.authorizationEndpoint, tokenEndpoint: saved.tokenEndpoint,
        redirectUri: saved.redirectUri || `${window.location.origin}/user/sso-callback`,
        scopes: saved.scopes, emailClaim: saved.emailClaim, subjectClaim: saved.subjectClaim,
        allowedDomains: (saved.allowedDomains || []).join(','),
        autoProvision: saved.autoProvision, defaultRoleCode: saved.defaultRoleCode,
        clientSecret: undefined,
      });
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);

  const save = async () => {
    const values = await form.validateFields();
    const saved = await saveSsoConfig({
      ...values,
      allowedDomains: String(values.allowedDomains || '').split(',').map((item: string) => item.trim()).filter(Boolean),
    });
    setConfig(saved);
    form.setFieldValue('clientSecret', undefined);
    message.success(saved.enabled ? 'SSO 已启用；登录页的单点登录入口现在会跳转到该身份提供方。' : 'SSO 配置已保存（当前为关闭状态）。');
  };

  return (
    <Card
      title={<Space><KeyOutlined />企业单点登录（OIDC SSO）</Space>}
      loading={loading}
      extra={
        <Space>
          <Tag color={config?.clientSecretSet ? 'green' : 'default'}>{config?.clientSecretSet ? '客户端密钥已配置' : '未配置客户端密钥'}</Tag>
          <Tag color={config?.configured ? 'green' : 'default'}>{config?.configured ? '已启用' : '未启用'}</Tag>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="未配置完成前，登录页的 SSO 入口会明确提示不可用"
        description="配置齐全并启用后，登录页「企业单点登录（SSO）」才会跳转到身份提供方。客户端密钥加密存储，保存后任何接口都不会再回显，需要更换时直接填新值。"
      />
      <Form form={form} layout="vertical">
        <Form.Item name="enabled" label="启用 SSO" valuePropName="checked" extra="启用要求下方必填项齐全，否则保存会被拒绝。"><Switch /></Form.Item>
        <Form.Item name="issuer" label="Issuer" rules={[{ required: true, message: '请输入 IdP 的 issuer' }]}><Input placeholder="https://idp.example.com" /></Form.Item>
        <Form.Item name="clientId" label="Client ID" rules={[{ required: true, message: '请输入 Client ID' }]}><Input /></Form.Item>
        <Form.Item name="clientSecret" label="Client Secret" extra="留空表示不修改已保存的密钥。">
          <Input.Password autoComplete="new-password" placeholder={config?.clientSecretSet ? '已配置（如需更换请输入新密钥）' : '首次启用必须填写'} />
        </Form.Item>
        <Form.Item name="authorizationEndpoint" label="Authorization Endpoint" rules={[{ required: true, type: 'url', message: '请输入完整授权端点地址' }]}><Input placeholder="https://idp.example.com/authorize" /></Form.Item>
        <Form.Item name="tokenEndpoint" label="Token Endpoint" rules={[{ required: true, type: 'url', message: '请输入完整令牌端点地址' }]}><Input placeholder="https://idp.example.com/token" /></Form.Item>
        <Form.Item name="redirectUri" label="回调地址（Redirect URI）" rules={[{ required: true, message: '请输入回调地址' }]} extra="需在 IdP 侧登记同一地址。"><Input /></Form.Item>
        <Form.Item name="allowedDomains" label="允许的邮箱域名" extra="逗号分隔；用于把登录邮箱解析到本企业，域名不可与其他企业重复。"><Input placeholder="example.com,corp.example.com" /></Form.Item>
        <Form.Item name="emailClaim" label="邮箱 Claim"><Input placeholder="email" /></Form.Item>
        <Form.Item name="subjectClaim" label="用户标识 Claim"><Input placeholder="sub" /></Form.Item>
        <Form.Item name="autoProvision" label="首次登录自动加入" valuePropName="checked" extra="关闭时，IdP 认证成功但企业内无对应账号会被拒绝——更安全的默认。"><Switch /></Form.Item>
        <Form.Item name="defaultRoleCode" label="自动加入时的默认角色">
          <Select options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))} />
        </Form.Item>
        <Space>
          <Button type="primary" onClick={save}>保存 SSO 配置</Button>
          {config?.updatedAt && <Typography.Text type="secondary">最近更新：{new Date(config.updatedAt).toLocaleString()}</Typography.Text>}
        </Space>
      </Form>
    </Card>
  );
}
