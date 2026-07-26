import { PageContainer, ProTable } from '@ant-design/pro-components';
import { App, Alert, Button, Drawer, Form, Input, InputNumber, Popconfirm, Select, Space, Table, Tag, Typography } from 'antd';
import { PlusOutlined, UserAddOutlined } from '@ant-design/icons';
import { useCallback, useEffect, useState } from 'react';
import { ROLE_LABELS } from '@/constants/status';
import { createUser, getDepartments, getUsers, resetUserPassword } from '@/services/settings';
import {
  createInvitation, getInvitations, getPasswordResetRequests, revokeInvitation, unlockUser,
  type Invitation, type PasswordResetRequestRow,
} from '@/services/account';

const INVITATION_STATUS: Record<Invitation['status'], { text: string; color: string }> = {
  active: { text: '生效中', color: 'green' },
  revoked: { text: '已失效', color: 'red' },
  expired: { text: '已过期', color: 'default' },
  exhausted: { text: '已用尽', color: 'orange' },
};

export default function Users() {
  // 用 App.useApp() 取代静态 message/Modal，消除 "Static function can not consume context" 警告。
  const { message, modal } = App.useApp();
  const [open, setOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [departments, setDepartments] = useState<API.Department[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [resets, setResets] = useState<PasswordResetRequestRow[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const show = async () => { setDepartments(await getDepartments()); setOpen(true); };

  const loadAccountState = useCallback(async () => {
    const [codes, pending] = await Promise.all([getInvitations(), getPasswordResetRequests()]);
    setInvitations(codes);
    setResets(pending);
  }, []);
  useEffect(() => { void loadAccountState(); }, [loadAccountState, reloadKey]);

  // 重置密码必须先确认，成功后用 Modal 持久展示一次性临时密码（可复制）。
  const doReset = async (row: API.User) => {
    const result = await resetUserPassword(row.id);
    modal.success({
      title: `已重置 ${row.name} 的密码`,
      content: (
        <div>
          <Typography.Paragraph>一次性临时密码（仅显示一次，请安全转交，该用户首次登录须改密）：</Typography.Paragraph>
          <Typography.Paragraph copyable strong>{result.temporaryPassword}</Typography.Paragraph>
        </div>
      ),
    });
    setReloadKey((value) => value + 1);
  };

  const doUnlock = async (row: API.User) => {
    await unlockUser(row.id);
    message.success(`${row.name} 的账号已解锁`);
    setReloadKey((value) => value + 1);
  };

  // 邀请码明文只在生成的这一次拿得到，之后列表里只有掩码——所以必须让管理员当场复制走。
  const doCreateInvitation = async (values: any) => {
    const result = await createInvitation(values);
    setInviteOpen(false);
    await loadAccountState();
    modal.success({
      title: '邀请码已生成',
      content: (
        <div>
          <Typography.Paragraph>
            请立即复制并转交受邀同事：该邀请码<strong>仅显示这一次</strong>，之后列表中只保留掩码。
          </Typography.Paragraph>
          <Typography.Paragraph copyable strong data-testid="invitation-code" style={{ fontSize: 20, letterSpacing: 2 }}>{result.code}</Typography.Paragraph>
          <Typography.Paragraph type="secondary">
            预设角色 {ROLE_LABELS[result.invitation.roleCode] || result.invitation.roleCode}，
            可用 {result.invitation.maxUses} 次，有效期至 {new Date(result.invitation.expiresAt).toLocaleString()}。
            受邀人访问「加入已有企业」页填写此码即可。
          </Typography.Paragraph>
        </div>
      ),
    });
  };

  const doRevoke = async (row: Invitation) => {
    await revokeInvitation(row.id);
    message.success('邀请码已失效');
    await loadAccountState();
  };

  const pendingResets = resets.filter((item) => item.status === 'pending');

  return (
    <PageContainer
      title="用户管理"
      extra={
        <Space wrap>
          <Button icon={<UserAddOutlined />} onClick={() => setInviteOpen(true)}>生成邀请码</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={show}>添加用户</Button>
        </Space>
      }
    >
      {/* 邮件/短信通道未接时，自助找回会落到这里等管理员兜底 —— 不显示出来这条降级链路就断了 */}
      {pendingResets.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`有 ${pendingResets.length} 条待处理的找回密码申请`}
          description={`申请人：${pendingResets.map((item) => `${item.userName}（${item.account}）`).join('、')}。请在下方对应用户行点击「重置密码」，把一次性临时密码安全转交本人。`}
        />
      )}

      <ProTable<API.User>
        rowKey="id"
        request={getUsers}
        params={{ reloadKey }}
        scroll={{ x: 1080 }}
        columns={[
          { title: '姓名', dataIndex: 'name', width: 110, ellipsis: true },
          { title: '手机号', dataIndex: 'phone', width: 130 },
          { title: '邮箱', dataIndex: 'email', width: 200, ellipsis: true },
          { title: '角色', dataIndex: 'roleCode', width: 130, valueType: 'select', valueEnum: Object.fromEntries(Object.entries(ROLE_LABELS).map(([key, text]) => [key, { text }])), render: (_, row) => <Tag color="blue">{ROLE_LABELS[row.roleCode]}</Tag> },
          { title: '数据范围', dataIndex: 'dataScope', width: 110, valueEnum: { all: { text: '全企业' }, dept: { text: '本部门' }, custom: { text: '自定义' } } },
          {
            title: '状态', dataIndex: 'status', width: 130,
            render: (_, row: any) => (
              <Space size={4} wrap>
                <Tag color={row.status === 'active' ? 'green' : 'default'}>{row.status === 'active' ? '启用' : '未启用'}</Tag>
                {row.locked && <Tag color="red">已锁定</Tag>}
                {row.ssoLinked && <Tag color="geekblue">SSO</Tag>}
              </Space>
            ),
          },
          {
            title: '操作', valueType: 'option', width: 240, fixed: 'right',
            render: (_, row: any) => [
              <Button key="edit" type="link">编辑</Button>,
              <Popconfirm key="reset" title="确认重置该用户密码？" description="将生成一次性临时密码，并强制该用户首次登录修改密码。" okText="确认重置" cancelText="取消" onConfirm={() => doReset(row)}>
                <Button type="link">重置密码</Button>
              </Popconfirm>,
              row.locked ? (
                <Popconfirm key="unlock" title="确认解锁该账号？" description="解锁后失败计数清零，用户可立即用正确密码登录。" okText="确认解锁" cancelText="取消" onConfirm={() => doUnlock(row)}>
                  <Button type="link">解锁</Button>
                </Popconfirm>
              ) : null,
              <Button key="disable" type="link" danger>停用</Button>,
            ],
          },
        ]}
      />

      <Typography.Title level={5} style={{ marginTop: 24 }}>企业邀请码</Typography.Title>
      <Typography.Paragraph type="secondary">
        受邀人凭邀请码只能加入本企业，角色/部门/数据范围按生成时的预设生效；使用记录逐条留痕。
      </Typography.Paragraph>
      <Table<Invitation>
        rowKey="id"
        dataSource={invitations}
        pagination={false}
        scroll={{ x: 900 }}
        locale={{ emptyText: '还没有邀请码，点右上角「生成邀请码」创建。' }}
        columns={[
          { title: '邀请码', dataIndex: 'codeMasked', width: 150, render: (value) => <Typography.Text code>{value}</Typography.Text> },
          { title: '预设角色', dataIndex: 'roleCode', width: 130, render: (value) => <Tag color="blue">{ROLE_LABELS[value] || value}</Tag> },
          { title: '备注', dataIndex: 'note', ellipsis: true },
          { title: '使用', width: 100, render: (_, row) => `${row.usedCount}/${row.maxUses}` },
          { title: '有效期至', dataIndex: 'expiresAt', width: 180, render: (value) => new Date(value).toLocaleString() },
          { title: '状态', dataIndex: 'status', width: 100, render: (value: Invitation['status']) => <Tag color={INVITATION_STATUS[value].color}>{INVITATION_STATUS[value].text}</Tag> },
          {
            title: '已加入成员', width: 200,
            render: (_, row) => row.redemptions.length
              ? row.redemptions.map((item) => `${item.userName}（${new Date(item.createdAt).toLocaleDateString()}）`).join('、')
              : '—',
          },
          {
            title: '操作', width: 90, fixed: 'right',
            render: (_, row) => row.status === 'active' ? (
              <Popconfirm title="确认失效该邀请码？" description="失效后任何人都无法再用它加入企业，已加入的成员不受影响。" okText="确认失效" cancelText="取消" onConfirm={() => doRevoke(row)}>
                <Button type="link" danger>失效</Button>
              </Popconfirm>
            ) : '—',
          },
        ]}
      />

      <Drawer title="添加用户" width={460} open={open} onClose={() => setOpen(false)}>
        <Form layout="vertical" onFinish={async (values) => { await createUser(values); message.success('用户已添加并发送邀请'); setOpen(false); setReloadKey((value) => value + 1); }}>
          <Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="phone" label="手机号" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="deptId" label="部门" rules={[{ required: true }]}><Select options={departments.map((item) => ({ label: item.name, value: item.id }))} /></Form.Item>
          <Form.Item name="roleCode" label="角色" rules={[{ required: true }]}><Select options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))} /></Form.Item>
          <Button block type="primary" htmlType="submit" icon={<PlusOutlined />}>添加并邀请</Button>
        </Form>
      </Drawer>

      <Drawer title="生成企业邀请码" width={460} open={inviteOpen} onClose={() => setInviteOpen(false)}>
        <Form layout="vertical" initialValues={{ maxUses: 1, validHours: 72, dataScope: 'custom' }} onFinish={doCreateInvitation}>
          <Form.Item name="roleCode" label="预设角色" rules={[{ required: true, message: '请选择受邀人加入后的角色' }]}>
            <Select options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          <Form.Item name="maxUses" label="可使用次数" rules={[{ required: true }]}><InputNumber min={1} max={200} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="validHours" label="有效期（小时）" rules={[{ required: true }]}><InputNumber min={1} max={720} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="dataScope" label="数据范围">
            <Select options={[{ value: 'custom', label: '自定义' }, { value: 'dept', label: '本部门' }, { value: 'all', label: '全企业' }]} />
          </Form.Item>
          <Form.Item name="note" label="备注"><Input placeholder="例如：给采购部新同事" /></Form.Item>
          <Button block type="primary" htmlType="submit" icon={<UserAddOutlined />}>生成邀请码</Button>
        </Form>
      </Drawer>
    </PageContainer>
  );
}
